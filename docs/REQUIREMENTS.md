# Requirements

3D BIPV Potential Assessment — compute rooftop and vertical-surface solar
potential for Building Integrated Photovoltaics (BIPV) from 3D city models.

## Goal

A real-world-usable tool (not just a demo) that turns a 3D city model into an
actionable **solar potential map**: for every roof and wall of every building,
the annual photovoltaic energy yield (kWh/yr), so planners and citizens can
decide where BIPV makes economic sense.

## Functional requirements

### FR-1 3D City Model ingest
- FR-1.1 Load building footprints from GeoJSON/Shapefile (WGS84) and, optionally,
  from OpenStreetMap via `osmnx` and CityGML/CityJSON files.
- FR-1.2 Extract per-building height (from tags `height`, `building:levels`,
  `roof:height`) with a configurable default.
- FR-1.3 Reproject to a local projected CRS (UTM) in meters with `z` up.

### FR-2 LoD1/LoD2 extrusion
- FR-2.1 Extrude footprints to a watertight 3D mesh (LoD1: flat roof).
- FR-2.2 (Phase 2) LoD2: pitched roofs / roof shapes from roof tags.

### FR-3 Sun position
- FR-3.1 Compute solar elevation & azimuth for any date/time and location
  (NOAA algorithm; pvlib `solar_position` as production upgrade).

### FR-4 Solar irradiance
- FR-4.1 Compute hourly GHI/DNI/DHI under a clear-sky model.
- FR-4.2 Transpose to the plane of array (POA): beam + diffuse (isotropic now,
  Perez upgrade) + ground reflection, for arbitrary tilt/azimuth.

### FR-5 Shadow simulation
- FR-5.1 Determine, per surface per timestep, whether the sun ray is obstructed
  by a neighbouring building (ray casting on the 3D mesh).
- FR-5.2 (Phase 2) GPU-accelerated ray casting / sky-view-factor raster for
  district scale.

### FR-6 Building surface analysis
- FR-6.1 For every mesh face: area, surface normal, tilt, azimuth.
- FR-6.2 Classify faces: **roof** (normal upward, `nz > 0.5`) vs **wall**
  (vertical, `|nz| <= 0.5`).
- FR-6.3 Aggregate per building: total roof area, wall area by orientation.

### FR-7 Solar potential map
- FR-7.1 Annual energy per surface and per building:
  `kWh = sum(POA) * area * panel_efficiency * performance_ratio`.
- FR-7.2 Export `potential.geojson` (color-coded intensity), `potential.csv`,
  and `summary.json`.
- FR-7.3 (Phase 2) 3D web viewer (CesiumJS/deck.gl) with day/hour shadow slider.

### FR-8 API
- FR-8.1 `POST /api/v1/analyze` runs the pipeline for a given city + params.
- FR-8.2 `GET /health`, `GET /api/v1/status/<job>` (async jobs in Phase 2).

## Non-functional requirements

- **Accuracy:** sun elevation within ~0.01° of NOAA reference; annual yield
  within ±10% of pvlib-based reference implementation.
- **Scale:** handle ~10k buildings (a district) in under an hour with parallel
  shadow simulation.
- **Determinism:** identical input → identical output (seed, fixed timestep).
- **Reproducibility:** pinned dependency groups; clear-sky baseline documented.
- **Modularity:** modules owned independently by 6 people (see
  `WORK_DIVISION.md`), coupled only through the documented data flow.
- **Open data:** OSM / Open Government building footprints; MIT/BSD stack.

## Out of scope (Phase 1)
- Weather (real TMY data) — clear-sky only; TMY is a documented Phase-2 upgrade.
- Economics (tariffs, payback) — separate module later.
- Shading from vegetation / topography — geometry-only for now.

## Acceptance criteria (demo)
1. Sample city (4 buildings) → full annual potential computed < 1 min.
2. Two adjacent buildings: the one shaded by a tall neighbour shows reduced
   wall/roof yield — visible in the export.
3. `pytest` green; sun-position test matches NOAA reference within tolerance.
4. All six owners can run `python -m bipv run ...` on their machine.