# Simplified Datasets V1

## Objective

Implement a Python generator that reads the GeoJSON source files from `original-datasets/` and produces simplified GeoJSON files in `simplified-datasets/`.

V1 output must include only:

- simplified geometry
- bbox

## Input Datasets

The generator must process these files:

- `original-datasets/limits_IT_regions.geojson`
- `original-datasets/limits_IT_provinces.geojson`
- `original-datasets/limits_IT_municipalities.geojson`

## Output Datasets

The generator must create:

- `simplified-datasets/limits_IT_regions.simplified.geojson`
- `simplified-datasets/limits_IT_provinces.simplified.geojson`
- `simplified-datasets/limits_IT_municipalities.simplified.geojson`

The generator must create the `simplified-datasets/` folder if it does not exist.

## Output Format

Each output file must be a valid GeoJSON `FeatureCollection`.

Top-level structure:

```json
{
  "type": "FeatureCollection",
  "features": []
}
```

Each output feature must have this structure:

```json
{
  "type": "Feature",
  "bbox": [minLon, minLat, maxLon, maxLat],
  "properties": {
    "...": "copied unchanged from source"
  },
  "geometry": {
    "type": "Polygon",
    "coordinates": []
  }
}
```

## Feature Transformation Rules

For each source feature:

1. copy `properties` unchanged
2. compute `bbox` from the original source geometry
3. reduce the source geometry to a single polygon
4. simplify the polygon geometry
5. write the transformed feature to the output file

## Coordinate And Measurement Rules

The source and output GeoJSON coordinates must remain in the source longitude/latitude coordinate system.

Operations that depend on distance or area must be performed in a metric projected CRS suitable for Italy, then transformed back to the source coordinate system for output serialization.

This applies to:

- polygon-part area filtering
- bridge construction
- Douglas-Peucker simplification tolerance
- geometry validation checks that depend on area

## Geometry Rules

### Source Geometry Handling

The source feature geometry may be:

- `Polygon`
- `MultiPolygon`

### MultiPolygon To Polygon

If the source geometry is `MultiPolygon`, the implementation must:

1. split the geometry into polygon parts
2. compute the area of each polygon part in a metric CRS
3. discard polygon parts whose area is smaller than the configured minimum-part-area parameter
4. if all polygon parts are discarded by the threshold, keep the largest original polygon part as a fallback
5. union touching or overlapping remaining polygon parts
6. if disjoint components remain, connect them using artificial bridge corridors
7. if more than two disjoint components remain, connect them using a minimum-spanning-tree strategy over component-to-component nearest-boundary distance
8. union the remaining polygon parts and bridges into a single polygon
9. continue processing using only the resulting polygon

### Bridge Construction

Each bridge must be built as a corridor with positive width centered on the shortest segment connecting the boundaries of two disjoint components.

The bridge width must be configurable through a parameter expressed in meters.

For multipart geometries with more than two disjoint components, the implementation must add only the bridges required by the minimum-spanning-tree strategy, not pairwise bridges between every component.

### Polygon Simplification

After the input geometry has been reduced to a single polygon, the resulting polygon becomes the feature base polygon.

The implementation must simplify the base polygon using the Douglas-Peucker algorithm.

V1 must use an aggressive simplification configuration.

The exact simplification tolerance must be exposed in the implementation as a parameter expressed in meters so it can be adjusted later without changing the output contract.

### Simplification Validation And Fallback

After simplification, the implementation must validate that the resulting geometry is a valid non-degenerate polygon.

At minimum, the simplified geometry must:

- remain a `Polygon`
- have positive area
- have at least three distinct non-collinear vertices
- not self-intersect

If simplification produces an invalid or degenerate polygon, the implementation must:

1. retry simplification with a lower tolerance
2. use a fixed fallback ladder based on the configured tolerance, such as `T`, `T/2`, `T/4`, `T/8`
3. repeat only for the bounded set of fallback tolerances
4. if all attempts fail, fall back to the unsimplified base polygon obtained after multipart reduction and bridge processing

The generator must not emit invalid or degenerate polygons.

The generator must not drop a feature only because simplification failed.

### Output Geometry Type

The output `geometry.type` must be:

- `Polygon`

V1 must not emit `MultiPolygon` in the simplified output files.

## BBox Rules

Each output feature must include a feature-level `bbox`.

The bbox must be computed from the original source geometry, before any `MultiPolygon -> Polygon` reduction and before simplification.

BBox format:

```json
[minLon, minLat, maxLon, maxLat]
```

## Ordering Rules

The output feature order must match the order of the source file.

## Properties Rules

The output feature `properties` object must be copied from the source feature without renaming, removing, or adding fields.

## Validation Requirements

The implementation must validate that:

- each input file is a GeoJSON `FeatureCollection`
- the `features` field is an array
- each processed feature has a valid geometry object
- each processed feature geometry is `Polygon` or `MultiPolygon`

If an input file is invalid, the generator must fail with a clear error.

## File Writing Requirements

The generator must write UTF-8 encoded JSON.

The generator should support at least:

- compact JSON output
- optionally formatted JSON output for inspection

## CLI Requirements

The implementation should provide a Python CLI script.

The CLI should support:

- processing all supported source datasets
- optionally processing a single dataset
- configuring Douglas-Peucker tolerance in meters
- configuring minimum polygon-part area in square meters
- configuring bridge width in meters
- optionally configuring the fallback tolerance ladder
- choosing compact or formatted JSON output

## Non-Goals

V1 must not include:

- original geometry in output files
- center or centroid fields
- point-on-surface fields
- min radius
- max radius
- additional derived metadata in feature properties

## Acceptance Criteria

V1 is complete when:

1. each source dataset can be processed successfully
2. each output file is valid GeoJSON
3. each output feature contains unchanged source `properties`
4. each output feature contains a feature-level `bbox`
5. each output feature contains a simplified `Polygon` geometry
6. source feature order is preserved
7. multipart features are reduced to a single polygon using area filtering plus bridge-based connection when needed
8. no invalid or degenerate polygons are emitted
9. output files are written to `simplified-datasets/`
