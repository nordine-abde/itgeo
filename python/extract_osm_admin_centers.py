#!/usr/bin/env python3
# Usage examples:
#   python3 python/extract_osm_admin_centers.py --osm-pbf original-datasets/italy-latest.osm.pbf
#   python3 python/extract_osm_admin_centers.py --download
#   python3 python/extract_osm_admin_centers.py --format formatted
"""Extract OSM administrative centre points for Italian locations."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import unicodedata
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_OSM_PBF = Path("original-datasets/italy-latest.osm.pbf")
DEFAULT_OUTPUT = Path("original-datasets/osm_IT_admin_centers.geojson")
DEFAULT_DOWNLOAD_URL = "https://download.geofabrik.de/europe/italy-latest.osm.pbf"
SOURCE_DATASETS = {
    "region": Path("original-datasets/limits_IT_regions.geojson"),
    "province": Path("original-datasets/limits_IT_provinces.geojson"),
    "municipality": Path("original-datasets/limits_IT_municipalities.geojson"),
}
ADMIN_LEVELS = {
    "4": "region",
    "6": "province",
    "8": "municipality",
}
ISTAT_CODE_LENGTHS = {
    "region": 2,
    "province": 3,
    "municipality": 6,
}
ISTAT_TAG_KEYS = (
    "ref:ISTAT",
    "ref:istat",
    "istat",
    "ISTAT",
    "codice_istat",
    "codice:istat",
)
NAME_TAG_KEYS = ("name", "name:it", "official_name", "short_name")
OSM_BASE_URL = "https://www.openstreetmap.org"


@dataclass(frozen=True)
class SourceLocation:
    kind: str
    name: str
    istat_code: str | None
    properties: dict[str, Any]


@dataclass
class OSMRelation:
    relation_id: int
    kind: str
    admin_level: str
    tags: dict[str, str]
    admin_centre_type: str | None = None
    admin_centre_id: int | None = None
    label_type: str | None = None
    label_id: int | None = None


@dataclass(frozen=True)
class OSMNode:
    node_id: int
    lon: float
    lat: float
    tags: dict[str, str]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Extract admin_centre members from OSM administrative boundary "
            "relations for Italian regions, provinces, and municipalities."
        )
    )
    parser.add_argument(
        "--osm-pbf",
        type=Path,
        default=DEFAULT_OSM_PBF,
        help=f"Path to the Italy OSM PBF extract. Default: {DEFAULT_OSM_PBF}.",
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help=(
            "Download the default Geofabrik Italy extract before extraction if "
            "the --osm-pbf file does not already exist."
        ),
    )
    parser.add_argument(
        "--download-url",
        default=DEFAULT_DOWNLOAD_URL,
        help=f"OSM PBF URL used with --download. Default: {DEFAULT_DOWNLOAD_URL}.",
    )
    parser.add_argument(
        "-o",
        "--output-file",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output GeoJSON path. Default: {DEFAULT_OUTPUT}.",
    )
    parser.add_argument(
        "--format",
        choices=["compact", "formatted"],
        default="compact",
        help="Write compact or formatted JSON output. Default: compact.",
    )
    parser.add_argument(
        "--include-unmatched",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Include OSM relations that could not be matched to the local "
            "Openpolis/ISTAT boundary datasets. Default: true."
        ),
    )
    return parser


def require_osmium():
    try:
        import osmium  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - import guard
        raise SystemExit(
            "Missing dependency `osmium`. Install dependencies with "
            "`python3 -m pip install -r requirements.txt`."
        ) from exc
    return osmium


def normalize_istat(raw_value: Any) -> str | None:
    if raw_value is None:
        return None
    value = re.sub(r"\D", "", str(raw_value))
    return value or None


def strip_location_prefix(value: str) -> str:
    normalized = normalize_name(value)
    prefixes = (
        "regione autonoma della ",
        "regione autonoma del ",
        "regione autonoma d ",
        "regione autonoma ",
        "regione della ",
        "regione del ",
        "regione d ",
        "regione ",
        "citta metropolitana di ",
        "citta metropolitana della ",
        "citta metropolitana del ",
        "libero consorzio comunale di ",
        "libero consorzio comunale della ",
        "libero consorzio comunale del ",
        "provincia autonoma di ",
        "provincia autonoma della ",
        "provincia autonoma del ",
        "provincia di ",
        "provincia della ",
        "provincia del ",
        "provincia d ",
        "comune di ",
        "comune della ",
        "comune del ",
        "comune d ",
    )
    for prefix in prefixes:
        if normalized.startswith(prefix):
            return normalized.removeprefix(prefix).strip()
    return normalized


def normalize_name(raw_value: Any) -> str:
    value = str(raw_value or "").strip().lower()
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = value.replace("'", " ").replace("`", " ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def relation_name_candidates(tags: dict[str, str]) -> set[str]:
    candidates: set[str] = set()
    for key in NAME_TAG_KEYS:
        raw_value = tags.get(key)
        if not raw_value:
            continue
        candidates.add(normalize_name(raw_value))
        candidates.add(strip_location_prefix(raw_value))
    return {candidate for candidate in candidates if candidate}


def source_name_candidates(location: SourceLocation) -> set[str]:
    properties = location.properties
    if location.kind == "region":
        values = {location.name, str(properties.get("reg_name") or "")}
    elif location.kind == "province":
        values = {
            location.name,
            str(properties.get("prov_name") or ""),
            str(properties.get("prov_acr") or ""),
        }
    else:
        values = {location.name, str(properties.get("name") or "")}

    candidates: set[str] = set()
    for value in values:
        candidates.add(normalize_name(value))
        candidates.add(strip_location_prefix(value))
    return {candidate for candidate in candidates if candidate}


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    if data.get("type") != "FeatureCollection":
        raise ValueError(f"{path} is not a GeoJSON FeatureCollection")
    return data


def source_location_from_feature(kind: str, feature: dict[str, Any]) -> SourceLocation:
    properties = dict(feature.get("properties") or {})
    if kind == "region":
        name = str(properties.get("reg_name") or properties.get("name") or "")
        istat_code = normalize_istat(properties.get("reg_istat_code"))
    elif kind == "province":
        name = str(properties.get("prov_name") or properties.get("name") or "")
        istat_code = normalize_istat(properties.get("prov_istat_code"))
    else:
        name = str(properties.get("name") or "")
        istat_code = normalize_istat(properties.get("com_istat_code"))

    return SourceLocation(
        kind=kind,
        name=name,
        istat_code=istat_code,
        properties=properties,
    )


def istat_variants(raw_value: str | None, kind: str) -> set[str]:
    if raw_value is None:
        return set()

    values = {raw_value}
    try:
        unpadded = str(int(raw_value))
    except ValueError:
        unpadded = raw_value

    values.add(unpadded)
    values.add(unpadded.zfill(ISTAT_CODE_LENGTHS[kind]))
    return values


def load_source_locations() -> tuple[
    dict[str, dict[str, SourceLocation]],
    dict[str, dict[str, SourceLocation | None]],
]:
    by_istat: dict[str, dict[str, SourceLocation]] = {
        kind: {} for kind in SOURCE_DATASETS
    }
    by_name: dict[str, dict[str, SourceLocation | None]] = {
        kind: {} for kind in SOURCE_DATASETS
    }

    for kind, path in SOURCE_DATASETS.items():
        data = load_json(path)
        for feature in data.get("features", []):
            location = source_location_from_feature(kind, feature)
            if location.istat_code:
                for istat_code in istat_variants(location.istat_code, kind):
                    by_istat[kind][istat_code] = location

            for candidate in source_name_candidates(location):
                existing = by_name[kind].get(candidate)
                if existing is None and candidate in by_name[kind]:
                    continue
                if existing is not None:
                    by_name[kind][candidate] = None
                else:
                    by_name[kind][candidate] = location

    return by_istat, by_name


def istat_from_tags(tags: dict[str, str]) -> str | None:
    for key in ISTAT_TAG_KEYS:
        istat_code = normalize_istat(tags.get(key))
        if istat_code:
            return istat_code
    return None


def match_source_location(
    relation: OSMRelation,
    by_istat: dict[str, dict[str, SourceLocation]],
    by_name: dict[str, dict[str, SourceLocation | None]],
) -> tuple[SourceLocation | None, str]:
    relation_istat = istat_from_tags(relation.tags)
    if relation_istat:
        for istat_code in istat_variants(relation_istat, relation.kind):
            match = by_istat[relation.kind].get(istat_code)
            if match:
                return match, "istat"

    ambiguous = False
    for candidate in relation_name_candidates(relation.tags):
        match = by_name[relation.kind].get(candidate)
        if match is None and candidate in by_name[relation.kind]:
            ambiguous = True
            continue
        if match is not None:
            return match, "name"

    if ambiguous:
        return None, "name_ambiguous"
    return None, "no_match"


def build_relation_collector(osmium_module):
    class RelationCollector(osmium_module.SimpleHandler):
        def __init__(self) -> None:
            super().__init__()
            self.relations: dict[int, OSMRelation] = {}
            self.node_refs: set[int] = set()

        def relation(self, relation) -> None:  # noqa: ANN001 - osmium callback
            tags = {tag.k: tag.v for tag in relation.tags}
            if tags.get("boundary") != "administrative":
                return
            admin_level = tags.get("admin_level")
            kind = ADMIN_LEVELS.get(str(admin_level))
            if kind is None:
                return

            osm_relation = OSMRelation(
                relation_id=relation.id,
                kind=kind,
                admin_level=str(admin_level),
                tags=tags,
            )
            for member in relation.members:
                if member.role == "admin_centre" and osm_relation.admin_centre_id is None:
                    osm_relation.admin_centre_type = member.type
                    osm_relation.admin_centre_id = member.ref
                    if member.type == "n":
                        self.node_refs.add(member.ref)
                elif member.role == "label" and osm_relation.label_id is None:
                    osm_relation.label_type = member.type
                    osm_relation.label_id = member.ref
                    if member.type == "n":
                        self.node_refs.add(member.ref)

            self.relations[relation.id] = osm_relation

    return RelationCollector()


def build_node_collector(osmium_module, node_refs: set[int]):
    class NodeCollector(osmium_module.SimpleHandler):
        def __init__(self) -> None:
            super().__init__()
            self.nodes: dict[int, OSMNode] = {}

        def node(self, node) -> None:  # noqa: ANN001 - osmium callback
            if node.id not in node_refs:
                return
            tags = {tag.k: tag.v for tag in node.tags}
            self.nodes[node.id] = OSMNode(
                node_id=node.id,
                lon=float(node.location.lon),
                lat=float(node.location.lat),
                tags=tags,
            )

    return NodeCollector()


def osm_object_url(osm_type: str | None, osm_id: int | None) -> str | None:
    if osm_type is None or osm_id is None:
        return None
    type_name = {"n": "node", "w": "way", "r": "relation"}.get(osm_type, osm_type)
    return f"{OSM_BASE_URL}/{type_name}/{osm_id}"


def add_if_present(properties: dict[str, Any], key: str, value: Any) -> None:
    if value is not None and value != "":
        properties[key] = value


def add_source_match_properties(
    properties: dict[str, Any],
    source_location: SourceLocation | None,
    match_method: str,
) -> None:
    properties["source_match_method"] = match_method
    if source_location is None:
        properties["source_matched"] = False
        return

    source_properties = source_location.properties
    properties["source_matched"] = True
    add_if_present(properties, "source_istat_code", source_location.istat_code)
    add_if_present(properties, "source_name", source_location.name)
    for key in (
        "reg_name",
        "reg_istat_code",
        "reg_istat_code_num",
        "prov_name",
        "prov_istat_code",
        "prov_istat_code_num",
        "prov_acr",
        "name",
        "com_istat_code",
        "com_istat_code_num",
        "com_catasto_code",
    ):
        add_if_present(properties, key, source_properties.get(key))


def node_properties(prefix: str, node: OSMNode | None) -> dict[str, Any]:
    if node is None:
        return {}
    properties: dict[str, Any] = {
        f"{prefix}_lon": node.lon,
        f"{prefix}_lat": node.lat,
    }
    for tag_key in ("name", "name:it", "place", "capital", "wikidata"):
        add_if_present(
            properties,
            f"{prefix}_{tag_key.replace(':', '_')}",
            node.tags.get(tag_key),
        )
    return properties


def build_feature(
    relation: OSMRelation,
    nodes: dict[int, OSMNode],
    source_location: SourceLocation | None,
    match_method: str,
) -> dict[str, Any]:
    admin_node = (
        nodes.get(relation.admin_centre_id)
        if relation.admin_centre_type == "n" and relation.admin_centre_id is not None
        else None
    )
    label_node = (
        nodes.get(relation.label_id)
        if relation.label_type == "n" and relation.label_id is not None
        else None
    )

    properties: dict[str, Any] = {
        "source": "OpenStreetMap",
        "source_license": "ODbL-1.0",
        "location_type": relation.kind,
        "osm_admin_level": relation.admin_level,
        "osm_relation_id": relation.relation_id,
        "osm_relation_url": f"{OSM_BASE_URL}/relation/{relation.relation_id}",
        "has_admin_centre": relation.admin_centre_id is not None,
        "admin_centre_has_coordinates": admin_node is not None,
    }
    for key in ("name", "name:it", "official_name", "short_name", "wikidata"):
        add_if_present(properties, f"osm_relation_{key.replace(':', '_')}", relation.tags.get(key))
    add_if_present(properties, "osm_relation_istat_code", istat_from_tags(relation.tags))
    add_if_present(properties, "admin_centre_osm_type", relation.admin_centre_type)
    add_if_present(properties, "admin_centre_osm_id", relation.admin_centre_id)
    add_if_present(
        properties,
        "admin_centre_osm_url",
        osm_object_url(relation.admin_centre_type, relation.admin_centre_id),
    )
    add_if_present(properties, "label_osm_type", relation.label_type)
    add_if_present(properties, "label_osm_id", relation.label_id)
    add_if_present(
        properties,
        "label_osm_url",
        osm_object_url(relation.label_type, relation.label_id),
    )
    properties.update(node_properties("admin_centre", admin_node))
    properties.update(node_properties("label", label_node))
    add_source_match_properties(properties, source_location, match_method)

    geometry = None
    if admin_node is not None:
        geometry = {
            "type": "Point",
            "coordinates": [admin_node.lon, admin_node.lat],
        }

    return {
        "type": "Feature",
        "properties": properties,
        "geometry": geometry,
    }


def download_extract(path: Path, download_url: str) -> None:
    if path.exists():
        print(f"Using existing OSM extract: {path}", file=sys.stderr)
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    request = urllib.request.Request(
        download_url,
        headers={"User-Agent": "itgeo-admin-center-extractor/1.0"},
    )
    print(f"Downloading {download_url} to {path}", file=sys.stderr)
    with urllib.request.urlopen(request) as response, tmp_path.open("wb") as file:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            file.write(chunk)
    tmp_path.replace(path)


def extract_admin_centers(args: argparse.Namespace) -> dict[str, Any]:
    osmium_module = require_osmium()
    if args.download:
        download_extract(args.osm_pbf, args.download_url)
    if not args.osm_pbf.exists():
        raise FileNotFoundError(
            f"{args.osm_pbf} does not exist. Download it first or run with --download."
        )

    by_istat, by_name = load_source_locations()

    relation_collector = build_relation_collector(osmium_module)
    relation_collector.apply_file(str(args.osm_pbf), locations=False)

    node_collector = build_node_collector(osmium_module, relation_collector.node_refs)
    node_collector.apply_file(str(args.osm_pbf), locations=True)

    features: list[dict[str, Any]] = []
    stats = {
        "relations_total": 0,
        "relations_with_admin_centre": 0,
        "relations_with_admin_centre_coordinates": 0,
        "relations_with_label_coordinates": 0,
        "relations_matched_to_source": 0,
        "relations_unmatched_to_source": 0,
    }
    by_type = {kind: 0 for kind in SOURCE_DATASETS}

    for relation in sorted(
        relation_collector.relations.values(),
        key=lambda item: (item.kind, item.relation_id),
    ):
        source_location, match_method = match_source_location(relation, by_istat, by_name)
        if source_location is None and not args.include_unmatched:
            continue

        feature = build_feature(
            relation,
            node_collector.nodes,
            source_location,
            match_method,
        )
        features.append(feature)

        stats["relations_total"] += 1
        by_type[relation.kind] += 1
        if relation.admin_centre_id is not None:
            stats["relations_with_admin_centre"] += 1
        if feature["properties"].get("admin_centre_has_coordinates"):
            stats["relations_with_admin_centre_coordinates"] += 1
        if "label_lon" in feature["properties"]:
            stats["relations_with_label_coordinates"] += 1
        if source_location is None:
            stats["relations_unmatched_to_source"] += 1
        else:
            stats["relations_matched_to_source"] += 1

    stats["relations_by_type"] = by_type
    return {
        "type": "FeatureCollection",
        "metadata": {
            "name": "Italian OSM administrative centre points",
            "description": (
                "Admin centre members from OpenStreetMap administrative boundary "
                "relations. Geometry is the admin_centre point when OSM provides "
                "a node member with coordinates; label node data is kept as "
                "separate properties and is not used as the feature geometry."
            ),
            "source": "OpenStreetMap",
            "source_license": "ODbL-1.0",
            "source_download_url": args.download_url,
            "source_extract_path": str(args.osm_pbf),
            "generated_at_utc": dt.datetime.now(dt.UTC).isoformat(),
            "admin_levels": ADMIN_LEVELS,
            "stats": stats,
        },
        "features": features,
    }


def write_geojson(path: Path, data: dict[str, Any], output_format: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        if output_format == "formatted":
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.write("\n")
        else:
            json.dump(data, file, ensure_ascii=False, separators=(",", ":"))


def main() -> None:
    args = build_parser().parse_args()
    try:
        data = extract_admin_centers(args)
        write_geojson(args.output_file, data, args.format)
    except Exception as exc:
        raise SystemExit(f"Error: {exc}") from exc

    stats = data["metadata"]["stats"]
    print(
        "Wrote "
        f"{stats['relations_total']} admin boundary records to {args.output_file} "
        f"({stats['relations_with_admin_centre_coordinates']} with admin-centre coordinates)."
    )


if __name__ == "__main__":
    main()
