# 3D BIPV Potential Assessment

Compute **rooftop and vertical building-surface solar potential** for Building
Integrated Photovoltaics (BIPV) using 3D city models.

```
3D City Model  ->  Sun Position  ->  Shadow Simulation  ->  Solar Irradiance
                 ->  Building Surface Analysis  ->  Solar Potential Map
```

The system ingests building footprints (OSM / GeoJSON / CityGML), extrudes them
into a LoD1/LoD2 3D city model, simulates shadows cast by neighbouring
buildings over the year, computes hourly irradiance on every roof and wall
surface, and outputs per-surface and per-building solar potential maps.

## Quick start

```powershell
# 1. Create environment (Python 3.11+)
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. Install
pip install -e ".[dev]"

# 3. Run the end-to-end pipeline on the bundled sample city
python -m bipv run --input data/sample/buildings.geojson --lat 28.6139 --lon 77.2090

# Outputs land in data/output/:
#   potential.geojson   - per-surface + per-building potential (color-coded)
#   potential.csv       - tabular report
#   summary.json        - aggregate stats (kWh/yr per building, etc.)
```

## Useful commands

```powershell
python -m bipv run --input data/sample/buildings.geojson --lat 28.6139 --lon 77.2090   # full pipeline
python -m bipv sun --lat 28.6139 --lon 77.2090 --date 2026-03-21 --hour 12              # sun position check
python -m bipv api                                                                    # FastAPI server on :8000
pytest                                                                                 # unit tests
```

## Project layout

```
bipv-potential/
├── config/          # YAML config (city, solar, shadow defaults)
├── data/            # raw/ processed/ output/ and a sample GeoJSON city
├── docs/            # REQUIREMENTS, ARCHITECTURE, TECH_STACK, WORK_DIVISION
├── src/bipv/
│   ├── city_model/  # ingest + LoD1/LoD2 extrusion (3D City Model)
│   ├── sun/         # sun position + clear-sky irradiance (Sun Position)
│   ├── shadow/      # sun-ray obstruction between buildings (Shadow Simulation)
│   ├── surface/     # roof/wall classification, normals, tilt, azimuth (Surface Analysis)
│   ├── potential/   # energy aggregation + export (Solar Potential Map)
│   ├── api/         # FastAPI service
│   └── pipeline.py  # end-to-end orchestration
├── tests/
├── notebooks/       # exploration and validation notebooks
└── web/             # (Phase 2) 3D visualization frontend
```

## Status

This is the **initial skeleton**: a runnable core pipeline with a sample city,
unit tests, and a documented 6-person work plan. See `docs/` for requirements,
architecture, tech-stack rationale, and task ownership.

Phase 1 (skeleton): core pipeline, CLI, API, tests.
Phase 2: full-scale data (OSM/CityGML), GPU-accelerated shadows, Perez
transposition, 3D frontend (CesiumJS / deck.gl).