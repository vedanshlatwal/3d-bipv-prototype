from __future__ import annotations

import numpy as np
from shapely.geometry import Polygon
from shapely.ops import transform as shapely_transform

from backend import elevation, geometry as g

LON, LAT = 77.2090, 28.6139

RECT = Polygon(
    [
        (77.20900, 28.61390),
        (77.20940, 28.61390),
        (77.20940, 28.61410),
        (77.20900, 28.61410),
        (77.20900, 28.61390),
    ]
)


def make_building(geom=RECT, height=12.0):
    return {
        "building_id": "way/1",
        "geometry": geom,
        "height_m": height,
        "height_source": "osm",
        "building_type": "yes",
        "roof_shape": "",
        "roof_height": None,
        "roof_levels": None,
        "roof_orientation": None,
        "roof_angle": None,
    }


def _sloped_points(ny_sign, n=40):
    rng = np.random.default_rng(2)
    c, s = 0.94, 0.34
    ny = ny_sign * s
    pts = []
    for _ in range(n):
        x = rng.uniform(-2, 2)
        y = rng.uniform(1, 3) * (1.0 if ny < 0 else -1.0)
        z = (-ny / c) * y + rng.normal(0, 0.02)
        pts.append([x, y, z])
    return np.array(pts)


def test_plane_metrics_slope_azimuth():
    slope, az = elevation.plane_metrics(np.array([0.0, -0.34, 0.94]))
    assert 18 < slope < 22
    assert 178 < az < 182
    slope, az = elevation.plane_metrics(np.array([0.0, 0.34, 0.94]))
    assert 18 < slope < 22
    assert az < 2 or az > 358


def test_ransac_recovers_gabled_roof_planes():
    points = np.vstack([_sloped_points(-1), _sloped_points(+1)])
    planes = elevation.extract_planes(points, max_planes=4, dist_thresh=0.1, min_inliers=10)
    assert len(planes) >= 2
    azimuths = [p["azimuth_deg"] for p in planes]
    assert any(a <= 5 or a >= 355 for a in azimuths)
    assert any(175 <= a <= 185 for a in azimuths)
    assert all(15 < p["slope_deg"] < 25 for p in planes)


def test_ground_and_roof_percentiles():
    pts = np.array([[0, 0, 200.0], [1, 1, 201.0], [2, 2, 202.0], [3, 3, 210.0], [4, 4, 211.0]])
    gz = elevation.ground_z_percentile(pts, 5.0)
    assert abs(gz - 200.0) < 0.3
    h = elevation.roof_height_percentile(pts, gz, 95.0)
    assert abs(h - 10.0) < 1.0


def test_read_asc_parse():
    asc = "ncols 3\nnrows 2\nxllcorner 10.0\nyllcorner 20.0\ncellsize 1.0\nNODATA_value -9999\n0 1 2\n3 4 5\n"
    grid = elevation.read_asc(asc)
    assert grid.ncols == 3 and grid.nrows == 2
    assert grid.sample(10.0, 21.0) == 0.0
    assert grid.sample(12.0, 21.0) == 2.0
    assert grid.sample(10.0, 20.0) == 3.0


def test_fallback_profiles():
    profiles = elevation.fallback_profiles([make_building()])
    prof = profiles["way/1"]
    assert prof["height_m"] == 12.0
    assert prof["confidence"] == "low"
    assert prof["roof_source"] == "unknown"
    assert prof["roof_planes"] == []


def test_geometry_height_override_and_ground_z():
    profile = {
        "ground_z": 150.0,
        "height_m": 20.0,
        "height_source": "lidar",
        "roof_source": "lidar_height_only",
        "confidence": "medium",
        "roof_planes": [],
    }
    surfaces, _ = g.derive_surfaces([make_building()], LON, LAT, elevation={"way/1": profile})
    assert surfaces
    for s in surfaces:
        assert s["geometry_source"] == "lidar"
        assert s["confidence"] == "medium"
        assert abs(s["ground_z_m"] - 150.0) < 0.01
        for coord in s["geometry"]:
            assert coord[2] >= 150.0  # lifted above ground


def test_geometry_roof_from_planes():
    building = make_building()
    fwd, _, _ = g._transformer(LON, LAT)
    p_utm = shapely_transform(fwd.transform, RECT)
    ring = list(p_utm.exterior.coords)[:-1]
    xs = sorted(v[0] for v in ring)
    ys = sorted(v[1] for v in ring)
    x0, x1 = xs[0], xs[1]
    y0, y1 = ys[0], ys[1]
    ymid = (y0 + y1) / 2

    ground = 150.0
    ridge = 3.0

    a1 = np.array([x0, y0, ground])
    b1 = np.array([x1, y0, ground])
    c1 = np.array([x0, ymid, ground + ridge])
    n1 = np.cross(b1 - a1, c1 - a1)
    n1 = n1 / np.linalg.norm(n1)
    d1 = -float(n1.dot(a1))

    a2 = np.array([x0, ymid, ground + ridge])
    b2 = np.array([x1, ymid, ground + ridge])
    c2 = np.array([x0, y1, ground])
    n2 = np.cross(b2 - a2, c2 - a2)
    n2 = n2 / np.linalg.norm(n2)
    d2 = -float(n2.dot(a2))

    profile = {
        "ground_z": ground,
        "height_m": ridge,
        "height_source": "lidar",
        "roof_source": "lidar_plane_fit",
        "confidence": "high",
        "roof_planes": [
            {"normal": n1.tolist(), "d": d1, "slope_deg": 20.0, "azimuth_deg": 180.0, "polygon_utm": [[x0, y0], [x1, y0], [x1, ymid], [x0, ymid]]},
            {"normal": n2.tolist(), "d": d2, "slope_deg": 20.0, "azimuth_deg": 0.0, "polygon_utm": [[x0, ymid], [x1, ymid], [x1, y1], [x0, y1]]},
        ],
    }

    surfaces, _ = g.derive_surfaces([building], LON, LAT, elevation={"way/1": profile})
    roofs = [s for s in surfaces if s["surface_type"] == "roof"]
    walls = [s for s in surfaces if s["surface_type"] != "roof"]
    assert len(roofs) == 2
    assert len(walls) == 4
    assert all(r["tilt_deg"] > 0 for r in roofs)
    assert all(s["confidence"] == "high" for s in surfaces)
    assert all(abs(s["ground_z_m"] - ground) < 0.01 for s in surfaces)
