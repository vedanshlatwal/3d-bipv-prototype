from __future__ import annotations

from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
from pyproj import CRS

HEIGHT_KEYS = ("height", "roof:height", "building:levels")


def _building_height(props: dict[str, Any], default: float) -> float:
    if props.get("height") is not None:
        try:
            return float(props["height"])
        except (TypeError, ValueError):
            pass
    levels = props.get("building:levels")
    if levels is not None:
        try:
            return float(levels) * 3.0
        except (TypeError, ValueError):
            pass
    roof = props.get("roof:height")
    if roof is not None:
        try:
            return float(roof) + 3.0
        except (TypeError, ValueError):
            pass
    return float(default)


def load_buildings(path: str | Path, target_crs: str = "EPSG:32643", default_height: float = 10.0) -> gpd.GeoDataFrame:
    """Load building footprints (GeoJSON/Shapefile), assign heights, reproject to local UTM meters (z-up).

    Returns a GeoDataFrame in `target_crs` with columns: geometry (polygons in
    meters), height (m), building_id, name (optional).
    """
    path = Path(path)
    if path.suffix.lower() == ".json":
        gdf = gpd.read_file(path, driver="GeoJSON")
    else:
        gdf = gpd.read_file(path)

    if gdf.empty:
        raise ValueError(f"No features found in {path}")

    if "id" not in gdf.columns and "building_id" not in gdf.columns:
        gdf["building_id"] = [f"bld_{i:04d}" for i in range(len(gdf))]
    elif "building_id" not in gdf.columns:
        gdf["building_id"] = gdf["id"].astype(str)

    gdf = gdf.copy()
    gdf["height"] = gdf.apply(lambda r: _building_height(dict(r.items()), default_height), axis=1)
    gdf["height"] = gdf["height"].fillna(default_height).clip(lower=1.0)

    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    target = CRS.from_user_input(target_crs)
    if not gdf.crs.equals(target):
        gdf = gdf.to_crs(target)
    return gdf[["geometry", "building_id", "height", "name"]]


def load_osm_place(place: str, target_crs: str = "EPSG:32643") -> gpd.GeoDataFrame:
    """Optional: pull building footprints from OpenStreetMap via osmnx.

    Requires the `osm` extra (osmnx). Raises ImportError if unavailable.
    """
    try:
        import osmnx as ox
    except ImportError as exc:
        raise ImportError("osmnx is not installed. Install the 'osm' extra: pip install bipv[osm]") from exc

    gdf = ox.features_from_place(place, tags={"building": True})
    gdf = gdf[gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].reset_index()
    gdf = gdf.rename(columns={"building": "_building"}).copy()
    gdf["building_id"] = gdf.index.map(lambda i: f"osm_{i:06d}")
    gdf["name"] = gdf.get("name", "").fillna("")
    gdf = gdf[["geometry", "building_id", "name"] + [c for c in gdf.columns if c in HEIGHT_KEYS]]
    return gdf.to_crs(target_crs)


def osm_buildings_to_geojson(place: str, out_path: str | Path, target_crs: str = "EPSG:4326") -> Path:
    gdf = load_osm_place(place, target_crs=target_crs)
    out_path = Path(out_path)
    gdf.to_file(out_path, driver="GeoJSON")
    return out_path