# AGENTS.md

Guidance for AI agents (and humans) working in this repository.

## Project

3D BIPV Potential Assessment — computes rooftop and vertical-surface solar
potential for Building Integrated Photovoltaics from 3D city models.

## Layout & ownership

- `src/bipv/city_model/` — data ingest (OSM/GeoJSON/CityGML) + LoD1/LoD2 extrusion.
- `src/bipv/sun/` — sun position + clear-sky irradiance. **Does not require pvlib**; uses built-in NOAA + Hottel model. pvlib is an optional upgrade.
- `src/bipv/shadow/` — sun-ray obstruction via `trimesh` ray casting.
- `src/bipv/surface/` — roof/wall classification, normals, tilt, azimuth.
- `src/bipv/potential/` — energy aggregation + GeoJSON/CSV export.
- `src/bipv/pipeline.py` — end-to-end orchestration (data flow below).
- `src/bipv/api/` — FastAPI service.
- `config/config.yaml` — runtime defaults. Env vars with prefix `BIPV_` override.

## Data flow (read this before editing pipeline code)

1. `city_model.loader.load_buildings()` → GeoDataFrame (WGS84) → reproject to a local UTM CRS (meters, `z` up).
2. `city_model.extrusion.extrude_buildings()` → merged `trimesh` + per-face metadata (building id, roof/wall flag).
3. `surface.analysis.classify_surfaces()` → per-face DataFrame: area, tilt, azimuth, normal.
4. `sun.solar.sun_position()` → hourly elevation/azimuth over the configured year.
5. `shadow.shadows.shadow_fraction()` → per-face shadowed mask per sun position.
6. `sun.solar.poa_irradiance()` → beam + diffuse + reflected on each tilted face.
7. `potential.potential.compute_potential()` → annual kWh per face/building + export.

Do not reorder: each module consumes the previous stage's output.

## Conventions & gotchas

- **Coordinates:** everything is computed in local UTM meters with `z` up. Sun rays
  use ENU convention: `(E=x, N=y, U=z)`; azimuth is degrees clockwise from north;
  elevation is degrees above horizon. Surface normal `nz > 0.5` ⇒ roof, else wall.
- **No comments in code unless asked.** Keep the codebase comment-free per repo style.
- **Runbook:** `pytest` (unit tests), `python -m bipv run ...` (manual E2E). No linter/formatter pinned yet — use `ruff` if installed, otherwise match surrounding style.
- **Test only the physics:** tests validate against known analytic values (e.g.
  solar noon elevation, perpendicular-face beam irradiance), not network or files.
- **Big time loops are slow in Python:** the default annual hourly loop is fine for
  the ~4-building sample, not for a district. Scale via `Ray` (see `docs/ARCHITECTURE.md`).
- **Config:** `config/config.yaml` defaults; env var `BIPV_` prefix overrides
  (e.g. `BIPV_SOLAR_LATITUDE`).

## Multi-agent setup

This repo was scaffolded for a 6-person build. Ownership matrix in
`docs/WORK_DIVISION.md`. Agents should respect module boundaries — `city_model`,
`sun`, `shadow`, `surface`, `potential`, `api`, `web` are owned independently.