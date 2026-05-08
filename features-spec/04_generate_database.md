# Generate database

## Goal

Create one database table containing Italian administrative areas from the original GeoJSON datasets:

- `regions`: `original-datasets/limits_IT_regions.geojson`
- `provinces`: `original-datasets/limits_IT_provinces.geojson`
- `municipalities`: `original-datasets/limits_IT_municipalities.geojson`

The table should store:

- common searchable metadata
- original ISTAT/source identifiers
- optional administrative centre coordinates
- bounding box
- original geometry
- simplified geometry

## Recommended database

Use PostgreSQL with PostGIS.

Reasons:

- the source geometry is GeoJSON `Polygon` / `MultiPolygon`
- spatial indexes are needed for bbox and geometry queries
- simplified and original geometries can be queried with the same API
- GeoJSON can be exported directly from PostGIS with `ST_AsGeoJSON`

## Single table

Table name:

```sql
italian_administrative_area
```

Admin type:

```sql
CREATE TYPE administrative_area_type AS ENUM (
  'region',
  'province',
  'municipality'
);
```

Table:

```sql
CREATE TABLE italian_administrative_area (
  id UUID PRIMARY KEY,
  type administrative_area_type NOT NULL,

  name TEXT NOT NULL,
  search_name TEXT NOT NULL,

  parent_region_id UUID REFERENCES italian_administrative_area(id),
  parent_province_id UUID REFERENCES italian_administrative_area(id),

  reg_name TEXT,
  reg_istat_code CHAR(2),
  reg_istat_code_num SMALLINT,

  prov_name TEXT,
  prov_istat_code CHAR(3),
  prov_istat_code_num SMALLINT,
  prov_acr VARCHAR(4),

  com_istat_code CHAR(6),
  com_istat_code_num INTEGER,
  com_catasto_code CHAR(4),

  op_id TEXT,
  opdm_id TEXT,
  minint_elettorale TEXT,
  minint_finloc TEXT,

  admin_center_lat DOUBLE PRECISION,
  admin_center_lng DOUBLE PRECISION,
  admin_center GEOMETRY(Point, 4326),
  admin_center_source TEXT,

  bbox_min_lng DOUBLE PRECISION NOT NULL,
  bbox_min_lat DOUBLE PRECISION NOT NULL,
  bbox_max_lng DOUBLE PRECISION NOT NULL,
  bbox_max_lat DOUBLE PRECISION NOT NULL,
  bbox GEOMETRY(Polygon, 4326) NOT NULL,

  geometry GEOMETRY(MultiPolygon, 4326) NOT NULL,
  simplified_geometry GEOMETRY(Polygon, 4326),

  source_properties JSONB NOT NULL DEFAULT '{}'::jsonb,
  source_dataset TEXT NOT NULL,
  source_updated_at DATE,

  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT italian_area_region_required CHECK (
    reg_istat_code IS NOT NULL
  ),
  CONSTRAINT italian_area_province_fields CHECK (
    type = 'region'
    OR (prov_istat_code IS NOT NULL AND prov_name IS NOT NULL)
  ),
  CONSTRAINT italian_area_municipality_fields CHECK (
    type <> 'municipality'
    OR (com_istat_code IS NOT NULL AND com_catasto_code IS NOT NULL)
  )
);
```

## Column notes

### Identity

`id` should be generated as UUIDv7 at import time.

Use deterministic natural keys for upsert/import logic, but do not use them as the primary key:

- region: `type + reg_istat_code`
- province: `type + prov_istat_code`
- municipality: `type + com_istat_code`

Recommended unique constraints:

```sql
CREATE UNIQUE INDEX italian_area_region_code_uidx
  ON italian_administrative_area (reg_istat_code)
  WHERE type = 'region';

CREATE UNIQUE INDEX italian_area_province_code_uidx
  ON italian_administrative_area (prov_istat_code)
  WHERE type = 'province';

CREATE UNIQUE INDEX italian_area_municipality_code_uidx
  ON italian_administrative_area (com_istat_code)
  WHERE type = 'municipality';
```

### Names

`name` is the display name:

- region: `reg_name`
- province: `prov_name`
- municipality: `name`

`search_name` is a normalized version generated during import, for example lowercased and accent-folded.

### Parent references

Keep both source codes and self-referencing parent IDs.

- `parent_region_id` is set for provinces and municipalities.
- `parent_province_id` is set for municipalities.
- source code columns remain useful for imports, debugging, and external interoperability.

### Geometry

Normalize all original area geometries to `MultiPolygon`.

The original datasets contain both `Polygon` and `MultiPolygon`; storing everything as `MultiPolygon` keeps the schema stable.

`geometry` stores the original full-resolution boundary.

`simplified_geometry` stores the generated simplified boundary. The current simplification generator emits one `Polygon` per feature, so the database column should use `GEOMETRY(Polygon, 4326)`.

### Bounding box

Store bbox twice:

- numeric columns: fast API responses and simple filtering
- PostGIS `bbox` polygon: spatial index and intersection queries

The numeric values should follow GeoJSON bbox order:

```text
min_lng, min_lat, max_lng, max_lat
```

`bbox` can be generated from those values with `ST_MakeEnvelope(min_lng, min_lat, max_lng, max_lat, 4326)`.

### Administrative centre

If `original-datasets/osm_IT_admin_centers.geojson` is available, join by:

- region: `reg_istat_code`
- province: `prov_istat_code`
- municipality: `com_istat_code`

Use:

- `admin_center_lat` from `admin_centre_lat`
- `admin_center_lng` from `admin_centre_lon`
- `admin_center` as `ST_SetSRID(ST_MakePoint(admin_center_lng, admin_center_lat), 4326)`
- `admin_center_source` as `OpenStreetMap`

Keep centre metadata in `source_properties` if the application needs OSM relation IDs, URLs, or label coordinates.

## Indexes

```sql
CREATE INDEX italian_area_type_idx
  ON italian_administrative_area (type);

CREATE INDEX italian_area_name_idx
  ON italian_administrative_area (search_name);

CREATE INDEX italian_area_region_idx
  ON italian_administrative_area (reg_istat_code);

CREATE INDEX italian_area_province_idx
  ON italian_administrative_area (prov_istat_code);

CREATE INDEX italian_area_parent_region_idx
  ON italian_administrative_area (parent_region_id);

CREATE INDEX italian_area_parent_province_idx
  ON italian_administrative_area (parent_province_id);

CREATE INDEX italian_area_bbox_gix
  ON italian_administrative_area
  USING GIST (bbox);

CREATE INDEX italian_area_geometry_gix
  ON italian_administrative_area
  USING GIST (geometry);

CREATE INDEX italian_area_simplified_geometry_gix
  ON italian_administrative_area
  USING GIST (simplified_geometry);

CREATE INDEX italian_area_admin_center_gix
  ON italian_administrative_area
  USING GIST (admin_center);
```

## Import mapping

### Regions

Source properties:

- `reg_name`
- `reg_istat_code`
- `reg_istat_code_num`

Mapping:

- `type`: `region`
- `name`: `reg_name`
- `reg_*`: copied from source
- `geometry`: source geometry normalized to `MultiPolygon`
- `bbox`: computed from source geometry

### Provinces

Source properties:

- `prov_name`
- `prov_istat_code`
- `prov_istat_code_num`
- `prov_acr`
- `reg_name`
- `reg_istat_code`
- `reg_istat_code_num`

Mapping:

- `type`: `province`
- `name`: `prov_name`
- `reg_*`, `prov_*`: copied from source
- `parent_region_id`: resolved from `reg_istat_code`
- `geometry`: source geometry normalized to `MultiPolygon`
- `bbox`: computed from source geometry

### Municipalities

Source properties:

- `name`
- `op_id`
- `minint_elettorale`
- `minint_finloc`
- `prov_name`
- `prov_istat_code`
- `prov_istat_code_num`
- `prov_acr`
- `reg_name`
- `reg_istat_code`
- `reg_istat_code_num`
- `opdm_id`
- `com_catasto_code`
- `com_istat_code`
- `com_istat_code_num`

Mapping:

- `type`: `municipality`
- `name`: `name`
- `reg_*`, `prov_*`, `com_*`: copied from source
- `parent_region_id`: resolved from `reg_istat_code`
- `parent_province_id`: resolved from `prov_istat_code`
- `geometry`: source geometry normalized to `MultiPolygon`
- `bbox`: computed from source geometry

## API usage model

Use `simplified_geometry` for list/map overview responses.

Use `geometry` only for detail views, downloads, or precision-sensitive spatial operations.

Recommended output fields for map listings:

```text
id
type
name
reg_istat_code
prov_istat_code
com_istat_code
admin_center_lat
admin_center_lng
bbox_min_lng
bbox_min_lat
bbox_max_lng
bbox_max_lat
simplified_geometry as GeoJSON
```

Recommended output fields for detail:

```text
all metadata columns
bbox
admin_center
geometry as GeoJSON
simplified_geometry as GeoJSON
```

## SQL insert generator

Generate insert statements with:

```bash
python3 python/generate_postgres_inserts.py all
```

Default output:

```text
generated-datasets/italian_administrative_area_inserts.sql
```

The generator imports `python/generate_simplified_datasets.py` and uses its `transform_feature` function for simplified geometry. The current simplifier reduces every feature to a single `Polygon`, even when the original source geometry is a `MultiPolygon`; the SQL generator therefore wraps only original geometry with `ST_Multi(...)` and keeps simplified geometry as `Polygon`.
