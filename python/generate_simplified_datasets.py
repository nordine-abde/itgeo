#!/usr/bin/env python3
# Usage examples:
#   python3 python/generate_simplified_datasets.py all
#   python3 python/generate_simplified_datasets.py municipalities --format formatted
#   python3 python/generate_simplified_datasets.py provinces --tolerance-meters 750
#   python3 python/generate_simplified_datasets.py municipalities --minimum-part-area-sqm 500000
#   python3 python/generate_simplified_datasets.py regions --coverage-policy covers-original
#   python3 python/generate_simplified_datasets.py provinces --output-file provinces-cover.geojson
#
# Parameter guide:
#   dataset
#       all | regions | provinces | municipalities
#       Chooses which source GeoJSON file(s) to process.
#   --coverage-policy
#       free | covers-original
#       free keeps the current aggressive simplification flow.
#       covers-original forces the final polygon to cover the full source geometry.
#   -o, --output-file
#       File name written inside generated-datasets/.
#       Accepted only for single-dataset runs.
#   --tolerance-meters
#       Douglas-Peucker tolerance in meters.
#       Higher values remove more vertices and simplify more aggressively.
#   --minimum-part-area-sqm
#       Minimum polygon-part area kept from a MultiPolygon before bridging.
#       Smaller detached parts under this threshold are ignored in free mode.
#       covers-original mode always keeps all parts.
#   --bridge-width-meters
#       Width in meters of the artificial corridors used to connect disjoint parts.
#   --fallback-multipliers
#       Comma-separated multipliers applied to the configured tolerance when a
#       simplification attempt becomes invalid. Example: 1,0.5,0.25,0.125.
#   --format
#       compact for smaller files, formatted for easier manual inspection.
"""Generate simplified GeoJSON datasets from the original Italian boundaries."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

try:
    from pyproj import Transformer
    from shapely import make_valid
    from shapely.geometry import LineString, MultiPolygon, Polygon, mapping, shape
    from shapely.ops import nearest_points, transform, unary_union
except ImportError as exc:  # pragma: no cover - import guard
    raise SystemExit(
        "Missing dependencies. Install them with "
        "`python3 -m pip install -r requirements.txt`."
    ) from exc


DEFAULT_INPUTS = {
    "regions": Path("original-datasets/limits_IT_regions.geojson"),
    "provinces": Path("original-datasets/limits_IT_provinces.geojson"),
    "municipalities": Path("original-datasets/limits_IT_municipalities.geojson"),
}
OUTPUT_DIR = Path("generated-datasets")
SOURCE_CRS = "EPSG:4326"
PROJECTED_CRS = "EPSG:3035"
DEFAULT_COVERAGE_POLICY = "free"
DEFAULT_OUTPUT_SUFFIXES = {
    "free": "simplified",
    "covers-original": "covers-original",
}
DEFAULT_TOLERANCE_METERS = 1_000.0
DEFAULT_MIN_PART_AREA_SQM = 250_000.0
DEFAULT_BRIDGE_WIDTH_METERS = 250.0
DEFAULT_FALLBACK_MULTIPLIERS = (1.0, 0.5, 0.25, 0.125)
DEFAULT_FALLBACK_MULTIPLIERS_RAW = ",".join(
    f"{value:g}" for value in DEFAULT_FALLBACK_MULTIPLIERS
)
AREA_EPSILON_SQM = 1e-6
OUTER_COVER_BINARY_SEARCH_STEPS = 12
OUTER_COVER_SERIALIZATION_PASSES = 8
OUTER_COVER_BUFFER_QUAD_SEGS = 1
OUTER_COVER_BUFFER_JOIN_STYLE = 2
OUTER_COVER_SERIALIZATION_MARGIN_METERS = 0.001


TO_METRIC = Transformer.from_crs(
    SOURCE_CRS,
    PROJECTED_CRS,
    always_xy=True,
)
TO_SOURCE = Transformer.from_crs(
    PROJECTED_CRS,
    SOURCE_CRS,
    always_xy=True,
)


@dataclass
class DatasetStats:
    features_processed: int = 0
    multipart_features: int = 0
    parts_removed_by_area: int = 0
    bridges_added: int = 0
    simplification_attempts: int = 0
    simplification_retries: int = 0
    simplification_base_fallbacks: int = 0
    coverage_expansions: int = 0
    max_outward_expansion_meters: float = 0.0


class DisjointSet:
    def __init__(self, size: int) -> None:
        self.parents = list(range(size))
        self.ranks = [0] * size

    def find(self, value: int) -> int:
        if self.parents[value] != value:
            self.parents[value] = self.find(self.parents[value])
        return self.parents[value]

    def union(self, left: int, right: int) -> bool:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return False

        if self.ranks[left_root] < self.ranks[right_root]:
            left_root, right_root = right_root, left_root

        self.parents[right_root] = left_root
        if self.ranks[left_root] == self.ranks[right_root]:
            self.ranks[left_root] += 1

        return True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate simplified GeoJSON datasets with Polygon-only output and "
            "feature-level bbox values."
        )
    )
    parser.add_argument(
        "dataset",
        nargs="?",
        default="all",
        choices=["all", *sorted(DEFAULT_INPUTS.keys())],
        help="Dataset to process. Default: all.",
    )
    parser.add_argument(
        "--coverage-policy",
        choices=list(DEFAULT_OUTPUT_SUFFIXES.keys()),
        default=DEFAULT_COVERAGE_POLICY,
        help=(
            "free keeps the current aggressive simplification flow. "
            "covers-original expands the simplified polygon until it covers the "
            "full source geometry. "
            f"Default: {DEFAULT_COVERAGE_POLICY}."
        ),
    )
    parser.add_argument(
        "-o",
        "--output-file",
        help=(
            "Output file name inside generated-datasets/. "
            "Accepted only when processing a single dataset."
        ),
    )
    parser.add_argument(
        "--tolerance-meters",
        type=float,
        default=DEFAULT_TOLERANCE_METERS,
        help=(
            "Douglas-Peucker tolerance in meters. "
            f"Default: {DEFAULT_TOLERANCE_METERS:g}."
        ),
    )
    parser.add_argument(
        "--minimum-part-area-sqm",
        type=float,
        default=DEFAULT_MIN_PART_AREA_SQM,
        help=(
            "Minimum polygon-part area in square meters used before bridging. "
            f"Default: {DEFAULT_MIN_PART_AREA_SQM:g}."
        ),
    )
    parser.add_argument(
        "--bridge-width-meters",
        type=float,
        default=DEFAULT_BRIDGE_WIDTH_METERS,
        help=(
            "Width of artificial bridge corridors in meters. "
            f"Default: {DEFAULT_BRIDGE_WIDTH_METERS:g}."
        ),
    )
    parser.add_argument(
        "--fallback-multipliers",
        default=DEFAULT_FALLBACK_MULTIPLIERS_RAW,
        help=(
            "Comma-separated tolerance multipliers applied to the configured "
            f"tolerance when simplification falls back. Default: "
            f"{DEFAULT_FALLBACK_MULTIPLIERS_RAW}."
        ),
    )
    parser.add_argument(
        "--format",
        choices=["compact", "formatted"],
        default="compact",
        help="Write compact or formatted JSON output. Default: compact.",
    )
    return parser


def parse_fallback_multipliers(raw_value: str) -> tuple[float, ...]:
    multipliers: list[float] = []
    for part in raw_value.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            multiplier = float(part)
        except ValueError as exc:
            raise ValueError(
                f"Invalid fallback multiplier `{part}` in `{raw_value}`"
            ) from exc
        if multiplier <= 0:
            raise ValueError("Fallback multipliers must be greater than 0")
        multipliers.append(multiplier)

    if not multipliers:
        raise ValueError("At least one fallback multiplier is required")

    return tuple(multipliers)


def validate_cli_args(args: argparse.Namespace) -> tuple[float, ...]:
    if args.tolerance_meters <= 0:
        raise ValueError("--tolerance-meters must be greater than 0")
    if args.minimum_part_area_sqm < 0:
        raise ValueError("--minimum-part-area-sqm must be greater than or equal to 0")
    if args.bridge_width_meters <= 0:
        raise ValueError("--bridge-width-meters must be greater than 0")
    if args.dataset == "all" and args.output_file:
        raise ValueError("--output-file can be used only when processing a single dataset")
    return parse_fallback_multipliers(args.fallback_multipliers)


def load_feature_collection(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if data.get("type") != "FeatureCollection":
        raise ValueError(f"{path} is not a GeoJSON FeatureCollection")

    features = data.get("features")
    if not isinstance(features, list):
        raise ValueError(f"{path} does not contain a valid `features` array")

    return data


def collect_polygon_parts(geometry: Any) -> list[Polygon]:
    if geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon):
        return list(geometry.geoms)
    if hasattr(geometry, "geoms"):
        parts: list[Polygon] = []
        for child in geometry.geoms:
            parts.extend(collect_polygon_parts(child))
        return parts
    return []


def to_metric(geometry: Any) -> Any:
    return transform(TO_METRIC.transform, geometry)


def to_source(geometry: Any) -> Any:
    return transform(TO_SOURCE.transform, geometry)


def normalize_polygonal_geometry(geometry: Any) -> Polygon | MultiPolygon:
    candidate = geometry if geometry.is_valid else make_valid(geometry)
    parts = collect_polygon_parts(candidate)
    if not parts:
        raise ValueError("Geometry normalization did not produce polygonal output")
    if len(parts) == 1:
        return parts[0]
    return MultiPolygon(parts)


def build_bridge(component_a: Polygon, component_b: Polygon, bridge_width: float) -> Polygon:
    point_a, point_b = nearest_points(component_a.boundary, component_b.boundary)
    line = LineString([point_a, point_b])
    # Square end caps extend past the segment endpoints so the corridor overlaps
    # both polygons instead of touching them at a single point.
    return line.buffer(
        bridge_width / 2.0,
        cap_style=3,
        join_style=2,
    )


def connect_components_with_bridges(
    components: list[Polygon],
    bridge_width: float,
) -> tuple[Polygon, int]:
    if len(components) == 1:
        return components[0], 0

    edges: list[tuple[float, int, int, Polygon]] = []
    for left_index, left_component in enumerate(components):
        for right_index in range(left_index + 1, len(components)):
            right_component = components[right_index]
            bridge = build_bridge(left_component, right_component, bridge_width)
            edges.append(
                (left_component.distance(right_component), left_index, right_index, bridge)
            )

    edges.sort(key=lambda item: item[0])
    disjoint_set = DisjointSet(len(components))
    bridges: list[Polygon] = []

    for _, left_index, right_index, bridge in edges:
        if disjoint_set.union(left_index, right_index):
            bridges.append(bridge)
        if len(bridges) == len(components) - 1:
            break

    merged = unary_union([*components, *bridges])
    merged_parts = collect_polygon_parts(merged)
    if len(merged_parts) != 1:
        raise ValueError(
            "Bridge-based multipart reduction did not produce a single polygon"
        )

    return merged_parts[0], len(bridges)


def build_base_polygon(
    geometry_metric: Polygon | MultiPolygon,
    min_part_area_sqm: float,
    bridge_width_meters: float,
) -> tuple[Polygon, int, int]:
    geometry_metric = normalize_polygonal_geometry(geometry_metric)
    if isinstance(geometry_metric, Polygon):
        return geometry_metric, 0, 0

    parts = list(geometry_metric.geoms)
    if not parts:
        raise ValueError("Encountered an empty MultiPolygon")

    kept_parts = [part for part in parts if part.area >= min_part_area_sqm]
    removed_parts = len(parts) - len(kept_parts)
    if not kept_parts:
        kept_parts = [max(parts, key=lambda part: part.area)]
        removed_parts = len(parts) - 1

    unioned = normalize_polygonal_geometry(unary_union(kept_parts))
    polygon_parts = collect_polygon_parts(unioned)
    if not polygon_parts:
        raise ValueError("Multipart reduction did not produce any polygonal geometry")

    if len(polygon_parts) == 1:
        return polygon_parts[0], removed_parts, 0

    connected_polygon, bridge_count = connect_components_with_bridges(
        polygon_parts,
        bridge_width_meters,
    )
    normalized_connected = normalize_polygonal_geometry(connected_polygon)
    if not isinstance(normalized_connected, Polygon):
        raise ValueError("Bridge-connected geometry did not normalize to a Polygon")
    return normalized_connected, removed_parts, bridge_count


def has_three_non_collinear_vertices(polygon: Polygon) -> bool:
    coordinates = list(polygon.exterior.coords)
    if len(coordinates) < 4:
        return False

    distinct = coordinates[:-1]
    if len({(round(x, 9), round(y, 9)) for x, y in distinct}) < 3:
        return False

    signed_area = 0.0
    for (x1, y1), (x2, y2) in zip(coordinates, coordinates[1:]):
        signed_area += (x1 * y2) - (x2 * y1)
    return abs(signed_area) / 2.0 > AREA_EPSILON_SQM


def is_valid_output_polygon(geometry: Any) -> bool:
    return (
        isinstance(geometry, Polygon)
        and not geometry.is_empty
        and geometry.is_valid
        and geometry.area > AREA_EPSILON_SQM
        and has_three_non_collinear_vertices(geometry)
    )


def is_valid_serialized_polygon(geometry: Any) -> bool:
    return (
        isinstance(geometry, Polygon)
        and not geometry.is_empty
        and geometry.is_valid
        and geometry.area > 0
        and has_three_non_collinear_vertices(geometry)
    )


def serialize_metric_polygon(geometry_metric: Polygon) -> Polygon | None:
    serialized = normalize_polygonal_geometry(to_source(geometry_metric))
    if not isinstance(serialized, Polygon):
        return None
    if not is_valid_serialized_polygon(serialized):
        return None
    return serialized


def roundtrip_source_polygon_to_metric(geometry_source: Polygon) -> Polygon | None:
    roundtrip_metric = normalize_polygonal_geometry(to_metric(geometry_source))
    if not isinstance(roundtrip_metric, Polygon):
        return None
    if not is_valid_output_polygon(roundtrip_metric):
        return None
    return roundtrip_metric


def candidate_covers_target(
    candidate: Polygon,
    coverage_target: Polygon | MultiPolygon,
) -> bool:
    return candidate.covers(coverage_target)


def enforce_outer_cover(
    candidate: Polygon,
    base_polygon: Polygon,
    coverage_target: Polygon | MultiPolygon,
) -> tuple[Polygon | None, float]:
    def expand_candidate(distance: float) -> Polygon:
        return candidate.buffer(
            distance,
            quad_segs=OUTER_COVER_BUFFER_QUAD_SEGS,
            join_style=OUTER_COVER_BUFFER_JOIN_STYLE,
        )

    if candidate_covers_target(candidate, coverage_target):
        return candidate, 0.0

    upper_bound = max(candidate.hausdorff_distance(base_polygon) + 1e-6, 1e-6)
    expanded_candidate = expand_candidate(upper_bound)
    if not (
        is_valid_output_polygon(expanded_candidate)
        and candidate_covers_target(expanded_candidate, coverage_target)
    ):
        bounds = base_polygon.bounds
        max_dimension = max(bounds[2] - bounds[0], bounds[3] - bounds[1], 1.0)
        while upper_bound <= max_dimension * 4:
            upper_bound *= 2.0
            expanded_candidate = expand_candidate(upper_bound)
            if (
                is_valid_output_polygon(expanded_candidate)
                and candidate_covers_target(expanded_candidate, coverage_target)
            ):
                break
        else:
            return None, 0.0

    lower_bound = 0.0
    best = expanded_candidate
    for _ in range(OUTER_COVER_BINARY_SEARCH_STEPS):
        midpoint = (lower_bound + upper_bound) / 2.0
        trial = expand_candidate(midpoint)
        if is_valid_output_polygon(trial) and candidate_covers_target(
            trial,
            coverage_target,
        ):
            upper_bound = midpoint
            best = trial
        else:
            lower_bound = midpoint

    if not is_valid_output_polygon(best):
        return None, 0.0
    return best, upper_bound


def serialize_covering_metric_polygon(
    geometry_metric: Polygon,
    coverage_target: Polygon | MultiPolygon,
) -> tuple[Polygon | None, float]:
    serialization_margin = 0.0

    for _ in range(OUTER_COVER_SERIALIZATION_PASSES):
        current_metric = geometry_metric
        if serialization_margin > 0:
            current_metric = geometry_metric.buffer(
                serialization_margin,
                quad_segs=OUTER_COVER_BUFFER_QUAD_SEGS,
                join_style=OUTER_COVER_BUFFER_JOIN_STYLE,
            )

        serialized = serialize_metric_polygon(current_metric)
        if serialized is None:
            serialization_margin = max(
                OUTER_COVER_SERIALIZATION_MARGIN_METERS,
                serialization_margin * 2.0,
            )
            continue

        roundtrip_metric = roundtrip_source_polygon_to_metric(serialized)
        if roundtrip_metric is None:
            serialization_margin = max(
                OUTER_COVER_SERIALIZATION_MARGIN_METERS,
                serialization_margin * 2.0,
            )
            continue
        if candidate_covers_target(roundtrip_metric, coverage_target):
            return serialized, serialization_margin

        serialization_margin = max(
            OUTER_COVER_SERIALIZATION_MARGIN_METERS,
            serialization_margin * 2.0,
        )

    return None, 0.0


def simplify_polygon_with_fallback(
    base_polygon: Polygon,
    coverage_target: Polygon | MultiPolygon,
    tolerance_meters: float,
    fallback_multipliers: Iterable[float],
    coverage_policy: str,
    stats: DatasetStats,
) -> Polygon:
    for attempt_index, multiplier in enumerate(fallback_multipliers):
        stats.simplification_attempts += 1
        if attempt_index > 0:
            stats.simplification_retries += 1

        simplified = base_polygon.simplify(
            tolerance_meters * multiplier,
            preserve_topology=False,
        )
        if not is_valid_output_polygon(simplified):
            continue

        final_metric = simplified
        expansion_distance = 0.0
        if coverage_policy == "covers-original":
            final_metric, expansion_distance = enforce_outer_cover(
                candidate=simplified,
                base_polygon=base_polygon,
                coverage_target=coverage_target,
            )
            if final_metric is None:
                continue
            simplified_source, roundtrip_expansion_distance = (
                serialize_covering_metric_polygon(
                    geometry_metric=final_metric,
                    coverage_target=coverage_target,
                )
            )
            if simplified_source is None:
                continue
            total_expansion_distance = expansion_distance + roundtrip_expansion_distance
            if total_expansion_distance > 0:
                stats.coverage_expansions += 1
                stats.max_outward_expansion_meters = max(
                    stats.max_outward_expansion_meters,
                    total_expansion_distance,
                )
            return simplified_source

        simplified_source = serialize_metric_polygon(final_metric)
        if simplified_source is not None:
            return simplified_source

    stats.simplification_base_fallbacks += 1
    if coverage_policy == "covers-original" and not candidate_covers_target(
        base_polygon,
        coverage_target,
    ):
        raise ValueError("Base polygon does not cover the full source geometry")
    if coverage_policy == "covers-original":
        fallback_source, roundtrip_expansion_distance = serialize_covering_metric_polygon(
            geometry_metric=base_polygon,
            coverage_target=coverage_target,
        )
        if fallback_source is None:
            raise ValueError("Base polygon did not produce a valid serialized Polygon")
        if roundtrip_expansion_distance > 0:
            stats.coverage_expansions += 1
            stats.max_outward_expansion_meters = max(
                stats.max_outward_expansion_meters,
                roundtrip_expansion_distance,
            )
        return fallback_source

    fallback_source = serialize_metric_polygon(base_polygon)
    if fallback_source is None:
        raise ValueError("Base polygon did not produce a valid serialized Polygon")
    return fallback_source


def build_bbox(original_geometry: Polygon | MultiPolygon) -> list[float]:
    min_lon, min_lat, max_lon, max_lat = original_geometry.bounds
    return [float(min_lon), float(min_lat), float(max_lon), float(max_lat)]


def transform_feature(
    feature: dict[str, Any],
    min_part_area_sqm: float,
    bridge_width_meters: float,
    tolerance_meters: float,
    fallback_multipliers: Iterable[float],
    coverage_policy: str,
    stats: DatasetStats,
) -> dict[str, Any]:
    properties = feature.get("properties")
    if not isinstance(properties, dict):
        raise ValueError("Feature properties must be an object")

    geometry_data = feature.get("geometry")
    if not isinstance(geometry_data, dict):
        raise ValueError("Feature geometry must be an object")

    original_geometry = shape(geometry_data)
    if not isinstance(original_geometry, (Polygon, MultiPolygon)):
        raise ValueError(
            "Feature geometry must be Polygon or MultiPolygon, "
            f"got `{geometry_data.get('type')}`"
        )
    normalized_original = normalize_polygonal_geometry(original_geometry)

    stats.features_processed += 1
    if isinstance(original_geometry, MultiPolygon):
        stats.multipart_features += 1

    bbox = build_bbox(original_geometry)
    coverage_target_metric = normalize_polygonal_geometry(to_metric(normalized_original))
    effective_min_part_area = (
        0.0 if coverage_policy == "covers-original" else min_part_area_sqm
    )
    base_polygon, removed_parts, bridge_count = build_base_polygon(
        coverage_target_metric,
        min_part_area_sqm=effective_min_part_area,
        bridge_width_meters=bridge_width_meters,
    )
    if not is_valid_output_polygon(base_polygon):
        raise ValueError("Base polygon is invalid or degenerate before simplification")
    if coverage_policy == "covers-original" and not candidate_covers_target(
        base_polygon,
        coverage_target_metric,
    ):
        expanded_base_polygon, _ = enforce_outer_cover(
            candidate=base_polygon,
            base_polygon=base_polygon,
            coverage_target=coverage_target_metric,
        )
        if expanded_base_polygon is None:
            raise ValueError("Base polygon does not cover the full normalized source geometry")
        base_polygon = expanded_base_polygon

    stats.parts_removed_by_area += removed_parts
    stats.bridges_added += bridge_count

    simplified_source = simplify_polygon_with_fallback(
        base_polygon,
        coverage_target=coverage_target_metric,
        tolerance_meters=tolerance_meters,
        fallback_multipliers=fallback_multipliers,
        coverage_policy=coverage_policy,
        stats=stats,
    )
    if not is_valid_serialized_polygon(simplified_source):
        raise ValueError("Failed to produce a valid output polygon")

    return {
        "type": "Feature",
        "bbox": bbox,
        "properties": properties,
        "geometry": mapping(simplified_source),
    }


def default_output_path(dataset: str, coverage_policy: str) -> Path:
    suffix = DEFAULT_OUTPUT_SUFFIXES[coverage_policy]
    return OUTPUT_DIR / f"limits_IT_{dataset}.{suffix}.geojson"


def resolve_output_path(
    dataset: str,
    coverage_policy: str,
    output_file: str | None,
) -> Path:
    if not output_file:
        return default_output_path(dataset, coverage_policy)

    file_name = Path(output_file).name
    if file_name in {"", ".", ".."}:
        raise ValueError("--output-file must be a valid file name")

    return OUTPUT_DIR / file_name


def resolve_dataset_targets(dataset: str) -> list[str]:
    if dataset == "all":
        return list(DEFAULT_INPUTS.keys())
    return [dataset]


def write_feature_collection(
    output_path: Path,
    feature_collection: dict[str, Any],
    json_format: str,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        if json_format == "formatted":
            json.dump(feature_collection, file, indent=2, ensure_ascii=False)
            file.write("\n")
            return

        json.dump(feature_collection, file, separators=(",", ":"), ensure_ascii=False)


def process_dataset(
    dataset: str,
    output_path: Path,
    coverage_policy: str,
    tolerance_meters: float,
    min_part_area_sqm: float,
    bridge_width_meters: float,
    fallback_multipliers: Iterable[float],
    json_format: str,
) -> DatasetStats:
    input_path = DEFAULT_INPUTS[dataset]

    data = load_feature_collection(input_path)
    transformed_features = []
    stats = DatasetStats()

    for feature in data["features"]:
        transformed_features.append(
            transform_feature(
                feature,
                min_part_area_sqm=min_part_area_sqm,
                bridge_width_meters=bridge_width_meters,
                tolerance_meters=tolerance_meters,
                fallback_multipliers=fallback_multipliers,
                coverage_policy=coverage_policy,
                stats=stats,
            )
        )

    write_feature_collection(
        output_path=output_path,
        feature_collection={
            "type": "FeatureCollection",
            "features": transformed_features,
        },
        json_format=json_format,
    )
    return stats


def print_summary(
    dataset: str,
    coverage_policy: str,
    output_path: Path,
    stats: DatasetStats,
) -> None:
    summary_parts = [
        f"dataset={dataset}",
        f"policy={coverage_policy}",
        f"features={stats.features_processed}",
        f"multipart={stats.multipart_features}",
        f"parts_removed={stats.parts_removed_by_area}",
        f"bridges_added={stats.bridges_added}",
        f"simplify_attempts={stats.simplification_attempts}",
        f"simplify_retries={stats.simplification_retries}",
        f"base_fallbacks={stats.simplification_base_fallbacks}",
    ]
    if coverage_policy == "covers-original":
        summary_parts.extend(
            [
                f"cover_expansions={stats.coverage_expansions}",
                (
                    "max_outward_expansion_meters="
                    f"{stats.max_outward_expansion_meters:.6f}"
                ),
            ]
        )

    print(
        ", ".join(summary_parts) + f", output={output_path}"
    )


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        fallback_multipliers = validate_cli_args(args)
    except ValueError as exc:
        parser.error(str(exc))

    for dataset in resolve_dataset_targets(args.dataset):
        output_path = resolve_output_path(
            dataset=dataset,
            coverage_policy=args.coverage_policy,
            output_file=args.output_file,
        )
        stats = process_dataset(
            dataset=dataset,
            output_path=output_path,
            coverage_policy=args.coverage_policy,
            tolerance_meters=args.tolerance_meters,
            min_part_area_sqm=args.minimum_part_area_sqm,
            bridge_width_meters=args.bridge_width_meters,
            fallback_multipliers=fallback_multipliers,
            json_format=args.format,
        )
        print_summary(
            dataset=dataset,
            coverage_policy=args.coverage_policy,
            output_path=output_path,
            stats=stats,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
