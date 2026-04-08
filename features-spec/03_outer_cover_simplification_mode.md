# Outer Cover Simplification Mode

## Objective

Extend `python/generate_simplified_datasets.py` with a new simplification mode that always approximates by excess.

In this mode, every generated output polygon must fully cover the original source geometry for the same feature.

The change must be implemented inside the existing generator script, not as a separate script.

## Scope

This feature changes the existing simplification pipeline by adding a conservative coverage mode.

The existing output contract remains the same:

- GeoJSON `FeatureCollection`
- feature-level `bbox`
- unchanged source `properties`
- output `geometry.type = Polygon`

This feature does not add new feature fields.

## Affected Files

The implementation must update:

- `python/generate_simplified_datasets.py`
- `README.md`

The generated output remains inside:

- `generated-datasets/`

Any manually curated files that should stay tracked in the repository may later be copied by hand into:

- `simplified-subset/`

That manual curation flow is outside the generator scope.

## New Coverage Requirement

When the new outer-cover mode is enabled, the final output polygon for each feature must satisfy this rule:

- the output polygon must cover the full original source geometry

Coverage must be checked in a metric projected CRS suitable for Italy.

Coverage is defined against the normalized original polygonal geometry for the feature, not against `bbox` and not against only the largest polygon part.

## Coverage Target Definition

For each feature, the implementation must build a `coverage target` geometry:

1. read the original source geometry
2. normalize invalid source geometry into valid polygonal geometry
3. keep all polygon parts from the normalized source geometry
4. use the full normalized polygonal geometry as the target for coverage checks

The coverage target may be `Polygon` or `MultiPolygon`.

The output geometry must cover the complete coverage target.

## CLI Changes

The existing generator CLI must be extended with:

- `--coverage-policy`
- `-o, --output-file`

Supported values:

- `free`
- `covers-original`

Behavior:

- `free`: keep the current v1 behavior
- `covers-original`: enable the new outer-cover mode

Default:

- `free`

The implementation may add optional internal tuning parameters for the cover-expansion step if needed, but `--coverage-policy` is the required user-facing control.

### Output File Parameter

The generator must follow the same output-file pattern used by `python/extract_geojson_subset.py`.

Required behavior:

- generated files must always be written inside `generated-datasets/`
- `--output-file` must accept only a file name, not an arbitrary path
- the implementation must sanitize the provided value the same way `python/extract_geojson_subset.py` does
- if the provided value is empty, `.`, or `..`, the generator must fail with a clear error

Recommended CLI behavior:

- if processing a single dataset, `--output-file` may be provided to choose the generated file name
- if `--output-file` is omitted, the implementation may use a mode-aware default file name
- if processing `all`, the implementation may reject `--output-file` and require default per-dataset output names

## Output Writing Rules

The generator must not write directly into `simplified-datasets/` or `simplified-subset/`.

All generated outputs must be created inside `generated-datasets/`.

When the caller provides `--output-file`, that file name must be used inside `generated-datasets/`.

If the implementation needs default names when `--output-file` is omitted, those names must remain mode-aware so `free` and `covers-original` outputs cannot overwrite each other accidentally.

## Geometry Processing Rules In `covers-original` Mode

### Source Geometry Handling

The source feature geometry may be:

- `Polygon`
- `MultiPolygon`

Invalid source geometries must be normalized into valid polygonal geometry before further processing.

### Part Retention

In `covers-original` mode, no original polygon parts may be discarded by area threshold.

Required behavior:

- all polygon parts from the normalized original geometry must be retained
- the effective minimum polygon-part area must be treated as `0`
- the implementation must not drop islands, exclaves, or detached components

### MultiPolygon To Polygon

If the normalized source geometry has multiple polygon components, the implementation must still emit a single `Polygon`.

Required reduction flow:

1. union touching or overlapping polygon parts
2. if disjoint components remain, connect them with artificial bridge corridors
3. if more than two disjoint components remain, connect components using a minimum-spanning-tree strategy
4. union the retained parts and the bridges into a single polygon
5. use that polygon as the feature base polygon for simplification

The base polygon must cover the full coverage target.

### Bridge Construction

The bridge construction rules from v1 remain in effect:

- each bridge must be a corridor with positive width
- the corridor must be centered on the shortest segment between two disjoint component boundaries
- bridge width remains configurable in meters
- only the minimum-spanning-tree bridge set may be added for multipart geometries with more than two disjoint components

## Simplification Rules In `covers-original` Mode

After the base polygon is built, the implementation must simplify it using the existing Douglas-Peucker flow and fallback ladder.

However, valid simplification is not sufficient by itself.

Each simplification candidate must pass both:

- geometry validity checks
- coverage check against the original coverage target

## Outer Cover Enforcement

If a simplified candidate polygon is valid but does not cover the original coverage target, the implementation must enlarge it outward until coverage is satisfied.

Required behavior:

1. simplify the base polygon with the current fallback tolerance
2. validate the simplified candidate
3. if the candidate already covers the coverage target, accept it
4. otherwise expand the candidate outward with a positive buffer in the projected CRS
5. search for the smallest outward expansion that makes the candidate cover the coverage target
6. validate the expanded candidate
7. if the expanded candidate is valid and covers the target, accept it

The cover-enforcement step must preserve `Polygon` output.

## Simplification Fallback Rules In `covers-original` Mode

The existing fallback ladder remains required.

For each fallback tolerance:

1. build a simplification candidate
2. if invalid, continue to the next fallback tolerance
3. if valid but not covering the original geometry, attempt outward expansion
4. if outward expansion fails, continue to the next fallback tolerance

If all fallback tolerances fail to produce a valid covering polygon, the implementation must fall back to the unsimplified base polygon.

Because the base polygon is built from all retained original parts plus bridges, it must still cover the original geometry and remain a valid final fallback.

## Validation Requirements

In `covers-original` mode, every output feature must satisfy all of these:

- `geometry.type` is `Polygon`
- geometry is valid
- geometry has positive area
- geometry has at least three distinct non-collinear vertices
- geometry covers the full original normalized source geometry

If any feature cannot satisfy these requirements, the generator must fail with a clear error instead of silently emitting a non-covering result.

## BBox Rules

The bbox rules do not change.

Each output feature must still include:

- feature-level `bbox`

The bbox must still be computed from the original source geometry before any reduction or simplification.

## Statistics And Reporting

The generator summary output must be extended to report, at minimum:

- number of features processed in `covers-original` mode
- number of features that required outward expansion after simplification
- maximum outward expansion distance used
- number of features that fell back to the unsimplified base polygon

## README Updates

`README.md` must be updated to describe:

- the new `--coverage-policy` parameter
- the new `--output-file` parameter
- the meaning of `covers-original`
- that generated files are written to `generated-datasets/`
- that repo-tracked files in `simplified-subset/` are selected manually outside the generator
- at least one usage example for the new mode

## Backward Compatibility

The existing `free` mode behavior must remain available and must stay the default mode.

Existing free-mode CLI invocations must continue to work.

The only intended output-management change is:

- generated files are produced in `generated-datasets/`
- manually tracked copies in `simplified-subset/` are not written automatically by the generator

## Non-Goals

This feature must not:

- create a separate generator script
- change the feature property schema
- replace polygons with bbox-only output
- allow dropped polygon parts in `covers-original` mode
- emit `MultiPolygon` in the simplified output
- write directly into `simplified-subset/`

## Acceptance Criteria

This feature is complete when:

1. the existing generator supports `--coverage-policy free|covers-original`
2. `free` mode continues to behave as before
3. the generator writes outputs into `generated-datasets/`
4. every `covers-original` output feature is a valid `Polygon`
5. every `covers-original` output feature covers the full original source geometry for that feature
6. no polygon parts are discarded in `covers-original` mode
7. multipart features in `covers-original` mode are reduced to one polygon using bridges when needed
8. bbox remains computed from the original geometry
9. the generator supports `--output-file` for caller-chosen file names following the `python/extract_geojson_subset.py` pattern
10. `README.md` documents the new mode, output location, and parameters
