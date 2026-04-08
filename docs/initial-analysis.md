# Project Goal

Create a simple postgres setup for italy geo informations

## Analysis Date

08/04/2026

# Data model

## Region

- reg_name
- reg_istat_code_num
- reg_istat_code
- reg_geometry
- reg_central_coordinates
- reg_approx_radius

## Province

- prov_name
- prov_istat_code_num 
- prov_acr
- reg_name
- reg_istat_code
- reg_istat_code_num
- prov_istat_code
- prov_geometry
- prov_central_coordinates
- reg_approx_radius

## Municipalities

- name 
- minint_elettorale
- minint_finloc
- op_id
- prov_name 
- prov_istat_code
- prov_istat_code_num
- prov_acr
- reg_name
- reg_istat_code
- reg_istat_code_num
- opdm_id"
- com_catasto_code
- com_istat_code
- com_istat_code_num
- mun_geometry
- mun_central_coordinates
- mun_approx_radius

## Geometry Strategy Decisions

The source datasets in `original-datasets/` remain the authoritative geometry source and must stay untouched.

The project will generate derived geometry datasets separately instead of modifying the originals.

Current source geometry facts:

- `limits_IT_regions.geojson`: 20 features, 14 `MultiPolygon`
- `limits_IT_provinces.geojson`: 107 features, 46 `MultiPolygon`
- `limits_IT_municipalities.geojson`: 7899 features, 7899 `MultiPolygon`
- total `MultiPolygon` features across all source datasets: 7959

Additional observed geometry complexity:

- regions: vertex count about 1176 min, 3683 p50, 5680 p90, 7703 max
- provinces: vertex count about 368 min, 1266 p50, 2136 p90, 5086 max
- municipalities: vertex count about 6 min, 89 p50, 195 p90, 1477 max

### Core Decisions

- keep the original datasets untouched
- create derived simplified datasets in a separate folder
- for v1, generate only:
  - simplified geometry
  - bbox
- do not include center, min radius, or max radius in v1
- do not collapse geometries to bbox
- use a deliberately aggressive simplification strategy for the first iteration
- force `MultiPolygon -> Polygon` in v1
- ignore polygon parts smaller than a configurable minimum area threshold during multipart reduction

`MultiPolygon -> Polygon` is not treated as neutral simplification because it changes geometry semantics and can drop islands, exclaves, or detached administrative parts. It is still intentionally chosen for v1 because the current priority is aggressive size reduction and quick evaluation of the resulting output quality.

### Why BBox Is Included

`bbox` means bounding box: the smallest axis-aligned rectangle that fully contains a geometry.

Representation:

```json
[minLon, minLat, maxLon, maxLat]
```

The bbox is useful because it is:

- cheap to compute
- compact to store
- useful for rough filtering and viewport calculations

The bbox is not a replacement for the boundary geometry because it loses all detailed shape information and includes empty space outside the real geometry.

### Simplification Direction

The working decision for v1 is to generate an aggressively simplified geometry and then inspect the output before further tuning.

The preferred simplification direction is:

- preserve geometry validity
- use `Douglas-Peucker` as the primary simplification algorithm
- force multipart geometries into single polygons in v1
- ignore very small polygon parts through a configurable area threshold
- connect remaining disjoint polygon parts with artificial bridges when needed
- simplify into a coarser `Polygon`
- avoid forcing shapes into squares, triangles, or other primitive shapes as the default strategy

### Simplification Algorithm Notes

The main algorithm families considered were:

- Douglas-Peucker
- topology-preserving simplification
- Visvalingam-Whyatt
- vertex clustering / grid snapping
- convex hull / concave hull
- bounding shapes such as bbox

Recommended v1 direction for this project:

- use `Douglas-Peucker` as the primary simplification algorithm
- use an intentionally aggressive simplification configuration first
- convert `MultiPolygon` geometries into `Polygon` geometries as part of the derived dataset generation
- discard polygon parts smaller than a configurable area threshold during multipart reduction
- connect remaining disjoint polygon parts with bridges so a single polygon can be produced
- keep more destructive approximations such as hulls or boxes for separate future experiments, not for the main simplified boundary dataset

### Forced MultiPolygon To Polygon Policy

For v1, `MultiPolygon` features are intentionally reduced to `Polygon`.

This requires an explicit reduction rule. The selected implementation policy should be:

- split the geometry into polygon parts
- compute polygon-part areas in a metric CRS
- discard polygon parts smaller than a configurable minimum area threshold
- if all parts are discarded by the threshold, keep the largest original polygon part as a fallback
- union touching or overlapping remaining parts
- if disjoint components remain, connect them with artificial bridge corridors between the nearest component boundaries
- if more than two disjoint components remain, connect components using a minimum-spanning-tree strategy so only the minimum bridge set is added
- union the remaining parts and bridges into a single polygon
- run `Douglas-Peucker` simplification after multipart reduction has produced a single polygon

Consequences:

- very small detached parts can be intentionally dropped by the area threshold
- larger detached parts are preserved approximately through bridges
- bridges introduce artificial connecting area that does not exist in the original boundary
- the generated dataset is an approximation dataset, not a fully faithful administrative boundary dataset
- this is acceptable for the first iteration because the goal is to inspect output quality and then decide whether to relax or revise the policy

### Tolerance Vs Max Vertices

Two simplification control strategies were considered.

Tolerance-based simplification:

- controls geometric error in spatial terms
- is easier to justify in GIS terms
- does not guarantee a final vertex count

Max-vertices-based simplification:

- controls payload size more directly
- does not guarantee geometric fidelity
- can distort irregular shapes more aggressively

Working conclusion:

- prefer tolerance as the primary control
- optionally use a vertex cap later as a safety rail if needed
- define tolerance in metric units for implementation purposes

## V1 Simplified Dataset

### Goal

Create a generated dataset per source file that contains:

- original feature properties unchanged
- simplified geometry as the feature geometry
- bbox for each feature

No other derived fields are included in v1.

### Output Folder

Create a new folder:

- `simplified-datasets/`

This folder is distinct from:

- `original-datasets/` for raw authoritative sources
- `generated-datasets/` for subsets and ad hoc generated files

### Output Files

One output file should be produced for each original dataset, with names such as:

- `simplified-datasets/limits_IT_regions.simplified.geojson`
- `simplified-datasets/limits_IT_provinces.simplified.geojson`
- `simplified-datasets/limits_IT_municipalities.simplified.geojson`

### GeoJSON Structure

The output should remain valid GeoJSON and use a standard `FeatureCollection`.

Per-feature structure:

```json
{
  "type": "Feature",
  "bbox": [minLon, minLat, maxLon, maxLat],
  "properties": {
    "...": "original properties unchanged"
  },
  "geometry": {
    "type": "Polygon",
    "coordinates": []
  }
}
```

Collection structure:

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "bbox": [minLon, minLat, maxLon, maxLat],
      "properties": {},
      "geometry": {}
    }
  ]
}
```

### V1 Output Contract

- `properties` must be copied unchanged from the source feature
- `geometry` must be the simplified geometry
- `bbox` must be present for every feature
- feature order should remain the same as the source dataset
- geometry should be output as `Polygon` in v1
- when the source feature is `MultiPolygon`, the output `Polygon` should be produced by area-threshold filtering, union of remaining parts, bridge-based connection of disjoint components, and final simplification
- simplification should use a tolerance-based control expressed in metric units
- the generator must not emit invalid or degenerate polygons
- multipart reduction must first produce a valid base polygon before simplification
- if simplification produces an invalid or degenerate polygon, the implementation should retry with lower tolerance using a fixed fallback ladder such as `T`, `T/2`, `T/4`, `T/8`
- if all simplification attempts fail, the implementation must fall back to the unsimplified base polygon
- the generator must not drop features only because simplification failed

### BBox Policy

For v1, the bbox should be computed from the original geometry, not from the simplified geometry.

Reason:

- the original geometry remains the authoritative source
- simplification should not accidentally reduce the spatial envelope too much

### Non-Goals For V1

The following are intentionally excluded from v1:

- center or centroid fields
- point-on-surface or representative point fields
- min radius
- max radius
- replacing geometries with bbox-only representations

Note: forcing `MultiPolygon -> Polygon` is not a non-goal anymore. It is part of the v1 simplification policy.

### Development Guidance

Implementation should be approached as a derived dataset generator:

- read from `original-datasets/`
- generate simplified outputs into `simplified-datasets/`
- preserve source properties
- compute simplified geometry and bbox only

The first implementation can use an aggressive simplification mode, then results should be inspected visually and statistically before tuning the simplification parameters.

The implementation should also record enough metrics during testing or inspection to understand the impact of the aggressive policy, especially:

- original geometry type
- simplified geometry type
- original vertex count
- simplified vertex count
- number of polygon parts removed by the minimum-area threshold
- number of disjoint components connected with bridges
- number of bridges added
- configured simplification tolerance
- final effective simplification tolerance used
- whether fallback to the unsimplified base polygon was required



