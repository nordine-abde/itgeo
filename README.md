Original boundary datasets were downloaded from [geojson-italy](https://github.com/openpolis/geojson-italy) (License CC-BY-4.0).

Optional administrative centre data can be generated from [OpenStreetMap](https://www.openstreetmap.org/) data, for example using the [Geofabrik Italy extract](https://download.geofabrik.de/europe/italy.html). OpenStreetMap data is available under the [Open Database License](https://www.openstreetmap.org/copyright). If this derived dataset is used or redistributed, keep OpenStreetMap attribution visible and preserve the ODbL obligations that apply to the generated database.

## Python setup

Create and activate a local virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install the project dependencies:

```bash
python3 -m pip install -r requirements.txt
```

## Extract OSM administrative centres

Use this helper to generate a separate admin-centre point dataset from an Italy OSM PBF extract:

```bash
python3 python/extract_osm_admin_centers.py --download
```

The default download source is the Geofabrik Italy extract, written locally as `original-datasets/italy-latest.osm.pbf`. The `.osm.pbf` extract is intentionally ignored by git because it is large and can be downloaded again.

If you already downloaded the extract manually:

```bash
python3 python/extract_osm_admin_centers.py --osm-pbf original-datasets/italy-latest.osm.pbf
```

The generated file is:

- `original-datasets/osm_IT_admin_centers.geojson`

The script reads OSM administrative boundary relations for Italian regions, provinces, and municipalities (`admin_level` 4, 6, and 8), extracts the `admin_centre` relation member when present, and stores the admin-centre point as the feature geometry. OSM `label` members are kept only as separate properties. This dataset is intentionally separate from future geometric-centre or centroid datasets.

## Create smaller subsets

Use the Python helper to extract smaller GeoJSON files from the heavy originals:

```bash
python3 python/extract_geojson_subset.py municipalities --limit 25
python3 python/extract_geojson_subset.py municipalities --limit 25 --format formatted
python3 python/extract_geojson_subset.py municipalities --limit 25 --output-file sample.geojson
python3 python/extract_geojson_subset.py municipalities --region Lazio --limit 10 --sample-mode first
python3 python/extract_geojson_subset.py provinces --province MI --limit 5
```

The script always writes inside `generated-datasets/`. Use `--output-file` to choose the file name and `--format formatted` for pretty-printed JSON.

## Generate simplified datasets

Use the simplification generator to produce Polygon-only derived datasets in `generated-datasets/`:

```bash
python3 python/generate_simplified_datasets.py all
python3 python/generate_simplified_datasets.py municipalities --format formatted
python3 python/generate_simplified_datasets.py provinces --tolerance-meters 750 --minimum-part-area-sqm 100000 --bridge-width-meters 200
python3 python/generate_simplified_datasets.py regions --coverage-policy covers-original
python3 python/generate_simplified_datasets.py provinces --coverage-policy covers-original --output-file provinces-cover.geojson
```

The generator:

- keeps source `properties` unchanged
- computes feature-level `bbox` from the original geometry
- forces `Polygon` output
- reduces multipart geometries with area filtering plus bridge-based connection
- applies Douglas-Peucker simplification with a bounded fallback ladder
- can run in `covers-original` mode to keep the final polygon as an outer approximation of the full source geometry

### How to use the generator

General form:

```bash
python3 python/generate_simplified_datasets.py <dataset> [options]
```

Where `<dataset>` can be:

- `all`: process regions, provinces, and municipalities
- `regions`: process only `original-datasets/limits_IT_regions.geojson`
- `provinces`: process only `original-datasets/limits_IT_provinces.geojson`
- `municipalities`: process only `original-datasets/limits_IT_municipalities.geojson`

The script always writes generated files into `generated-datasets/`.

Default file names are mode-aware so `free` and `covers-original` runs do not overwrite each other:

- `limits_IT_regions.simplified.geojson`
- `limits_IT_provinces.simplified.geojson`
- `limits_IT_municipalities.simplified.geojson`
- `limits_IT_regions.covers-original.geojson`
- `limits_IT_provinces.covers-original.geojson`
- `limits_IT_municipalities.covers-original.geojson`

Use `--output-file <name>.geojson` to choose the file name for a single-dataset run. The name is written inside `generated-datasets/`. Repo-tracked copies in `simplified-subset/` are selected manually outside the generator.

### What each parameter means

- `dataset`: chooses which source dataset to process. Use `all` to generate every simplified file in one run.
- `--coverage-policy`: controls whether the generator is free to simplify inward or must preserve full source coverage. `free` keeps the current aggressive v1 behavior. `covers-original` keeps all original polygon parts, bridges disjoint components when needed, then expands the simplified result outward until it covers the full normalized source geometry.
- `-o, --output-file`: chooses the output file name inside `generated-datasets/`. This is accepted only when processing a single dataset. Path components are ignored; only the file name is used.
- `--tolerance-meters`: Douglas-Peucker simplification tolerance in meters. Higher values remove more vertices and produce more aggressive simplification. Lower values preserve more detail.
- `--minimum-part-area-sqm`: minimum area, in square meters, for polygon parts inside a `MultiPolygon`. In `free` mode, parts smaller than this threshold are ignored before bridge generation. In `covers-original` mode, this parameter is ignored and all parts are retained.
- `--bridge-width-meters`: width, in meters, of the artificial corridors used to connect disjoint polygon parts. Larger widths make bridges more robust but also add more invented connecting area.
- `--fallback-multipliers`: comma-separated tolerance multipliers used when simplification creates an invalid polygon. For example, `1,0.5,0.25,0.125` means try `T`, then `T/2`, then `T/4`, then `T/8`.
- `--format`: output JSON formatting. `compact` writes smaller files, `formatted` writes easier-to-read files for inspection.

### Practical examples

Generate every simplified dataset with the default aggressive settings:

```bash
python3 python/generate_simplified_datasets.py all
```

Generate municipalities with the conservative outer-cover mode:

```bash
python3 python/generate_simplified_datasets.py municipalities --coverage-policy covers-original
```

Generate only municipalities with a lower tolerance to preserve more boundary detail:

```bash
python3 python/generate_simplified_datasets.py municipalities --tolerance-meters 500
```

Generate only provinces while discarding smaller multipart fragments more aggressively:

```bash
python3 python/generate_simplified_datasets.py provinces --minimum-part-area-sqm 500000
```

Generate formatted output for manual inspection:

```bash
python3 python/generate_simplified_datasets.py regions --format formatted
```

Choose a custom output file name for a single-dataset run:

```bash
python3 python/generate_simplified_datasets.py provinces --coverage-policy covers-original --output-file provinces-cover.geojson
```

## Generate PostgreSQL inserts

Use the SQL exporter to generate PostGIS insert statements for the single-table database structure:

```bash
python3 python/generate_postgres_inserts.py all
```

The default output file is:

- `generated-datasets/italian_administrative_area_inserts.sql`

The exporter reuses `python/generate_simplified_datasets.py` for simplified geometry generation. That simplifier intentionally emits `Polygon` geometry, including when the source is a `MultiPolygon`; the SQL exporter wraps original geometry with `ST_Multi(...)` and stores simplified geometry as `GEOMETRY(Polygon, 4326)`.

Useful examples:

```bash
python3 python/generate_postgres_inserts.py regions
python3 python/generate_postgres_inserts.py provinces --coverage-policy covers-original
python3 python/generate_postgres_inserts.py municipalities --output-file generated-datasets/municipality-inserts.sql
python3 python/generate_postgres_inserts.py all --limit 5 --output-file generated-datasets/sample-inserts.sql
```
