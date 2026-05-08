# Examples

This folder contains generated example outputs for the database import and map visualization workflow.

## Generation parameters

All files in this folder were generated from the original datasets with:

```text
coverage-policy: covers-original
tolerance-meters: 500
```

Source boundary datasets:

- `original-datasets/limits_IT_regions.geojson`
- `original-datasets/limits_IT_provinces.geojson`
- `original-datasets/limits_IT_municipalities.geojson`

Administrative centre data, when available, was joined from:

- `original-datasets/osm_IT_admin_centers.geojson`

## SQL insert file

Generated file:

- `italian_administrative_area_covers_original_tolerance_500_inserts.sql`

Command used:

```bash
.venv/bin/python python/generate_postgres_inserts.py all \
  --coverage-policy covers-original \
  --tolerance-meters 500 \
  --output-file examples/italian_administrative_area_covers_original_tolerance_500_inserts.sql
```

The SQL file contains one `INSERT` statement per administrative area:

- 20 regions
- 107 provinces
- 7899 municipalities
- 8026 total rows

The generated SQL requires PostgreSQL with PostGIS enabled.

## Simplified GeoJSON files

Generated files:

- `limits_IT_regions_covers_original_tolerance_500.geojson`
- `limits_IT_provinces_covers_original_tolerance_500.geojson`
- `limits_IT_municipalities_covers_original_tolerance_500.geojson`

Command used:

```bash
.venv/bin/python python/generate_simplified_datasets.py all \
  --coverage-policy covers-original \
  --tolerance-meters 500
```

The generator first wrote the default files in `generated-datasets/`:

- `generated-datasets/limits_IT_regions.covers-original.geojson`
- `generated-datasets/limits_IT_provinces.covers-original.geojson`
- `generated-datasets/limits_IT_municipalities.covers-original.geojson`

Then those files were copied into this folder with tolerance-specific names.

## Simplification notes

The current simplification script produces `Polygon` output for every feature. This includes source features that are originally `MultiPolygon`.

For the SQL export, the insert generator wraps original geometry with:

```sql
ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(...), 4326))
```

Simplified geometry is inserted without `ST_Multi(...)`, because the target column is `GEOMETRY(Polygon, 4326)` and the simplifier already emits `Polygon`.

The `covers-original` policy expands simplified geometry outward until it covers the original geometry. This avoids data loss, but can add visible extra area, especially for fragmented or island municipalities.

## Generation summary

The simplified GeoJSON command reported:

```text
dataset=regions, policy=covers-original, features=20, multipart=14, parts_removed=0, bridges_added=401, simplify_attempts=25, simplify_retries=5, base_fallbacks=0, cover_expansions=20, max_outward_expansion_meters=1534.469876
dataset=provinces, policy=covers-original, features=107, multipart=46, parts_removed=0, bridges_added=415, simplify_attempts=115, simplify_retries=8, base_fallbacks=0, cover_expansions=107, max_outward_expansion_meters=1278.122137
dataset=municipalities, policy=covers-original, features=7899, multipart=7899, parts_removed=0, bridges_added=849, simplify_attempts=7943, simplify_retries=44, base_fallbacks=0, cover_expansions=7899, max_outward_expansion_meters=3161.700261
```
