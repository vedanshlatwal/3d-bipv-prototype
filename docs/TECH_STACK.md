# Tech Stack

Chosen for: (1) a **visually impressive SIH demo**, (2) **real-world usability**,
(3) a **6-person team** where everyone owns an independent module.

## Core language & runtime
| Component | Choice | Why |
|---|---|---|
| Language | Python 3.11+ | Scientific + geospatial ecosystem is unmatched |
| Packaging | `pyproject.toml` + `setuptools` | Standard, works on Windows |

## 3D City Model (module: city_model)
| Component | Choice | Why |
|---|---|---|
| Footprints | GeoJSON / Shapefile; **osmnx** for OSM, CityGML/CityJSON parser | Free, open, real-world data |
| Projection | **pyproj** | WGS84 → UTM (meters, z-up) |
| 3D mesh | **trimesh** | Watertight extrusion, ray casting, face normals |

## Solar physics (module: sun)
| Component | Choice | Why |
|---|---|---|
| Sun position | built-in NOAA algorithm | Zero-dependency, validated; **pvlib** `solar_position` is the production upgrade |
| Clear-sky irradiance | Hottel model (built-in) | Simple, analytic; pvlib `ineichen` + `perez` upgrade |
| Transposition | Isotropic sky (built-in) | Good Phase-1 baseline; **Perez** upgrade in Phase 2 |

## Geometry & simulation (modules: surface, shadow)
| Component | Choice | Why |
|---|---|---|
| Surface analysis | `shapely` + `trimesh` normals | Area, tilt, azimuth, roof/wall |
| Shadows | `trimesh.ray.intersects_location` | Exact per-face sun-ray obstruction |
| Parallelism (Phase 2) | **Ray** | District-scale sharding of the annual loop |

## Backend / API
| Component | Choice | Why |
|---|---|---|
| API | **FastAPI** + uvicorn | Async, typed, auto-docs, easy demo |
| Storage (Phase 2) | PostGIS (optional), else GeoJSON/Parquet | Spatial queries for large cities |

## Frontend (Phase 2)
| Component | Choice | Why |
|---|---|---|
| 3D viewer | **CesiumJS** (React) | Real georeferenced 3D city + shadows slider — the "wow" demo |
| Alternative | **deck.gl** | Faster layer-based rendering for huge meshes |

## Data / outputs
- `GeoJSON` (color-coded intensity), `CSV` (tabular), `JSON` (summary) — every
  mainstream GIS/BI tool opens these.

## Optional extras (not required for skeleton)
- `pvlib` — industry-standard solar models (Ineichen, Perez, TMY support).
- `matplotlib` / `folium` — quick static maps for validation.
- `ray` — parallel shadow simulation.
- `pytest` + `ruff` — tests and lint.

## Why not X?
- **CityGML-only** — heavy schema; GeoJSON is the 80% case and trivial to demo.
- **C++/Rust core** — unnecessary at this stage; numpy/trimesh vectorisation is
  enough for a district; drop to Ray only if profiling demands it.
- **Desktop-only (QGIS/Blender plugin)** — less shareable for a hackathon demo;
  API + web viewer is more impressive and more useful.