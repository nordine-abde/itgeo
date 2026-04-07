# GeoJSON Quick Guide

## What is GeoJSON?

GeoJSON is a format for storing geographic data using JSON. It
represents shapes on a map along with their attributes.

------------------------------------------------------------------------

## Core Structure

### FeatureCollection

A GeoJSON file usually starts with:

    {
      "type": "FeatureCollection",
      "features": [...]
    }

------------------------------------------------------------------------

### Feature

Each item in `features`:

    {
      "type": "Feature",
      "properties": {...},
      "geometry": {...}
    }

-   **properties**: metadata (name, id, etc.)
-   **geometry**: shape data

------------------------------------------------------------------------

### Geometry Types

#### Point

    { "type": "Point", "coordinates": [lon, lat] }

#### LineString

    { "type": "LineString", "coordinates": [[lon, lat], [lon, lat]] }

#### Polygon

    {
      "type": "Polygon",
      "coordinates": [[[lon, lat], ...]]
    }

------------------------------------------------------------------------

## Coordinate Order

Always:

    [longitude, latitude]

Example:

    [2.1734, 41.3851]

------------------------------------------------------------------------

## MultiPolygon

Used when an area has multiple parts:

    {
      "type": "MultiPolygon",
      "coordinates": [[[[...]]], [[[...]]]]
    }

------------------------------------------------------------------------

## Typical Municipality File

-   FeatureCollection
-   Each Feature = one municipality
-   Geometry = Polygon or MultiPolygon
-   Properties = name, id, region

------------------------------------------------------------------------

## Mental Model

GeoJSON = shapes + data

  Component    Meaning
  ------------ ------------
  Feature      One object
  Geometry     Shape
  Properties   Attributes

------------------------------------------------------------------------

## Tips

-   Use geojson.io or QGIS to visualize
-   Validate JSON if errors occur
-   Watch coordinate order and polygon closure
