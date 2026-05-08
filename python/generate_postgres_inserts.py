#!/usr/bin/env python3
"""Generate PostgreSQL/PostGIS INSERT statements for administrative areas."""

from __future__ import annotations

import argparse
import json
import secrets
import sys
import time
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from shapely.geometry import MultiPolygon, Polygon, mapping, shape

import generate_simplified_datasets as simplifier


OUTPUT_DIR = Path("generated-datasets")
DEFAULT_OUTPUT_FILE = OUTPUT_DIR / "italian_administrative_area_inserts.sql"
DEFAULT_ADMIN_CENTERS_FILE = Path("original-datasets/osm_IT_admin_centers.geojson")
DATASET_ORDER = ("regions", "provinces", "municipalities")
TYPE_BY_DATASET = {
    "regions": "region",
    "provinces": "province",
    "municipalities": "municipality",
}
SOURCE_DATASET_BY_DATASET = {
    "regions": "original-datasets/limits_IT_regions.geojson",
    "provinces": "original-datasets/limits_IT_provinces.geojson",
    "municipalities": "original-datasets/limits_IT_municipalities.geojson",
}
INSERT_COLUMNS = (
    "id",
    "type",
    "name",
    "search_name",
    "parent_region_id",
    "parent_province_id",
    "reg_name",
    "reg_istat_code",
    "reg_istat_code_num",
    "prov_name",
    "prov_istat_code",
    "prov_istat_code_num",
    "prov_acr",
    "com_istat_code",
    "com_istat_code_num",
    "com_catasto_code",
    "op_id",
    "opdm_id",
    "minint_elettorale",
    "minint_finloc",
    "admin_center_lat",
    "admin_center_lng",
    "admin_center",
    "admin_center_source",
    "bbox_min_lng",
    "bbox_min_lat",
    "bbox_max_lng",
    "bbox_max_lat",
    "bbox",
    "geometry",
    "simplified_geometry",
    "source_properties",
    "source_dataset",
    "source_updated_at",
)


@dataclass(frozen=True)
class SourceFeature:
    dataset: str
    admin_type: str
    source_path: Path
    properties: dict[str, Any]
    geometry: dict[str, Any]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate PostgreSQL/PostGIS INSERT statements from the original "
            "Italian boundary datasets and the existing simplified-geometry logic."
        )
    )
    parser.add_argument(
        "dataset",
        nargs="?",
        default="all",
        choices=["all", *DATASET_ORDER],
        help="Dataset to export. Default: all.",
    )
    parser.add_argument(
        "-o",
        "--output-file",
        type=Path,
        default=DEFAULT_OUTPUT_FILE,
        help=f"SQL output file. Default: {DEFAULT_OUTPUT_FILE}.",
    )
    parser.add_argument(
        "--admin-centers-file",
        type=Path,
        default=DEFAULT_ADMIN_CENTERS_FILE,
        help=(
            "Optional OSM administrative-centre GeoJSON file. "
            f"Default: {DEFAULT_ADMIN_CENTERS_FILE}."
        ),
    )
    parser.add_argument(
        "--no-admin-centers",
        action="store_true",
        help="Do not join administrative-centre coordinates.",
    )
    parser.add_argument(
        "--coverage-policy",
        choices=list(simplifier.DEFAULT_OUTPUT_SUFFIXES.keys()),
        default=simplifier.DEFAULT_COVERAGE_POLICY,
        help=f"Simplification coverage policy. Default: {simplifier.DEFAULT_COVERAGE_POLICY}.",
    )
    parser.add_argument(
        "--tolerance-meters",
        type=float,
        default=simplifier.DEFAULT_TOLERANCE_METERS,
        help=(
            "Douglas-Peucker simplification tolerance in meters. "
            f"Default: {simplifier.DEFAULT_TOLERANCE_METERS:g}."
        ),
    )
    parser.add_argument(
        "--minimum-part-area-sqm",
        type=float,
        default=simplifier.DEFAULT_MIN_PART_AREA_SQM,
        help=(
            "Minimum polygon-part area kept before bridge generation in free mode. "
            f"Default: {simplifier.DEFAULT_MIN_PART_AREA_SQM:g}."
        ),
    )
    parser.add_argument(
        "--bridge-width-meters",
        type=float,
        default=simplifier.DEFAULT_BRIDGE_WIDTH_METERS,
        help=(
            "Width in meters of bridge corridors used by the simplifier. "
            f"Default: {simplifier.DEFAULT_BRIDGE_WIDTH_METERS:g}."
        ),
    )
    parser.add_argument(
        "--fallback-multipliers",
        default=simplifier.DEFAULT_FALLBACK_MULTIPLIERS_RAW,
        help=(
            "Comma-separated simplification fallback multipliers. "
            f"Default: {simplifier.DEFAULT_FALLBACK_MULTIPLIERS_RAW}."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Optional per-dataset feature limit, useful for smoke tests.",
    )
    parser.add_argument(
        "--no-transaction",
        action="store_true",
        help="Do not wrap generated INSERT statements in BEGIN/COMMIT.",
    )
    return parser


def validate_args(args: argparse.Namespace) -> tuple[float, ...]:
    if args.tolerance_meters <= 0:
        raise ValueError("--tolerance-meters must be greater than 0")
    if args.minimum_part_area_sqm < 0:
        raise ValueError("--minimum-part-area-sqm must be greater than or equal to 0")
    if args.bridge_width_meters <= 0:
        raise ValueError("--bridge-width-meters must be greater than 0")
    if args.limit is not None and args.limit < 1:
        raise ValueError("--limit must be greater than 0")
    return simplifier.parse_fallback_multipliers(args.fallback_multipliers)


def uuid7() -> uuid.UUID:
    unix_ms = int(time.time() * 1000)
    random_a = secrets.randbits(12)
    random_b = secrets.randbits(62)
    value = (
        (unix_ms << 80)
        | (0x7 << 76)
        | (random_a << 64)
        | (0b10 << 62)
        | random_b
    )
    return uuid.UUID(int=value)


def selected_datasets(dataset: str) -> tuple[str, ...]:
    if dataset == "all":
        return DATASET_ORDER
    return (dataset,)


def load_source_features(dataset: str, limit: int | None) -> list[SourceFeature]:
    source_path = simplifier.DEFAULT_INPUTS[dataset]
    data = simplifier.load_feature_collection(source_path)
    features = data["features"] if limit is None else data["features"][:limit]
    return [
        SourceFeature(
            dataset=dataset,
            admin_type=TYPE_BY_DATASET[dataset],
            source_path=source_path,
            properties=feature["properties"],
            geometry=feature["geometry"],
        )
        for feature in features
    ]


def natural_key(admin_type: str, properties: dict[str, Any]) -> str:
    if admin_type == "region":
        return str(properties["reg_istat_code"])
    if admin_type == "province":
        return str(properties["prov_istat_code"])
    return str(properties["com_istat_code"])


def load_admin_centers(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    if not path.exists():
        return {}

    data = simplifier.load_feature_collection(path)
    centers: dict[tuple[str, str], dict[str, Any]] = {}
    code_by_type = {
        "region": "reg_istat_code",
        "province": "prov_istat_code",
        "municipality": "com_istat_code",
    }

    for feature in data["features"]:
        properties = feature.get("properties")
        if not isinstance(properties, dict):
            continue

        location_type = properties.get("location_type")
        code_key = code_by_type.get(str(location_type))
        if code_key is None:
            continue

        code = properties.get(code_key)
        if code is None:
            continue
        if not properties.get("admin_centre_has_coordinates"):
            continue

        key = (str(location_type), str(code))
        current = centers.get(key)
        if current is None or center_rank(properties) > center_rank(current):
            centers[key] = properties

    return centers


def center_rank(properties: dict[str, Any]) -> tuple[int, int]:
    return (
        1 if properties.get("source_matched") else 0,
        1 if properties.get("has_admin_centre") else 0,
    )


def normalize_search_name(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_value = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return " ".join(ascii_value.casefold().split())


def display_name(admin_type: str, properties: dict[str, Any]) -> str:
    if admin_type == "region":
        return str(properties["reg_name"])
    if admin_type == "province":
        return str(properties["prov_name"])
    return str(properties["name"])


def sql_string(value: Any) -> str:
    if value is None:
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


def sql_number(value: Any) -> str:
    if value is None:
        return "NULL"
    return str(value)


def sql_jsonb(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return sql_string(raw) + "::jsonb"


def sql_geometry_from_geojson(geometry: dict[str, Any], force_multi: bool) -> str:
    raw = json.dumps(geometry, ensure_ascii=False, separators=(",", ":"))
    expression = f"ST_SetSRID(ST_GeomFromGeoJSON({sql_string(raw)}), 4326)"
    if force_multi:
        return f"ST_Multi({expression})"
    return expression


def sql_point(longitude: Any, latitude: Any) -> str:
    if longitude is None or latitude is None:
        return "NULL"
    return f"ST_SetSRID(ST_MakePoint({sql_number(longitude)}, {sql_number(latitude)}), 4326)"


def sql_bbox(bbox: list[float]) -> str:
    min_lng, min_lat, max_lng, max_lat = bbox
    return (
        "ST_MakeEnvelope("
        f"{min_lng}, {min_lat}, {max_lng}, {max_lat}, 4326"
        ")"
    )


def normalized_polygonal_geojson(geometry_data: dict[str, Any]) -> dict[str, Any]:
    geometry = simplifier.normalize_polygonal_geometry(shape(geometry_data))
    if isinstance(geometry, Polygon):
        geometry = MultiPolygon([geometry])
    return mapping(geometry)


def simplified_geojson(
    feature: SourceFeature,
    min_part_area_sqm: float,
    bridge_width_meters: float,
    tolerance_meters: float,
    fallback_multipliers: Iterable[float],
    coverage_policy: str,
    stats: simplifier.DatasetStats,
) -> dict[str, Any]:
    transformed = simplifier.transform_feature(
        {
            "type": "Feature",
            "properties": feature.properties,
            "geometry": feature.geometry,
        },
        min_part_area_sqm=min_part_area_sqm,
        bridge_width_meters=bridge_width_meters,
        tolerance_meters=tolerance_meters,
        fallback_multipliers=fallback_multipliers,
        coverage_policy=coverage_policy,
        stats=stats,
    )
    simplified = transformed["geometry"]
    return simplified


def source_properties(
    properties: dict[str, Any],
    center: dict[str, Any] | None,
) -> dict[str, Any]:
    value: dict[str, Any] = {"boundary": properties}
    if center is not None:
        value["admin_center"] = center
    return value


def sql_row(
    feature: SourceFeature,
    area_id: uuid.UUID,
    parent_region_id: uuid.UUID | None,
    parent_province_id: uuid.UUID | None,
    center: dict[str, Any] | None,
    original_geometry: dict[str, Any],
    simplified_geometry: dict[str, Any],
) -> str:
    properties = feature.properties
    name = display_name(feature.admin_type, properties)
    original_shape = shape(feature.geometry)
    bbox = simplifier.build_bbox(original_shape)
    admin_center_lat = center.get("admin_centre_lat") if center else None
    admin_center_lng = center.get("admin_centre_lon") if center else None

    values = {
        "id": sql_string(area_id),
        "type": sql_string(feature.admin_type),
        "name": sql_string(name),
        "search_name": sql_string(normalize_search_name(name)),
        "parent_region_id": sql_string(parent_region_id),
        "parent_province_id": sql_string(parent_province_id),
        "reg_name": sql_string(properties.get("reg_name")),
        "reg_istat_code": sql_string(properties.get("reg_istat_code")),
        "reg_istat_code_num": sql_number(properties.get("reg_istat_code_num")),
        "prov_name": sql_string(properties.get("prov_name")),
        "prov_istat_code": sql_string(properties.get("prov_istat_code")),
        "prov_istat_code_num": sql_number(properties.get("prov_istat_code_num")),
        "prov_acr": sql_string(properties.get("prov_acr")),
        "com_istat_code": sql_string(properties.get("com_istat_code")),
        "com_istat_code_num": sql_number(properties.get("com_istat_code_num")),
        "com_catasto_code": sql_string(properties.get("com_catasto_code")),
        "op_id": sql_string(properties.get("op_id")),
        "opdm_id": sql_string(properties.get("opdm_id")),
        "minint_elettorale": sql_string(properties.get("minint_elettorale")),
        "minint_finloc": sql_string(properties.get("minint_finloc")),
        "admin_center_lat": sql_number(admin_center_lat),
        "admin_center_lng": sql_number(admin_center_lng),
        "admin_center": sql_point(admin_center_lng, admin_center_lat),
        "admin_center_source": sql_string(center.get("source") if center else None),
        "bbox_min_lng": sql_number(bbox[0]),
        "bbox_min_lat": sql_number(bbox[1]),
        "bbox_max_lng": sql_number(bbox[2]),
        "bbox_max_lat": sql_number(bbox[3]),
        "bbox": sql_bbox(bbox),
        "geometry": sql_geometry_from_geojson(original_geometry, force_multi=True),
        "simplified_geometry": sql_geometry_from_geojson(
            simplified_geometry,
            force_multi=False,
        ),
        "source_properties": sql_jsonb(source_properties(properties, center)),
        "source_dataset": sql_string(SOURCE_DATASET_BY_DATASET[feature.dataset]),
        "source_updated_at": "NULL",
    }

    rendered_values = ",\n  ".join(values[column] for column in INSERT_COLUMNS)
    return (
        "INSERT INTO italian_administrative_area (\n  "
        + ",\n  ".join(INSERT_COLUMNS)
        + "\n) VALUES (\n  "
        + rendered_values
        + "\n);"
    )


def parent_ids(
    feature: SourceFeature,
    ids_by_type_and_key: dict[tuple[str, str], uuid.UUID],
    included_types: set[str],
) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    properties = feature.properties
    parent_region_id = None
    parent_province_id = None

    if feature.admin_type in {"province", "municipality"} and "region" in included_types:
        reg_istat_code = properties.get("reg_istat_code")
        if reg_istat_code is not None:
            parent_region_id = ids_by_type_and_key.get(("region", str(reg_istat_code)))

    if feature.admin_type == "municipality" and "province" in included_types:
        prov_istat_code = properties.get("prov_istat_code")
        if prov_istat_code is not None:
            parent_province_id = ids_by_type_and_key.get(("province", str(prov_istat_code)))

    return parent_region_id, parent_province_id


def write_sql(args: argparse.Namespace, fallback_multipliers: Iterable[float]) -> None:
    datasets = selected_datasets(args.dataset)
    features = [
        feature
        for dataset in datasets
        for feature in load_source_features(dataset, args.limit)
    ]
    ids_by_feature = {id(feature): uuid7() for feature in features}
    ids_by_type_and_key = {
        (feature.admin_type, natural_key(feature.admin_type, feature.properties)): area_id
        for feature in features
        for area_id in [ids_by_feature[id(feature)]]
    }
    included_types = {TYPE_BY_DATASET[dataset] for dataset in datasets}
    centers = (
        {}
        if args.no_admin_centers
        else load_admin_centers(args.admin_centers_file)
    )
    stats = simplifier.DatasetStats()

    args.output_file.parent.mkdir(parents=True, exist_ok=True)
    with args.output_file.open("w", encoding="utf-8") as file:
        file.write("-- Generated by python/generate_postgres_inserts.py\n")
        file.write("-- Requires PostgreSQL with PostGIS enabled.\n")
        file.write(
            "-- Simplified geometries are produced by python/generate_simplified_datasets.py.\n"
        )
        file.write(
            "-- Original geometries are inserted as MultiPolygon; simplified "
            "geometries keep the simplifier's Polygon output.\n\n"
        )
        if not args.no_transaction:
            file.write("BEGIN;\n\n")

        for feature in features:
            area_id = ids_by_feature[id(feature)]
            parent_region_id, parent_province_id = parent_ids(
                feature=feature,
                ids_by_type_and_key=ids_by_type_and_key,
                included_types=included_types,
            )
            key = natural_key(feature.admin_type, feature.properties)
            center = centers.get((feature.admin_type, key))
            original_geometry = normalized_polygonal_geojson(feature.geometry)
            simplified_geometry = simplified_geojson(
                feature=feature,
                min_part_area_sqm=args.minimum_part_area_sqm,
                bridge_width_meters=args.bridge_width_meters,
                tolerance_meters=args.tolerance_meters,
                fallback_multipliers=fallback_multipliers,
                coverage_policy=args.coverage_policy,
                stats=stats,
            )
            file.write(
                sql_row(
                    feature=feature,
                    area_id=area_id,
                    parent_region_id=parent_region_id,
                    parent_province_id=parent_province_id,
                    center=center,
                    original_geometry=original_geometry,
                    simplified_geometry=simplified_geometry,
                )
            )
            file.write("\n\n")

        if not args.no_transaction:
            file.write("COMMIT;\n")

    print(
        "Generated "
        f"{len(features)} INSERT statements at {args.output_file} "
        f"(simplified_features={stats.features_processed}, "
        f"multipart_seen={stats.multipart_features}, "
        f"bridges_added={stats.bridges_added})."
    )


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        fallback_multipliers = validate_args(args)
        write_sql(args, fallback_multipliers)
    except ValueError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
