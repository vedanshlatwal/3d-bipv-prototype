from __future__ import annotations

import hashlib
import json
import math
import os
import time
from pathlib import Path

import numpy as np

CACHE_DIR = Path(os.getenv("BIPV_ELEVATION_CACHE", "data/elevation/cache"))
DEM_URL = "https://portal.opentopography.org/API/globaldem"
DEM_TYPE = "COP30"
DEM_CACHE_TTL_S = 7 * 86400

ROOF_SHAPES = {"flat", "gabled", "hipped", "pyramidal", "skillion"}


def _cache_key(params: dict) -> str:
    return hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()[:24]


def _cache_get(params: dict):
    try:
        p = CACHE_DIR / (_cache_key(params) + ".json")
        if not p.exists():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
        if time.time() - float(data.get("t", 0)) > DEM_CACHE_TTL_S:
            return None
        return data.get("v")
    except Exception:
        return None


def _cache_put(params: dict, value) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (CACHE_DIR / (_cache_key(params) + ".json")).write_text(
            json.dumps({"t": time.time(), "v": value}), encoding="utf-8"
        )
    except Exception:
        pass


class ElevationProvider:
    def sample(self, lon: float, lat: float) -> float | None:
        raise NotImplementedError


class RasterGrid:
    def __init__(self, grid, xll, yll, cellsize, nodata=-9999.0):
        self.grid = np.asarray(grid, dtype=float)
        self.xll = xll
        self.yll = yll
        self.cellsize = cellsize
        self.nodata = nodata
        self.nrows, self.ncols = self.grid.shape

    def sample(self, lon: float, lat: float) -> float | None:
        col = (lon - self.xll) / self.cellsize
        row = (self.yll + (self.nrows - 1) * self.cellsize - lat) / self.cellsize
        ci = int(round(col))
        ri = int(round(row))
        if ci < 0 or ci >= self.ncols or ri < 0 or ri >= self.nrows:
            return None
        v = self.grid[ri, ci]
        return None if (np.isnan(v) or v == self.nodata) else float(v)


def read_asc(text: str) -> RasterGrid:
    header = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        parts = line.split()
        key = parts[0].lower()
        if key in ("ncols", "nrows", "xllcorner", "yllcorner", "cellsize", "nodata_value"):
            header[key] = float(parts[1])
            i += 1
        elif key == "nodata":
            header["nodata_value"] = float(parts[1])
            i += 1
        else:
            break
    data = np.loadtxt(lines[i:], dtype=float)
    return RasterGrid(
        data,
        header.get("xllcorner", 0.0),
        header.get("yllcorner", 0.0),
        header.get("cellsize", 1.0),
        header.get("nodata_value", -9999.0),
    )


def read_raster(source) -> RasterGrid:
    if isinstance(source, (str, os.PathLike)) and str(source).lower().endswith((".asc", ".txt")):
        return read_asc(Path(source).read_text(encoding="utf-8"))
    if isinstance(source, str) and source.lower().endswith(".asc"):
        import httpx

        return read_asc(httpx.get(source, timeout=60, headers={"User-Agent": "3D-BIPV-Assessment/0.1"}).text)
    try:
        import tifffile

        arr = tifffile.imread(source)
        return RasterGrid(arr, 0.0, 0.0, 1.0)
    except Exception as exc:
        raise ValueError(f"unsupported raster source: {source}") from exc


class CopernicusDemProvider(ElevationProvider):
    def __init__(self, west: float, south: float, east: float, north: float):
        self.params = {"demtype": DEM_TYPE, "west": west, "south": south, "east": east, "north": north, "outputFormat": "AAIGrid"}
        self._grid = None

    def _load(self) -> RasterGrid | None:
        cached = _cache_get({"provider": "copernicus_dem", **self.params})
        if cached is not None:
            try:
                self._grid = RasterGrid(**cached)
                return self._grid
            except Exception:
                pass
        try:
            import httpx

            resp = httpx.get(DEM_URL, params=self.params, timeout=60, headers={"User-Agent": "3D-BIPV-Assessment/0.1"})
            resp.raise_for_status()
            grid = read_asc(resp.text)
        except Exception:
            return None
        _cache_put(
            {"provider": "copernicus_dem", **self.params},
            {"grid": grid.grid.tolist(), "xll": grid.xll, "yll": grid.yll, "cellsize": grid.cellsize, "nodata": grid.nodata},
        )
        self._grid = grid
        return grid

    def sample(self, lon: float, lat: float) -> float | None:
        if self._grid is None:
            self._load()
        if self._grid is None:
            return None
        return self._grid.sample(lon, lat)


class DsmProvider(ElevationProvider):
    def __init__(self, source):
        self.grid = read_raster(source) if not isinstance(source, RasterGrid) else source

    def sample(self, lon: float, lat: float) -> float | None:
        return self.grid.sample(lon, lat)


def read_points_xyz(path) -> np.ndarray:
    return np.loadtxt(path, dtype=float)[:, :3]


def read_points_las(path) -> np.ndarray:
    import laspy

    las = laspy.read(path)
    x = np.asarray(las.x, dtype=float)
    y = np.asarray(las.y, dtype=float)
    z = np.asarray(las.z, dtype=float)
    return np.column_stack([x, y, z])


def ground_z_percentile(points: np.ndarray, percentile: float = 5.0) -> float:
    if points.size == 0:
        return 0.0
    return float(np.percentile(points[:, 2], percentile))


def roof_height_percentile(points: np.ndarray, ground: float, percentile: float = 95.0) -> float:
    if points.size == 0:
        return 0.0
    roof = float(np.percentile(points[:, 2], percentile))
    return max(0.0, roof - ground)


def ransac_plane(points: np.ndarray, n_iter: int = 200, dist_thresh: float = 0.5, min_inliers: int = 15):
    best = None
    best_count = -1
    rng = np.random.default_rng(0)
    n = len(points)
    if n < 3:
        return None
    for _ in range(n_iter):
        idx = rng.choice(n, 3, replace=False)
        p1, p2, p3 = points[idx]
        v1 = p2 - p1
        v2 = p3 - p1
        normal = np.cross(v1, v2)
        norm = np.linalg.norm(normal)
        if norm < 1e-9:
            continue
        normal = normal / norm
        d = -float(normal.dot(p1))
        dists = np.abs(points.dot(normal) + d)
        inliers = points[dists < dist_thresh]
        if len(inliers) > best_count:
            best_count = len(inliers)
            best = (normal, d, inliers)
    if best is None or best_count < min_inliers:
        return None
    return best


def plane_metrics(normal) -> tuple[float, float]:
    nx, ny, nz = normal
    if nz < 0:
        nx, ny, nz = -nx, -ny, -nz
    nz = max(-1.0, min(1.0, nz))
    slope = math.degrees(math.acos(nz))
    az = math.degrees(math.atan2(nx, ny)) % 360.0
    return slope, az


def extract_planes(points: np.ndarray, max_planes: int = 4, dist_thresh: float = 0.5, min_inliers: int = 15) -> list[dict]:
    planes = []
    remaining = points.copy()
    for _ in range(max_planes):
        res = ransac_plane(remaining, dist_thresh=dist_thresh, min_inliers=min_inliers)
        if res is None:
            break
        normal, d, inliers = res
        slope, az = plane_metrics(normal)
        planes.append({"normal": normal.tolist(), "d": d, "slope_deg": slope, "azimuth_deg": az, "n_points": len(inliers)})
        dists = np.abs(remaining.dot(normal) + d)
        remaining = remaining[dists >= dist_thresh]
        if len(remaining) < min_inliers:
            break
    return planes


def clip_points_to_footprint(points_utm: np.ndarray, polygon) -> np.ndarray:
    from shapely.geometry import Point

    if points_utm.size == 0:
        return points_utm
    mask = [polygon.contains(Point(x, y)) or polygon.boundary.distance(Point(x, y)) < 1e-6 for x, y in points_utm[:, :2]]
    return points_utm[np.array(mask, dtype=bool)]


def _plane_polygon(points_utm: np.ndarray, footprint_polygon) -> list | None:
    from shapely.geometry import MultiPoint

    if points_utm.size == 0:
        return None
    hull = MultiPoint([(x, y) for x, y in points_utm[:, :2]]).convex_hull
    clipped = hull.intersection(footprint_polygon)
    if clipped.is_empty:
        return None
    from shapely.geometry import Polygon

    polys = [clipped] if clipped.geom_type == "Polygon" else list(clipped.geoms)
    best = max((p for p in polys if p.geom_type == "Polygon"), key=lambda p: p.area, default=None)
    if best is None:
        return None
    ring = list(best.exterior.coords)
    return [[x, y] for x, y in ring[:-1]]


def lidar_profile(buildings: list[dict], points_utm: np.ndarray) -> dict:
    from shapely.ops import transform as shapely_transform
    from pyproj import Transformer

    profiles = {}
    for b in buildings:
        geom = b["geometry"]
        fwd, _, epsg = _transformer_for_building(b)
        foot = shapely_transform(fwd.transform, geom)
        if foot.geom_type != "Polygon":
            continue
        pts = clip_points_to_footprint(points_utm, foot)
        if pts.size < 30:
            continue
        gz = ground_z_percentile(pts, 5.0)
        height = roof_height_percentile(pts, gz, 95.0)
        planes = extract_planes(pts, max_planes=4)
        roof_planes = []
        for pl in planes:
            inliers = _plane_inliers(points_utm, pl)
            poly = _plane_polygon(inliers, foot)
            if poly:
                pl["polygon_utm"] = poly
                roof_planes.append(pl)
        profiles[b["building_id"]] = {
            "ground_z": round(gz, 2),
            "height_m": round(height, 2),
            "height_source": "lidar",
            "roof_source": "lidar_plane_fit" if roof_planes else "lidar_height_only",
            "confidence": "high" if roof_planes else "medium",
            "roof_planes": roof_planes,
        }
    return profiles


def _plane_inliers(points_utm: np.ndarray, plane: dict) -> np.ndarray:
    n = np.array(plane["normal"], dtype=float)
    d = float(plane["d"])
    dists = np.abs(points_utm[:, :3].dot(n) + d)
    return points_utm[dists < 0.5]


def _transformer_for_building(b):
    from .geometry import utm_epsg

    lon = b.get("_lon") or b.get("geometry").centroid.x
    lat = b.get("_lat") or b.get("geometry").centroid.y
    epsg = utm_epsg(lon, lat)
    from pyproj import Transformer

    return Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True), None, epsg


def fallback_profiles(buildings: list[dict]) -> dict:
    profiles = {}
    for b in buildings:
        shape = (b.get("roof_shape") or "").strip().lower()
        profiles[b["building_id"]] = {
            "ground_z": 0.0,
            "height_m": float(b.get("height_m", 0.0)),
            "height_source": b.get("height_source", "default"),
            "roof_source": "osm_tags" if shape in ROOF_SHAPES else "unknown",
            "confidence": "low",
            "roof_planes": [],
        }
    return profiles


def elevation_profile(buildings, dem_provider=None, dsm_provider=None, points_utm=None) -> dict:
    base = fallback_profiles(buildings)
    if points_utm is not None and len(points_utm):
        lidar = lidar_profile(buildings, points_utm)
        for bid, prof in lidar.items():
            base[bid] = prof
    if dem_provider is not None or dsm_provider is not None:
        for b in buildings:
            bid = b["building_id"]
            centroid = b["geometry"].centroid
            lon, lat = centroid.x, centroid.y
            if dsm_provider is not None and dem_provider is not None:
                dsm = dsm_provider.sample(lon, lat)
                dtm = dem_provider.sample(lon, lat)
                if dsm is not None and dtm is not None and dsm > dtm:
                    base[bid]["height_m"] = round(dsm - dtm, 2)
                    base[bid]["height_source"] = "dsm"
                    base[bid]["roof_source"] = "dsm_inferred"
                    base[bid]["confidence"] = "medium"
            elif dem_provider is not None:
                gz = dem_provider.sample(lon, lat)
                if gz is not None:
                    base[bid]["ground_z"] = round(gz, 2)
                    base[bid]["confidence"] = "low"
    return base
