from __future__ import annotations

import time

import requests

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
OVERPASS_ATTEMPTS = 2
USER_AGENT = "3D-BIPV-Assessment/0.1 (development project)"
DEFAULT_FLOOR_HEIGHT = 3.0
DEFAULT_HEIGHT = 10.0


def _height_from_tags(tags: dict) -> tuple[float, str]:
    for key in ("height", "building:height"):
        raw = tags.get(key)
        if raw:
            try:
                return max(1.0, float(raw)), "height"
            except (TypeError, ValueError):
                pass
    levels = tags.get("building:levels")
    if levels:
        try:
            return max(1.0, float(levels) * DEFAULT_FLOOR_HEIGHT), "building:levels"
        except (TypeError, ValueError):
            pass
    return DEFAULT_HEIGHT, "default"


def resolve_roof(tags: dict) -> dict:
    shape = (tags.get("roof:shape") or "").strip().lower()
    roof_height = None
    raw_height = tags.get("roof:height")
    if raw_height:
        try:
            roof_height = float(raw_height)
        except (TypeError, ValueError):
            roof_height = None
    orientation = tags.get("roof:orientation") or tags.get("roof:direction")
    return {
        "roof_shape": shape,
        "roof_height": roof_height,
        "roof_levels": tags.get("roof:levels"),
        "roof_orientation": orientation,
        "roof_angle": tags.get("roof:angle"),
    }


def fetch_osm_buildings(lat: float, lon: float, radius_m: float) -> list[dict]:
    from shapely.geometry import Polygon

    radius_m = max(50.0, min(float(radius_m), 2000.0))
    query = (
        "[out:json][timeout:90];"
        f"(way['building'](around:{int(radius_m)},{lat},{lon});"
        f" relation['building'](around:{int(radius_m)},{lat},{lon}););"
        "out geom;"
    )

    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    last_error: Exception | None = None
    for _ in range(OVERPASS_ATTEMPTS):
        for url in OVERPASS_URLS:
            try:
                resp = requests.post(url, data={"data": query}, headers=headers, timeout=90)
                if resp.status_code >= 400:
                    last_error = RuntimeError(f"{resp.status_code} {resp.text[:120]}")
                    continue
                data = resp.json()
                return _parse_overpass(data)
            except Exception as exc:  # noqa: BLE001 - network/provider errors
                last_error = exc
        time.sleep(1.0)

    raise last_error or RuntimeError("Overpass request failed")


def _parse_overpass(data: dict) -> list[dict]:
    from shapely.geometry import Polygon

    buildings: list[dict] = []
    for el in data.get("elements", []):
        if el.get("type") != "way":
            continue
        geom = el.get("geometry")
        if not geom or len(geom) < 4:
            continue
        coords = [(p["lon"], p["lat"]) for p in geom]
        if coords[0] != coords[-1]:
            coords.append(coords[0])
        try:
            poly = Polygon(coords)
            if not poly.is_valid:
                poly = poly.buffer(0)
            if poly.is_empty or poly.area <= 0:
                continue
        except Exception:
            continue
        tags = el.get("tags", {})
        height_m, height_source = _height_from_tags(tags)
        roof = resolve_roof(tags)
        buildings.append(
            {
                "building_id": f"way/{el['id']}",
                "geometry": poly,
                "height_m": height_m,
                "height_source": height_source,
                "building_type": tags.get("building", ""),
                "levels": tags.get("building:levels"),
                **roof,
            }
        )
    return buildings


def buildings_to_geojson(buildings: list[dict]) -> dict:
    features = []
    for b in buildings:
        features.append(
            {
                "type": "Feature",
                "id": b["building_id"],
                "geometry": b["geometry"].__geo_interface__,
                "properties": {
                    "building_id": b["building_id"],
                    "height_m": b["height_m"],
                    "height_source": b["height_source"],
                    "building_type": b.get("building_type", ""),
                    "levels": b.get("levels"),
                    "roof_shape": b.get("roof_shape", ""),
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}
