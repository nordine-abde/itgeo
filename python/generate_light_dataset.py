#!/usr/bin/env python3
"""Generate a geometry-free JSONL dataset for Italian administrative areas."""

from __future__ import annotations

import argparse
import json
import math
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from shapely.geometry import shape
except ImportError as exc:  # pragma: no cover - import guard
    raise SystemExit(
        "Missing dependencies. Install them with "
        "`python3 -m pip install -r requirements.txt`."
    ) from exc


DATASET_ORDER = ("regions", "provinces", "municipalities")
DEFAULT_INPUTS = {
    "regions": Path("original-datasets/limits_IT_regions.geojson"),
    "provinces": Path("original-datasets/limits_IT_provinces.geojson"),
    "municipalities": Path("original-datasets/limits_IT_municipalities.geojson"),
}
DEFAULT_ADMIN_CENTERS_FILE = Path("original-datasets/osm_IT_admin_centers.geojson")
DEFAULT_OUTPUT_FILE = Path("datasets/italian_administrative_areas_light.jsonl")
TYPE_BY_DATASET = {
    "regions": "region",
    "provinces": "province",
    "municipalities": "municipality",
}
NAME_FIELD_BY_TYPE = {
    "region": "reg_name",
    "province": "prov_name",
    "municipality": "name",
}
CODE_FIELD_BY_TYPE = {
    "region": "reg_istat_code",
    "province": "prov_istat_code",
    "municipality": "com_istat_code",
}
BOUNDARY_SOURCE = {
    "provider": "openpolis/geojson-italy",
    "license": "CC-BY-4.0",
}
ADMIN_CENTER_SOURCE = {
    "provider": "OpenStreetMap",
    "license": "ODbL-1.0",
}


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
            "Generate a light JSONL dataset for Italian regions, provinces, "
            "and municipalities without geometries or PostGIS-specific fields."
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
        help=f"JSONL output file. Default: {DEFAULT_OUTPUT_FILE}.",
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
        "--limit",
        type=int,
        help="Optional per-dataset feature limit, useful for smoke tests.",
    )
    return parser


def selected_datasets(dataset: str) -> tuple[str, ...]:
    if dataset == "all":
        return DATASET_ORDER
    return (dataset,)


def load_feature_collection(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        data = json.load(file)

    if data.get("type") != "FeatureCollection":
        raise ValueError(f"{path} is not a GeoJSON FeatureCollection")
    if not isinstance(data.get("features"), list):
        raise ValueError(f"{path} does not contain a features array")

    return data


def load_source_features(dataset: str, limit: int | None) -> list[SourceFeature]:
    source_path = DEFAULT_INPUTS[dataset]
    data = load_feature_collection(source_path)
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
    code_key = CODE_FIELD_BY_TYPE[admin_type]
    code = properties.get(code_key)
    if code is None:
        raise ValueError(f"Missing {code_key} for {admin_type}")
    return str(code)


def stable_id(admin_type: str, properties: dict[str, Any]) -> str:
    return f"{admin_type}:{natural_key(admin_type, properties)}"


def display_name(admin_type: str, properties: dict[str, Any]) -> str:
    name_key = NAME_FIELD_BY_TYPE[admin_type]
    name = properties.get(name_key)
    if name is None:
        raise ValueError(f"Missing {name_key} for {admin_type}")
    return str(name)


def normalize_search_name(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_value = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return " ".join(ascii_value.casefold().split())


def build_bbox(geometry: dict[str, Any] | None) -> list[float] | None:
    if geometry is None:
        return None

    min_lng, min_lat, max_lng, max_lat = shape(geometry).bounds
    if any(math.isnan(value) for value in (min_lng, min_lat, max_lng, max_lat)):
        return None
    return [min_lng, min_lat, max_lng, max_lat]


def load_admin_centers(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    if not path.exists():
        return {}

    data = load_feature_collection(path)
    centers: dict[tuple[str, str], dict[str, Any]] = {}

    for feature in data["features"]:
        properties = feature.get("properties")
        if not isinstance(properties, dict):
            continue

        location_type = properties.get("location_type")
        if location_type not in CODE_FIELD_BY_TYPE:
            continue

        code = properties.get(CODE_FIELD_BY_TYPE[str(location_type)])
        if code is None or not properties.get("admin_centre_has_coordinates"):
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


def source_metadata(
    source_path: Path,
    center: dict[str, Any] | None,
    admin_centers_file: Path,
) -> dict[str, Any]:
    admin_center = None
    if center is not None:
        admin_center = {
            "dataset": str(admin_centers_file),
            **ADMIN_CENTER_SOURCE,
            "osmRelationId": center.get("osm_relation_id"),
            "osmRelationUrl": center.get("osm_relation_url"),
            "matchMethod": center.get("source_match_method"),
        }

    return {
        "boundary": {
            "dataset": str(source_path),
            **BOUNDARY_SOURCE,
        },
        "adminCenter": admin_center,
    }


def light_record(
    feature: SourceFeature,
    center: dict[str, Any] | None,
    admin_centers_file: Path,
) -> dict[str, Any]:
    admin_type = feature.admin_type
    properties = feature.properties
    name = display_name(feature.admin_type, feature.properties)
    return {
        "id": stable_id(admin_type, properties),
        "type": admin_type,
        "name": name,
        "searchName": normalize_search_name(name),
        "regionName": properties.get("reg_name"),
        "regionIstatCode": properties.get("reg_istat_code"),
        "regionIstatCodeNum": properties.get("reg_istat_code_num"),
        "provinceName": properties.get("prov_name"),
        "provinceIstatCode": properties.get("prov_istat_code"),
        "provinceIstatCodeNum": properties.get("prov_istat_code_num"),
        "provinceAcronym": properties.get("prov_acr"),
        "municipalityIstatCode": properties.get("com_istat_code"),
        "municipalityIstatCodeNum": properties.get("com_istat_code_num"),
        "cadastralCode": properties.get("com_catasto_code"),
        "parentRegionIstatCode": (
            properties.get("reg_istat_code")
            if admin_type in {"province", "municipality"}
            else None
        ),
        "parentProvinceIstatCode": (
            properties.get("prov_istat_code")
            if admin_type == "municipality"
            else None
        ),
        "centerLat": center.get("admin_centre_lat") if center else None,
        "centerLng": center.get("admin_centre_lon") if center else None,
        "bbox": build_bbox(feature.geometry),
        "sourceDataset": str(feature.source_path),
        "source": source_metadata(
            source_path=feature.source_path,
            center=center,
            admin_centers_file=admin_centers_file,
        ),
    }


def write_jsonl(args: argparse.Namespace) -> None:
    if args.limit is not None and args.limit < 1:
        raise ValueError("--limit must be greater than 0")

    datasets = selected_datasets(args.dataset)
    features = [
        feature
        for dataset in datasets
        for feature in load_source_features(dataset, args.limit)
    ]
    dataset_order = {
        dataset: index
        for index, dataset in enumerate(DATASET_ORDER)
    }
    features.sort(
        key=lambda feature: (
            dataset_order[feature.dataset],
            natural_key(feature.admin_type, feature.properties),
        )
    )

    centers = (
        {}
        if args.no_admin_centers
        else load_admin_centers(args.admin_centers_file)
    )

    args.output_file.parent.mkdir(parents=True, exist_ok=True)
    matched_centers = 0
    with args.output_file.open("w", encoding="utf-8") as file:
        for feature in features:
            key = (
                feature.admin_type,
                natural_key(feature.admin_type, feature.properties),
            )
            center = centers.get(key)
            if center is not None:
                matched_centers += 1
            record = light_record(
                feature=feature,
                center=center,
                admin_centers_file=args.admin_centers_file,
            )
            file.write(
                json.dumps(record, ensure_ascii=False, separators=(",", ":"))
                + "\n"
            )

    print(
        f"Generated {len(features)} records at {args.output_file} "
        f"(admin_centers_matched={matched_centers})."
    )


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        write_jsonl(args)
    except ValueError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
