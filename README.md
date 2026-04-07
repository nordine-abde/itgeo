Original dataset was downloaded from [text](https://github.com/openpolis/geojson-italy/tree/master) (License CC-BY-4.0)

## Create smaller subsets

Use the Python helper to extract smaller GeoJSON files from the heavy originals:

```bash
python3 python/extract_geojson_subset.py municipalities --limit 25
python3 python/extract_geojson_subset.py municipalities --limit 25 --output-file sample.geojson
python3 python/extract_geojson_subset.py municipalities --region Lazio --limit 10 --sample-mode first
python3 python/extract_geojson_subset.py provinces --province MI --limit 5
```

The script always writes inside `generated-datasets/`. Use `--output-file` to choose the file name.
