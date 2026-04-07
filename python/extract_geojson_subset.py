#!/usr/bin/env python3
# Usage examples:
#   python3 python/extract_geojson_subset.py municipalities --limit 25
#   python3 python/extract_geojson_subset.py municipalities --limit 25 --output-file sample.geojson
#   python3 python/extract_geojson_subset.py municipalities --region Lazio --limit 10 --sample-mode first
#   python3 python/extract_geojson_subset.py provinces --province MI --limit 5
"""Extract smaller GeoJSON subsets from the original Italian datasets."""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any


DEFAULT_INPUTS = {
    "regions": Path("original-datasets/limits_IT_regions.geojson"),
    "provinces": Path("original-datasets/limits_IT_provinces.geojson"),
    "municipalities": Path("original-datasets/limits_IT_municipalities (1).geojson"),
}
OUTPUT_DIR = Path("generated-datasets")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Extract a smaller GeoJSON FeatureCollection from one of the original datasets."
        )
    )
    parser.add_argument(
        "dataset",
        choices=sorted(DEFAULT_INPUTS.keys()),
        help="Dataset to extract from.",
    )
    parser.add_argument(
        "-o",
        "--output-file",
        help=(
            "Output file name inside generated-datasets/. "
            "Defaults to <dataset>-subset.geojson."
        ),
    )
    parser.add_argument(
        "-n",
        "--limit",
        type=int,
        default=20,
        help="Maximum number of features to keep after filtering. Default: 20.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed used when shuffling filtered features. Default: 42.",
    )
    parser.add_argument(
        "--region",
        action="append",
        default=[],
        help="Keep only features whose region name matches this value. Repeatable.",
    )
    parser.add_argument(
        "--province",
        action="append",
        default=[],
        help="Keep only features whose province name or acronym matches this value. Repeatable.",
    )
    parser.add_argument(
        "--municipality",
        action="append",
        default=[],
        help="Keep only features whose municipality name matches this value. Repeatable.",
    )
    parser.add_argument(
        "--contains",
        help="Keep only features with at least one property containing this text.",
    )
    parser.add_argument(
        "--sort-by",
        choices=[
            "original",
            "name",
            "prov_name",
            "reg_name",
            "prov_acr",
            "com_istat_code",
            "prov_istat_code",
            "reg_istat_code",
        ],
        default="original",
        help="Sort filtered features before applying the limit. Default: original.",
    )
    parser.add_argument(
        "--sample-mode",
        choices=["first", "random"],
        default="random",
        help="Pick the first N or a deterministic random sample after filtering. Default: random.",
    )
    return parser


def load_feature_collection(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if data.get("type") != "FeatureCollection":
        raise ValueError(f"{path} is not a GeoJSON FeatureCollection")

    if not isinstance(data.get("features"), list):
        raise ValueError(f"{path} does not contain a valid 'features' array")

    return data


def normalize(values: list[str]) -> set[str]:
    return {value.casefold().strip() for value in values if value.strip()}


def property_matches(properties: dict[str, Any], key: str, accepted: set[str]) -> bool:
    if not accepted:
        return True

    value = properties.get(key)
    if value is None:
        return False

    return str(value).casefold().strip() in accepted


def province_matches(properties: dict[str, Any], accepted: set[str]) -> bool:
    if not accepted:
        return True

    for key in ("prov_name", "prov_acr"):
        value = properties.get(key)
        if value is not None and str(value).casefold().strip() in accepted:
            return True
    return False


def contains_text(properties: dict[str, Any], needle: str | None) -> bool:
    if not needle:
        return True

    lowered = needle.casefold().strip()
    for value in properties.values():
        if lowered in str(value).casefold():
            return True
    return False


def filter_features(
    features: list[dict[str, Any]],
    regions: set[str],
    provinces: set[str],
    municipalities: set[str],
    contains: str | None,
) -> list[dict[str, Any]]:
    filtered = []
    for feature in features:
        properties = feature.get("properties", {})
        if not isinstance(properties, dict):
            continue

        if not property_matches(properties, "reg_name", regions):
            continue
        if not province_matches(properties, provinces):
            continue
        if not property_matches(properties, "name", municipalities):
            continue
        if not contains_text(properties, contains):
            continue

        filtered.append(feature)

    return filtered


def sort_features(features: list[dict[str, Any]], sort_by: str) -> list[dict[str, Any]]:
    if sort_by == "original":
        return list(features)

    return sorted(
        features,
        key=lambda feature: str(feature.get("properties", {}).get(sort_by, "")),
    )


def select_features(
    features: list[dict[str, Any]],
    limit: int,
    sample_mode: str,
    seed: int,
) -> list[dict[str, Any]]:
    if limit < 1:
        raise ValueError("--limit must be greater than 0")

    if len(features) <= limit:
        return features

    if sample_mode == "first":
        return features[:limit]

    rng = random.Random(seed)
    indices = sorted(rng.sample(range(len(features)), limit))
    return [features[index] for index in indices]


def default_output_path(dataset: str) -> Path:
    return OUTPUT_DIR / f"{dataset}-subset.geojson"


def resolve_output_path(dataset: str, output_file: str | None) -> Path:
    if not output_file:
        return default_output_path(dataset)

    file_name = Path(output_file).name
    if file_name in {"", ".", ".."}:
        raise ValueError("--output-file must be a valid file name")

    return OUTPUT_DIR / file_name


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    source_path = DEFAULT_INPUTS[args.dataset]
    output_path = resolve_output_path(args.dataset, args.output_file)

    data = load_feature_collection(source_path)
    filtered = filter_features(
        data["features"],
        regions=normalize(args.region),
        provinces=normalize(args.province),
        municipalities=normalize(args.municipality),
        contains=args.contains,
    )
    ordered = sort_features(filtered, args.sort_by)
    selected = select_features(
        ordered,
        limit=args.limit,
        sample_mode=args.sample_mode,
        seed=args.seed,
    )

    subset = {
        "type": "FeatureCollection",
        "features": selected,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        json.dump(subset, file, ensure_ascii=False, separators=(",", ":"))

    print(f"Source: {source_path}")
    print(f"Matched features: {len(filtered)}")
    print(f"Written features: {len(selected)}")
    print(f"Output: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
