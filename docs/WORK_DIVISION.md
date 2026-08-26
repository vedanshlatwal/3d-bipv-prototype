# Work Division — 6 people

Module boundaries in `docs/ARCHITECTURE.md`. Everyone owns a module; coupling
exists only through the 7 documented interfaces.

## Person 1 — Team Lead / Integration (also owns `pipeline.py`)
- End-to-end orchestration, `cli.py`, config, wiring the data flow.
- Git hygiene, CI, demo story, acceptance criteria (docs/REQUIREMENTS.md §Acceptance).
- Deliverables: `pipeline.py`, `cli.py`, `config/`, `README`, AGENTS.md.
- Depends on: nothing (stubs first), then everyone.

## Person 2 — Data / 3D City Model Engineer (module `city_model`)
- GeoJSON/Shapefile ingest; OSM via osmnx; CityGML parser stub.
- Height extraction from tags; UTM reprojection (z-up).
- LoD1 extrusion into a watertight trimesh; per-face building id.
- Deliverables: `loader.py`, `extrusion.py`, sample GeoJSON city, ingest tests.
- Depends on: shapely, geopandas, pyproj, trimesh.

## Person 3 — Solar Physics Engineer (module `sun`)
- NOAA sun position (elevation/azimuth) — validated against reference values.
- Hottel clear-sky GHI/DNI/DHI; isotropic transposition to POA; ground reflection.
- pvlib-compatible function signatures so pvlib is a drop-in Phase-2 upgrade.
- Deliverables: `solar.py`, sun/irradiance tests (analytic golden values).
- Depends on: numpy, pandas.

## Person 4 — Geometry & Simulation Engineer (modules `shadow`, `surface`)
- Face normals/tilt/azimuth/area; roof vs wall classification.
- Sun-ray obstruction via trimesh ray casting; shadowed mask per timestep.
- Ray-based scaling plan for district size.
- Deliverables: `shadows.py`, `analysis.py`, shadow/surface tests.
- Depends on: person 2's mesh, person 3's sun table.

## Person 5 — Backend / API Engineer (module `api`)
- FastAPI service: `/health`, `POST /api/v1/analyze` (synchronous Phase 1).
- Job queue + status endpoint (Phase 2); input validation; output download.
- Deliverables: `api/main.py`, OpenAPI docs, API integration test.
- Depends on: person 1's pipeline interface.

## Person 6 — Frontend / Visualization Engineer (module `web`)
- Phase 1: consume exported GeoJSON → static color-coded map (folium/mapbox).
- Phase 2: React + CesiumJS 3D viewer with day/hour shadow slider, per-building
  detail card, potential legend.
- Deliverables: `web/` app, GeoJSON↔UI contract (color ramp for kWh/m²/yr).
- Depends on: person 5's API + person 4's exports.

## Suggested build order (so nothing blocks anyone)
1. **Week 1** — P1 defines interfaces + config; P2 delivers sample city +
   mesh; P3 delivers sun table. P5/P6 stub their layers with mock data.
2. **Week 2** — P4 surfaces + shadows on P2/P3 output; P1 wires E2E; P5 real
   endpoint; P6 real map.
3. **Week 3** — pvlib/Perez upgrade, Ray scaling, API async, CesiumJS polish,
   validation vs pvlib reference, demo rehearsal.

## Definition of done (per person)
- Own module has unit tests (`pytest`) + docstring contract matching
  `docs/ARCHITECTURE.md`.
- `python -m bipv run --input data/sample/buildings.geojson` works on their machine.
- No import of another person's module internals — only the public interfaces.