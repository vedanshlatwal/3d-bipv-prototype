from __future__ import annotations

import math
import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import bipv as bipv_mod
from . import elevation, geometry, osm_loader, shadows, solar

app = FastAPI(title="BIPV Potential API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

PEAK_CLEAR_POA = 1000.0
ELEVATION_ENABLED = os.getenv("BIPV_ELEVATION_ENABLED", "0").lower() in ("1", "true", "yes")


class BuildingsRequest(BaseModel):
    lat: float = 37.7749
    lon: float = -122.4194
    radius_m: float = 300.0


class SolarRequest(BaseModel):
    lat: float = 37.7749
    lon: float = -122.4194
    season: str = "equinox"
    hour: float = 12.0
    buildings: dict


def _empty_fc() -> dict:
    return {"type": "FeatureCollection", "features": []}


def _surface_summary(surfaces: list[dict]) -> dict:
    total_area = sum(s["area_m2"] for s in surfaces)
    total_kwp = sum(s.get("pv_capacity_kwp", 0.0) for s in surfaces)
    total_kwh = sum(s.get("annual_energy_kwh", 0.0) for s in surfaces)
    bld_ids = {s["building_id"] for s in surfaces}
    return {
        "buildings": len(bld_ids),
        "surfaces": len(surfaces),
        "total_area_m2": total_area,
        "total_kwp": total_kwp,
        "annual_kwh": total_kwh,
    }


@app.get("/health")
def health():
    return {"status": "ok", "service": "bipv-backend"}


def _elevation_profiles(bld, lat, lon):
    profiles = elevation.fallback_profiles(bld)
    if not ELEVATION_ENABLED:
        return profiles
    try:
        dlat = max(0.0005, 0.002)
        dlon = dlat / max(0.2, abs(math.cos(math.radians(lat))))
        dem = elevation.CopernicusDemProvider(
            west=lon - dlon, south=lat - dlat, east=lon + dlon, north=lat + dlat
        )
        profiles = elevation.elevation_profile(bld, dem_provider=dem)
    except Exception as exc:
        print(f"[BIPV] elevation disabled for this request: {exc}")
    return profiles


@app.post("/api/v1/buildings")
def buildings(req: BuildingsRequest):
    try:
        bld = osm_loader.fetch_osm_buildings(req.lat, req.lon, req.radius_m)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"OSM query failed: {exc}")

    if not bld:
        return {
            "buildings": _empty_fc(),
            "surfaces": [],
            "summary": _surface_summary([]),
            "assumptions": bipv_mod.assumptions(),
        }

    try:
        profiles = _elevation_profiles(bld, req.lat, req.lon)
        surfaces, _ = geometry.derive_surfaces(bld, req.lon, req.lat, elevation=profiles)
        ctx = solar.annual_context(req.lat, req.lon)
        cache: dict[tuple, float] = {}
        for s in surfaces:
            key = (round(s["tilt_deg"], 1), round(s["azimuth_deg"], 1))
            if key not in cache:
                cache[key] = solar.annual_poa(ctx, s["tilt_deg"], s["azimuth_deg"])
            irr = cache[key]
            s["annual_irradiation_kwh_m2"] = irr
            s["bipv_score"] = bipv_mod.bipv_score(irr)
            s.update(bipv_mod.bipv_potential(s["area_m2"], irr))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Geometry/solar failed: {exc}")

    return {
        "buildings": osm_loader.buildings_to_geojson(bld),
        "surfaces": surfaces,
        "summary": _surface_summary(surfaces),
        "assumptions": bipv_mod.assumptions(),
    }


@app.post("/api/v1/solar")
def simulate(req: SolarRequest):
    try:
        bld = geometry.buildings_from_geojson(req.buildings)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid buildings payload: {exc}")

    if not bld:
        return {"sun": {}, "surfaces": [], "summary": {}}

    try:
        surfaces, footprints = geometry.derive_surfaces(bld, req.lon, req.lat)
        pos = solar.position_and_clearsky(req.lat, req.lon, req.season, req.hour)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Solar computation failed: {exc}")

    sun_e, sun_n, sun_u = geometry.sun_vector_enu(pos["azimuth"], pos["elevation"])
    caster = shadows.ShadowCaster(footprints, sun_e, sun_n, sun_u)

    results = []
    for s in surfaces:
        if pos["elevation"] <= 0 or math.isnan(pos["azimuth"]):
            results.append(
                {
                    "surface_id": s["surface_id"],
                    "solar_score": 0.0,
                    "shade_fraction": 1.0,
                    "poa_w_m2": 0.0,
                }
            )
            continue
        shade = caster.fraction(s)
        poa_map = solar.poa(
            s["tilt_deg"],
            s["azimuth_deg"],
            pos["zenith"],
            pos["azimuth"],
            pos["ghi"],
            pos["dni"],
            pos["dhi"],
        )
        direct = float(poa_map.get("poa_direct", 0.0))
        diffuse = float(poa_map.get("poa_sky_diffuse", 0.0)) + float(
            poa_map.get("poa_ground_diffuse", 0.0)
        )
        poa_shaded = direct * shade + diffuse
        score = min(1.0, max(0.0, poa_shaded / PEAK_CLEAR_POA))
        results.append(
            {
                "surface_id": s["surface_id"],
                "solar_score": score,
                "shade_fraction": shade,
                "poa_w_m2": poa_shaded,
            }
        )

    sun = {
        "elevation": pos["elevation"],
        "azimuth": pos["azimuth"],
        "zenith": pos["zenith"],
        "ghi": pos["ghi"],
        "dni": pos["dni"],
        "dhi": pos["dhi"],
    }
    return {"sun": sun, "surfaces": results}
