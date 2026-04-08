# Geometry Simplification Brainstorm

Date: 2026-04-08

## Goal

Brainstorm how to simplify the geometries in `original-datasets/` without implementing anything yet.

Target outcome per feature:

- keep the complete/original geometry
- compute a simplified geometry
- always compute a bbox

This means the intended model is:

- `complete_geometry`
- `simplified_geometry`
- `bbox`

The bbox is additional metadata, not a replacement for the geometry.

## Current Dataset Facts

From the current files in `original-datasets/`:

- `limits_IT_regions.geojson`: 20 features, 14 `MultiPolygon`
- `limits_IT_provinces.geojson`: 107 features, 46 `MultiPolygon`
- `limits_IT_municipalities.geojson`: 7899 features, 7899 `MultiPolygon`

Total:

- 7959 `MultiPolygon` features across all three files

Additional geometry complexity observations:

- regions: vertex count roughly 1176 min, 3683 p50, 5680 p90, 7703 max
- provinces: vertex count roughly 368 min, 1266 p50, 2136 p90, 5086 max
- municipalities: vertex count roughly 6 min, 89 p50, 195 p90, 1477 max

## BBox

`bbox` means bounding box: the smallest axis-aligned rectangle that contains the geometry.

Typical representation:

```json
[minLon, minLat, maxLon, maxLat]
```

Usefulness:

- cheap to compute
- compact to store
- good for rough filtering and viewport logic

Limits:

- loses all boundary detail
- contains empty area outside the real shape

Conclusion:

- do not collapse geometries to bbox
- always compute bbox as an extra representation

## MultiPolygon To Polygon

Important distinction:

- `MultiPolygon -> Polygon` is not just simplification
- it changes the geometry model and can change meaning

Possible policies if ever needed:

- keep only the largest polygon by area
- dissolve only if parts actually touch
- replace with a derived polygon such as convex hull

Risks:

- islands and exclaves can disappear
- administrative boundaries can become semantically wrong

Working conclusion:

- do not collapse `MultiPolygon` to `Polygon` by default
- if simplification is done, prefer preserving multipart structure

## Simplification Families

### 1. Douglas-Peucker

Pros:

- fast
- common
- strong reduction in vertex count

Cons:

- can create sharp unnatural edges
- if not topology-aware, shared borders may drift

### 2. Topology-Preserving Simplification

Pros:

- safest default for administrative boundaries
- helps keep polygons valid
- reduces risk of broken or self-intersecting shapes

Cons:

- usually less aggressive than plain Douglas-Peucker
- a bit more compute

### 3. Visvalingam-Whyatt

Pros:

- often preserves the visual feel of a shape better

Cons:

- tuning is less intuitive
- validity/topology guarantees depend on implementation

### 4. Vertex Clustering / Grid Snapping

Pros:

- simple
- fast
- useful as a rough cleanup step

Cons:

- crude
- can visibly deform borders

### 5. Convex Hull / Concave Hull

Pros:

- useful for coarse approximation
- good for rough containment or search prefiltering

Cons:

- not faithful boundary simplification
- strong information loss

### 6. Bounding Shapes

Examples:

- bbox
- oriented bounding box

Pros:

- very compact
- good for indexing or rough filtering

Cons:

- not a boundary representation

## Recommended Direction

Best default discussed for this repository:

- keep original geometry untouched
- always compute bbox from the original geometry
- compute simplified geometry separately
- prefer a topology-preserving simplification approach
- avoid forcing polygons into squares or triangles as the default strategy
- avoid collapsing multipart geometries unless there is a very explicit product reason

## Tolerance Vs Max Vertices

These are different control strategies.

### Tolerance-Based

Meaning:

- remove detail smaller than a chosen spatial distance/error threshold

Pros:

- spatially meaningful
- easier to justify in GIS terms
- better when fidelity matters

Cons:

- final vertex count is not predictable
- one tolerance may not fit every dataset equally well

### Max-Vertices-Based

Meaning:

- force each geometry to end up at or below a vertex limit

Pros:

- predictable payload size
- good when transfer/storage/rendering budgets matter

Cons:

- geometric error is unpredictable
- can over-distort irregular shapes
- often implemented indirectly by adjusting tolerance until the cap is met

### Working Conclusion

Preferred control strategy:

1. simplify using a tolerance
2. measure the resulting vertex count
3. if still too heavy, apply a secondary cap/fallback

This hybrid approach gives:

- geographic meaning first
- payload protection second

## Candidate Output Strategy

Possible future per-feature outputs:

- `complete_geometry`
- `simplified_geometry`
- `bbox`
- optionally `center`
- optionally `approx_radius`

## Non-Implementation Conclusion

Before writing a Python script, the main design choice should be:

- preserve original geometry as authoritative
- simplify into a second geometry field
- compute bbox for every feature
- treat multipart collapse as a separate and more dangerous transformation, not as the default simplification step
