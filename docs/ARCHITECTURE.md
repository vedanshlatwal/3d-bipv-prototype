# Architecture

## Pipeline

```
GeoJSON / OSM / CityGML
        │
        ▼
┌─────────────────────┐     ┌──────────────────────┐
│ city_model.loader   │────►│ city_model.extrusion │  3D City Model
│ footprints (WGS84)  │     │ LoD1/LoD2 trimesh    │
└─────────────────────┘     └──────────┬───────────┘
                                       │ merged mesh + face→building
                                       ▼
┌─────────────────────┐     ┌──────────────────────┐
│ surface.analysis    │     │ sun.solar            │  Sun Position
│ classify roof/wall, │     │ NOAA + Hottel        │
│ tilt, azimuth, area │     │ hourly el/az, GHI    │
└──────────┬──────────┘     └──────────┬───────────┘
           │ per-face DataFrame        │ hourly sun table
           ▼                           ▼
┌─────────────────────┐     ┌──────────────────────┐
│ shadow.shadows      │────►│ sun.solar.poa_       │  Shadow Simulation
│ ray cast to sun     │     │ irradiance (beam+    │  + Solar Irradiance
│ → shadowed mask     │     │ diffuse+refl)        │
└──────────┬──────────┘     └──────────┬───────────┘
           └──────────────┬───────────┘
                          ▼
              ┌─────────────────────┐
              │ potential.potential │  Building Surface
              │ annual kWh/face +   │  Analysis
              │ kWh/building        │
              └──────────┬──────────┘
                         ▼
              ┌─────────────────────┐
              │ GeoJSON / CSV /     │  Solar Potential Map
              │ summary.json        │
              └─────────────────────┘
```

## Module contracts (the only coupling points)

1. `city_model.loader.load_buildings(path) -> geopandas.GeoDataFrame`
   (WGS84 polygons; column `height` in meters).
2. `city_model.extrusion.extrude_buildings(gdf) -> (trimesh.Trimesh,
   np.ndarray)` — returns merged mesh and a `face_to_building` array
   (`len = mesh.faces.shape[0]`).
3. `surface.analysis.classify_surfaces(mesh, face_to_building) -> pandas.DataFrame`
   — one row per face: `building_id, surface_type, area_m2, tilt_deg,
   azimuth_deg, normal_x/y/z`.
4. `sun.solar.sun_position(lat, lon, times) -> pandas.DataFrame` — index =
   timestamps; columns `elevation_deg, azimuth_deg, dni, dhi, ghi`.
5. `shadow.shadows.shadow_fraction(mesh, origins, sun_vectors) -> np.ndarray[bool]`
   — `True` means the surface is in shadow for that timestep.
6. `potential.potential.compute_potential(surfaces, sun_df, shadowed, cfg)
   -> (face_df, building_df)` and `export(...)`.
7. `pipeline.run_pipeline(cfg, input_path) -> ResultSummary`.

Changing one module must not touch another module's internals — only these
interfaces.

## Coordinate conventions

- Internal geometry: local UTM (meters), `z` up.
- Sun vectors: ENU — `x=East, y=North, z=Up`.
  - Ray from surface **toward the sun**:
    `d = (cos(el)·sin(az), cos(el)·cos(az), sin(el))` with azimuth clockwise
    from north, elevation above horizon.
  - Surface normal `nz > 0.5` ⇒ **roof**; `|nz| <= 0.5` ⇒ **wall**.
- Tilt = angle of face normal from vertical (0° = flat roof, 90° = wall).
- Azimuth = compass direction the face normal points (0°N, 90°E, 180°S, 270°W).

## Performance strategy

- Phase 1: annual hourly loop over faces. Fine for sample data, slow for
  districts. Face-level loops are vectorised with `numpy` where possible.
- Phase 2: split buildings across `Ray` workers; per-worker mesh = the whole
  city (shadow casting needs global context) but the surface loop is sharded.
- Phase 3: precompute sky-view factors / shadow map per face once, then
  evaluate any weather year in O(1) per face.

## API design

- `src/bipv/api/main.py` — FastAPI.
  - `GET /health` → `{status: "ok"}`.
  - `POST /api/v1/analyze` → body = city params (or uploaded GeoJSON) → runs
    pipeline synchronously → `{summary, outputs: {geojson, csv, json}}`.
  - Phase 2: job ids + `GET /api/v1/status/{job_id}` backed by a task queue.

## Frontend (Phase 2)

- `web/` — React + **CesiumJS** (real georeferenced 3D) or **deck.gl** (fast
  layers). Color-coded roof/wall surfaces by kWh/m²/yr; day/hour sun + shadow
  slider; building click → detail card. See `web/README.md`.