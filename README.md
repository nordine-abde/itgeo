Original dataset was downloaded from [geojson-italy](https://github.com/openpolis/geojson-italy) (License CC-BY-4.0)

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

Use the v1 simplification generator to produce Polygon-only derived datasets in `simplified-datasets/`:

```bash
python3 python/generate_simplified_datasets.py all
python3 python/generate_simplified_datasets.py municipalities --format formatted
python3 python/generate_simplified_datasets.py provinces --tolerance-meters 750 --minimum-part-area-sqm 100000 --bridge-width-meters 200
```

The generator:

- keeps source `properties` unchanged
- computes feature-level `bbox` from the original geometry
- forces `Polygon` output
- reduces multipart geometries with area filtering plus bridge-based connection
- applies Douglas-Peucker simplification with a bounded fallback ladder

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

The script writes the output files into `simplified-datasets/` using these names:

- `limits_IT_regions.simplified.geojson`
- `limits_IT_provinces.simplified.geojson`
- `limits_IT_municipalities.simplified.geojson`

### What each parameter means

- `dataset`: chooses which source dataset to process. Use `all` to generate every simplified file in one run.
- `--tolerance-meters`: Douglas-Peucker simplification tolerance in meters. Higher values remove more vertices and produce more aggressive simplification. Lower values preserve more detail.
- `--minimum-part-area-sqm`: minimum area, in square meters, for polygon parts inside a `MultiPolygon`. Parts smaller than this threshold are ignored before bridge generation. Raise it to discard more small islands or detached fragments.
- `--bridge-width-meters`: width, in meters, of the artificial corridors used to connect disjoint polygon parts. Larger widths make bridges more robust but also add more invented connecting area.
- `--fallback-multipliers`: comma-separated tolerance multipliers used when simplification creates an invalid polygon. For example, `1,0.5,0.25,0.125` means try `T`, then `T/2`, then `T/4`, then `T/8`.
- `--format`: output JSON formatting. `compact` writes smaller files, `formatted` writes easier-to-read files for inspection.

### Practical examples

Generate every simplified dataset with the default aggressive settings:

```bash
python3 python/generate_simplified_datasets.py all
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
