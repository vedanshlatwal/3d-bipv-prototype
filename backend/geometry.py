from __future__ import annotations

import math

from pyproj import Transformer
from shapely.geometry import Point, Polygon, shape as shapely_shape
from shapely.ops import transform as shapely_transform

FLOOR_HEIGHT = 3.0
DEFAULT_ROOF_HEIGHT = 3.0
ROOF_SHAPES = {"flat", "gabled", "hipped", "pyramidal", "skillion"}

SKELETON_STEPS = 5
MIN_SKELETON_OFFSET = 0.15

DEFAULT_UNTAGGED_ROOF_SHAPE = "hipped"
DEFAULT_UNTAGGED_ROOF_HEIGHT = 2.5


def utm_epsg(lon: float, lat: float) -> int:
    zone = int((lon + 180.0) // 6) + 1
    north = lat >= 0
    return 32600 + zone if north else 32700 + zone


def _transformer(lon: float, lat: float) -> tuple[Transformer, Transformer, int]:
    epsg = utm_epsg(lon, lat)
    fwd = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
    back = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)
    return fwd, back, epsg


def sun_vector_enu(azimuth_deg: float, elevation_deg: float) -> tuple[float, float, float]:
    el = math.radians(elevation_deg)
    az = math.radians(azimuth_deg)
    return (
        math.cos(el) * math.sin(az),
        math.cos(el) * math.cos(az),
        math.sin(el),
    )


def buildings_from_geojson(fc: dict) -> list[dict]:
    out = []
    for feat in fc.get("features", []):
        props = feat.get("properties", {})
        try:
            geom = shapely_shape(feat["geometry"])
        except Exception:
            continue
        if geom.is_empty:
            continue
        out.append(
            {
                "building_id": str(props.get("building_id", feat.get("id", "bld"))),
                "geometry": geom,
                "height_m": float(props.get("height_m", 10.0)),
                "height_source": props.get("height_source", "default"),
                "building_type": props.get("building_type", ""),
                "roof_shape": props.get("roof_shape", ""),
                "roof_height": props.get("roof_height"),
                "roof_levels": props.get("roof_levels"),
                "roof_orientation": props.get("roof_orientation"),
                "roof_angle": props.get("roof_angle"),
            }
        )
    return out


def _azimuth(nx: float, ny: float) -> float:
    az = math.degrees(math.atan2(nx, ny))
    if az < 0:
        az += 360.0
    return az


def _classify(azimuth: float) -> str:
    if 45 <= azimuth < 135:
        return "east_facade"
    if 135 <= azimuth < 225:
        return "south_facade"
    if 225 <= azimuth < 315:
        return "west_facade"
    return "north_facade"


# ---- 3D face helpers -------------------------------------------------------

def _face_normal(verts: list[tuple]) -> tuple[float, float, float]:
    nx = ny = nz = 0.0
    n = len(verts)
    for i in range(n):
        x1, y1, z1 = verts[i]
        x2, y2, z2 = verts[(i + 1) % n]
        nx += (y1 - y2) * (z1 + z2)
        ny += (z1 - z2) * (x1 + x2)
        nz += (x1 - x2) * (y1 + y2)
    m = math.hypot(nx, ny, nz)
    if m < 1e-12:
        return (0.0, 0.0, 1.0)
    return (nx / m, ny / m, nz / m)


def _polygon_area(verts: list[tuple]) -> float:
    n = len(verts)
    if n < 3:
        return 0.0
    ax = ay = az = 0.0
    for i in range(n):
        x1, y1, z1 = verts[i]
        x2, y2, z2 = verts[(i + 1) % n]
        ax += y1 * z2 - z1 * y2
        ay += z1 * x2 - x1 * z2
        az += x1 * y2 - y1 * x2
    return 0.5 * math.sqrt(ax * ax + ay * ay + az * az)


def _tilt_azimuth(nx: float, ny: float, nz: float) -> tuple[float, float]:
    nz = max(-1.0, min(1.0, nz))
    tilt = math.degrees(math.acos(nz))
    az = math.degrees(math.atan2(nx, ny)) % 360.0
    return tilt, az


# ---- triangulation ----------------------------------------------------------

def _planar_project(verts: list[tuple]) -> list[tuple[float, float]]:
    normal = _face_normal(verts)
    nx, ny, nz = normal
    helper = (1.0, 0.0, 0.0) if abs(nx) < 0.9 else (0.0, 1.0, 0.0)
    ux = helper[1] * nz - helper[2] * ny
    uy = helper[2] * nx - helper[0] * nz
    uz = helper[0] * ny - helper[1] * nx
    ul = math.hypot(math.hypot(ux, uy), uz) or 1.0
    ux, uy, uz = ux / ul, uy / ul, uz / ul
    vx = ny * uz - nz * uy
    vy = nz * ux - nx * uz
    vz = nx * uy - ny * ux
    ox, oy, oz = verts[0]
    out = []
    for x, y, z in verts:
        dx, dy, dz = x - ox, y - oy, z - oz
        out.append((dx * ux + dy * uy + dz * uz, dx * vx + dy * vy + dz * vz))
    return out


def _signed_area_2d(pts: list[tuple[float, float]]) -> float:
    area = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return area * 0.5


def _point_in_triangle_2d(p, a, b, c) -> bool:
    def sign(p1, p2, p3):
        return (p1[0] - p3[0]) * (p2[1] - p3[1]) - (p2[0] - p3[0]) * (p1[1] - p3[1])

    d1, d2, d3 = sign(p, a, b), sign(p, b, c), sign(p, c, a)
    has_neg = d1 < 0 or d2 < 0 or d3 < 0
    has_pos = d1 > 0 or d2 > 0 or d3 > 0
    return not (has_neg and has_pos)


def _ear_clip_2d(pts: list[tuple[float, float]]) -> list[tuple[int, int, int]]:
    n = len(pts)
    if n < 3:
        return []
    if n == 3:
        return [(0, 1, 2)]

    idx = list(range(n)) if _signed_area_2d(pts) >= 0 else list(range(n))[::-1]
    triangles = []
    guard = 0
    while len(idx) > 3 and guard < 20 * n:
        guard += 1
        ear_found = False
        for i in range(len(idx)):
            ip, ic, inx = idx[i - 1], idx[i], idx[(i + 1) % len(idx)]
            a, b, c = pts[ip], pts[ic], pts[inx]
            cross = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
            if cross <= 1e-12:
                continue
            if any(j not in (ip, ic, inx) and _point_in_triangle_2d(pts[j], a, b, c) for j in idx):
                continue
            triangles.append((ip, ic, inx))
            idx.pop(i)
            ear_found = True
            break
        if not ear_found:
            break
    if len(idx) >= 3:
        for i in range(1, len(idx) - 1):
            triangles.append((idx[0], idx[i], idx[i + 1]))
    return triangles


def _sample_face(verts: list[tuple], n: int = 5) -> list[tuple]:
    if len(verts) < 3:
        return []
    tris = [(0, 1, 2)] if len(verts) == 3 else _ear_clip_2d(_planar_project(verts))
    pts = []
    for i0, i1, i2 in tris:
        a, b, c = verts[i0], verts[i1], verts[i2]
        for i in range(n):
            for j in range(n):
                u = (i + 0.5) / n
                v = (j + 0.5) / n
                if u + v > 1.0:
                    continue
                w = 1.0 - u - v
                pts.append(
                    (
                        w * a[0] + u * b[0] + v * c[0],
                        w * a[1] + u * b[1] + v * c[1],
                        w * a[2] + u * b[2] + v * c[2],
                    )
                )
    return pts


def _outward_normal(x1, y1, x2, y2, ccw: bool) -> tuple[float, float]:
    dx = x2 - x1
    dy = y2 - y1
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return (0.0, 0.0)
    if ccw:
        return (dy / length, -dx / length)
    return (-dy / length, dx / length)


def _is_rectangle(verts: list[tuple]) -> bool:
    if len(verts) != 4:
        return False
    for i in range(4):
        x0, y0 = verts[i]
        x1, y1 = verts[(i + 1) % 4]
        x2, y2 = verts[(i + 2) % 4]
        ax, ay = x1 - x0, y1 - y0
        bx, by = x2 - x1, y2 - y1
        la = math.hypot(ax, ay)
        lb = math.hypot(bx, by)
        if la < 1e-6 or lb < 1e-6:
            return False
        if abs((ax * bx + ay * by) / (la * lb)) > 0.15:
            return False
    return True


def _resolve_roof(b: dict, height: float) -> tuple[str, float, float, str]:
    roof_shape_tag = (b.get("roof_shape") or "").strip().lower()

    if roof_shape_tag == "flat":
        return "flat", 0.0, height, "detailed"

    if roof_shape_tag == "" or roof_shape_tag not in ROOF_SHAPES:
        if DEFAULT_UNTAGGED_ROOF_SHAPE == "flat":
            return "flat", 0.0, height, "estimated"
        roof_h = min(DEFAULT_UNTAGGED_ROOF_HEIGHT, height)
        eave = height - roof_h
        return DEFAULT_UNTAGGED_ROOF_SHAPE, roof_h, eave, "estimated"

    roof_h = b.get("roof_height")
    if roof_h is None:
        levels = b.get("roof_levels")
        if levels is not None:
            try:
                roof_h = float(levels) * FLOOR_HEIGHT
            except (TypeError, ValueError):
                roof_h = None
    if roof_h is None or float(roof_h) <= 0:
        roof_h = DEFAULT_ROOF_HEIGHT
    roof_h = min(float(roof_h), height)
    eave = height - roof_h
    return roof_shape_tag, roof_h, eave, "detailed"


# ---- surface emission ------------------------------------------------------

def _emit(surfaces, bid, b, back, quality, verts, normal, kind):
    if normal is None:
        normal = _face_normal(verts)
        if normal[2] < 0:
            normal = (-normal[0], -normal[1], -normal[2])
    area = _polygon_area(verts)
    if area < 1e-9:
        return
    tilt, az = _tilt_azimuth(*normal)
    surface_type = "roof" if kind == "roof" else _classify(az)
    geometry = [list(back.transform(x, y, z)) for x, y, z in verts]
    idx = len(surfaces)
    surfaces.append(
        {
            "surface_id": f"{bid}__{'roof' if kind == 'roof' else 'facade'}_{idx}",
            "building_id": bid,
            "surface_type": surface_type,
            "area_m2": round(area, 3),
            "azimuth_deg": round(az, 2),
            "tilt_deg": round(tilt, 2),
            "normal": {"east": round(normal[0], 6), "north": round(normal[1], 6), "up": round(normal[2], 6)},
            "height_m": max(z for _, _, z in verts),
            "geometry": geometry,
            "samples": _sample_face(verts),
            "building_type": b.get("building_type", ""),
            "height_source": b.get("height_source", "default"),
            "geometry_quality": quality,
        }
    )


def _emit_wall(surfaces, bid, b, back, quality, x1, y1, x2, y2, z0, z1, nx, ny):
    verts = [(x1, y1, z0), (x2, y2, z0), (x2, y2, z1), (x1, y1, z1)]
    _emit(surfaces, bid, b, back, quality, verts, (nx, ny, 0.0), "wall")


# ---- roof builders ---------------------------------------------------------

def _build_flat(surfaces, bid, b, back, quality, verts, ccw, height):
    for i in range(len(verts)):
        x1, y1 = verts[i]
        x2, y2 = verts[(i + 1) % len(verts)]
        nx, ny = _outward_normal(x1, y1, x2, y2, ccw)
        _emit_wall(surfaces, bid, b, back, quality, x1, y1, x2, y2, 0.0, height, nx, ny)
    roof_verts = [(x, y, height) for x, y in verts]
    _emit(surfaces, bid, b, back, quality, roof_verts, (0.0, 0.0, 1.0), "roof")


def _edge_info(verts):
    n = len(verts)
    edges = []
    for i in range(n):
        x1, y1 = verts[i]
        x2, y2 = verts[(i + 1) % n]
        edges.append((x1, y1, x2, y2, math.hypot(x2 - x1, y2 - y1)))
    return edges


def _edge_mid(edge):
    return ((edge[0] + edge[2]) / 2, (edge[1] + edge[3]) / 2)


def _order_planar(verts):
    cx = sum(v[0] for v in verts) / len(verts)
    cy = sum(v[1] for v in verts) / len(verts)
    return sorted(verts, key=lambda v: math.atan2(v[1] - cy, v[0] - cx))


def _build_gabled(surfaces, bid, b, back, quality, verts, ccw, eave, roof_h):
    edges = _edge_info(verts)
    long_axis = [0, 2] if edges[0][4] >= edges[1][4] else [1, 3]
    short_axis = [1, 3] if long_axis == [0, 2] else [0, 2]
    ridge_start = _edge_mid(edges[short_axis[0]])
    ridge_end = _edge_mid(edges[short_axis[1]])
    ridge_z = eave + roof_h

    for i in range(4):
        x1, y1, x2, y2, _ = edges[i]
        nx, ny = _outward_normal(x1, y1, x2, y2, ccw)
        _emit_wall(surfaces, bid, b, back, quality, x1, y1, x2, y2, 0.0, eave, nx, ny)
        if i in short_axis:
            peak = ridge_start if i == short_axis[0] else ridge_end
            _emit(surfaces, bid, b, back, quality, [(x1, y1, eave), (x2, y2, eave), (peak[0], peak[1], ridge_z)], (nx, ny, 0.0), "wall")
        else:
            _emit(surfaces, bid, b, back, quality, _order_planar([(x1, y1, eave), (x2, y2, eave), (ridge_start[0], ridge_start[1], ridge_z), (ridge_end[0], ridge_end[1], ridge_z)]), None, "roof")


def _build_hipped(surfaces, bid, b, back, quality, verts, ccw, eave, roof_h):
    edges = _edge_info(verts)
    long_axis = [0, 2] if edges[0][4] >= edges[1][4] else [1, 3]
    short_axis = [1, 3] if long_axis == [0, 2] else [0, 2]
    short_len = edges[short_axis[0]][4]
    hip = min(roof_h, short_len / 2)

    m0 = _edge_mid(edges[short_axis[0]])
    m1 = _edge_mid(edges[short_axis[1]])
    dx = m1[0] - m0[0]
    dy = m1[1] - m0[1]
    dist = math.hypot(dx, dy) or 1.0
    ux, uy = dx / dist, dy / dist
    ridge_start = (m0[0] + ux * hip, m0[1] + uy * hip)
    ridge_end = (m1[0] - ux * hip, m1[1] - uy * hip)
    ridge_z = eave + roof_h

    for i in range(4):
        x1, y1, x2, y2, _ = edges[i]
        nx, ny = _outward_normal(x1, y1, x2, y2, ccw)
        _emit_wall(surfaces, bid, b, back, quality, x1, y1, x2, y2, 0.0, eave, nx, ny)
        if i in long_axis:
            _emit(surfaces, bid, b, back, quality, _order_planar([(x1, y1, eave), (x2, y2, eave), (ridge_start[0], ridge_start[1], ridge_z), (ridge_end[0], ridge_end[1], ridge_z)]), None, "roof")
        else:
            apex = ridge_start if i == short_axis[0] else ridge_end
            _emit(surfaces, bid, b, back, quality, [(x1, y1, eave), (x2, y2, eave), (apex[0], apex[1], ridge_z)], None, "roof")


def _build_skillion(surfaces, bid, b, back, quality, verts, ccw, eave, roof_h):
    edges = _edge_info(verts)
    long_axis = [0, 2] if edges[0][4] >= edges[1][4] else [1, 3]
    short_axis = [1, 3] if long_axis == [0, 2] else [0, 2]
    high_edge = long_axis[1]
    low_edge = long_axis[0]
    ridge_z = eave + roof_h

    for i in range(4):
        x1, y1, x2, y2, _ = edges[i]
        nx, ny = _outward_normal(x1, y1, x2, y2, ccw)
        if i == high_edge:
            _emit_wall(surfaces, bid, b, back, quality, x1, y1, x2, y2, 0.0, ridge_z, nx, ny)
        elif i == low_edge:
            _emit_wall(surfaces, bid, b, back, quality, x1, y1, x2, y2, 0.0, eave, nx, ny)
        else:
            _emit(surfaces, bid, b, back, quality, [(x1, y1, 0.0), (x2, y2, 0.0), (x2, y2, ridge_z), (x1, y1, eave)], (nx, ny, 0.0), "wall")

    lx1, ly1, lx2, ly2, _ = edges[low_edge]
    hx1, hy1, hx2, hy2, _ = edges[high_edge]
    _emit(surfaces, bid, b, back, quality, _order_planar([(lx1, ly1, eave), (lx2, ly2, eave), (hx1, hy1, ridge_z), (hx2, hy2, ridge_z)]), None, "roof")


# ---- generalized pitched roof (any simple polygon, not just rectangles) ---

def _erosion_extinction_distance(poly: Polygon, max_iter: int = 40) -> float:
    minx, miny, maxx, maxy = poly.bounds
    hi = max(maxx - minx, maxy - miny)
    if hi <= 0:
        return 0.0
    lo = 0.0
    for _ in range(max_iter):
        mid = (lo + hi) / 2.0
        if poly.buffer(-mid, join_style=2).is_empty:
            hi = mid
        else:
            lo = mid
    return lo


def _skeleton_rings(poly: Polygon, extinction: float, steps: int, n_pts: int, start_xy):
    rings = []
    for i in range(1, steps + 1):
        d = min(extinction * (i / steps), extinction * 0.999)
        eroded = poly.buffer(-d, join_style=2)
        if eroded.is_empty:
            eroded = poly.buffer(-extinction * 0.999, join_style=2)
        if eroded.geom_type == "MultiPolygon":
            if not eroded.geoms:
                break
            eroded = max(eroded.geoms, key=lambda g: g.area)
        if eroded.is_empty or eroded.geom_type != "Polygon":
            break
        ring = eroded.exterior
        length = ring.length
        if length < 1e-9:
            pt = ring.coords[0]
            rings.append([(pt[0], pt[1])] * n_pts)
            continue
        offset = ring.project(Point(start_xy))
        pts = [
            (lambda p: (p.x, p.y))(ring.interpolate((offset + length * (k / n_pts)) % length))
            for k in range(n_pts)
        ]
        rings.append(pts)
    return rings


def _build_hip_general(surfaces, bid, b, back, quality, verts, ccw, eave, roof_h):
    poly = Polygon(verts)
    if not poly.is_valid:
        poly = poly.buffer(0)
    if poly.is_empty or poly.geom_type != "Polygon":
        _build_flat(surfaces, bid, b, back, "estimated", verts, ccw, eave + roof_h)
        return

    for i in range(len(verts)):
        x1, y1 = verts[i]
        x2, y2 = verts[(i + 1) % len(verts)]
        nx, ny = _outward_normal(x1, y1, x2, y2, ccw)
        _emit_wall(surfaces, bid, b, back, quality, x1, y1, x2, y2, 0.0, eave, nx, ny)

    extinction = _erosion_extinction_distance(poly)
    if extinction < MIN_SKELETON_OFFSET:
        roof_verts = [(x, y, eave) for x, y in verts]
        _emit(surfaces, bid, b, back, "estimated", roof_verts, (0.0, 0.0, 1.0), "roof")
        return

    n_pts = max(len(verts), 3)
    rings = [list(verts)] + _skeleton_rings(poly, extinction, SKELETON_STEPS, n_pts, verts[0])
    if len(rings) < 2:
        roof_verts = [(x, y, eave) for x, y in verts]
        _emit(surfaces, bid, b, back, "estimated", roof_verts, (0.0, 0.0, 1.0), "roof")
        return

    steps = len(rings) - 1
    for k in range(steps):
        z0 = eave + roof_h * min(k / SKELETON_STEPS, 1.0)
        z1 = eave + roof_h * min((k + 1) / SKELETON_STEPS, 1.0)
        ring0, ring1 = rings[k], rings[k + 1]
        m = len(ring0)
        for i in range(m):
            (x00, y00), (x01, y01) = ring0[i], ring0[(i + 1) % m]
            (x10, y10), (x11, y11) = ring1[i], ring1[(i + 1) % m]
            quad = [(x00, y00, z0), (x01, y01, z0), (x11, y11, z1), (x10, y10, z1)]
            _emit(surfaces, bid, b, back, quality, quad, None, "roof")

    top_z = eave + roof_h
    top_ring = rings[-1]
    cap = [(x, y, top_z) for x, y in top_ring]
    _emit(surfaces, bid, b, back, quality, cap, (0.0, 0.0, 1.0), "roof")


def _plane_z(plane: dict, x: float, y: float, ground_z: float) -> float:
    n = plane["normal"]
    if abs(n[2]) < 1e-6:
        return 0.0
    return -((n[0] * x + n[1] * y + plane["d"]) / n[2]) - ground_z


def _build_roof_from_planes(surfaces, bid, b, back, quality, verts, ccw, planes, ground_z):
    roof_z = 0.0
    rel_polys = []
    for pl in planes:
        poly = pl.get("polygon_utm")
        if not poly or len(poly) < 3:
            continue
        zs = [_plane_z(pl, x, y, ground_z) for x, y in poly]
        roof_z = max(roof_z, max(zs))
        rel_polys.append((pl, zs))

    for i in range(len(verts)):
        x1, y1 = verts[i]
        x2, y2 = verts[(i + 1) % len(verts)]
        nx, ny = _outward_normal(x1, y1, x2, y2, ccw)
        _emit_wall(surfaces, bid, b, back, quality, x1, y1, x2, y2, 0.0, max(0.0, roof_z), nx, ny)

    for pl, zs in rel_polys:
        poly = pl["polygon_utm"]
        verts3d = [(poly[k][0], poly[k][1], zs[k]) for k in range(len(poly))]
        normal = tuple(pl["normal"])
        _emit(surfaces, bid, b, back, quality, verts3d, normal, "roof")


# ---- entry points ----------------------------------------------------------

def derive_surfaces(buildings: list[dict], lon: float, lat: float, elevation: dict | None = None) -> tuple[list[dict], list[tuple]]:
    fwd, back, _ = _transformer(lon, lat)
    surfaces: list[dict] = []
    footprints: list[tuple] = []

    for b in buildings:
        geom = b["geometry"]
        polys = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
        height = b["height_m"]
        bid = b["building_id"]
        for poly in polys:
            if poly.is_empty:
                continue
            p_utm = shapely_transform(fwd.transform, poly)
            if not p_utm.is_valid:
                p_utm = p_utm.buffer(0)
            if p_utm.geom_type != "Polygon" or p_utm.is_empty:
                continue
            _add_surfaces(surfaces, footprints, b, p_utm, height, back, bid, elevation)

    return surfaces, footprints


def _add_surfaces(surfaces, footprints, b, p_utm, height, back, bid, elevation=None):
    profile = elevation.get(bid) if elevation else None
    ground_z = float(profile.get("ground_z", 0.0)) if profile else 0.0
    geometry_source = (profile.get("height_source") if profile else b.get("height_source", "default"))
    confidence = (profile.get("confidence") if profile else "low")
    roof_planes = (profile.get("roof_planes") or []) if profile else []
    if profile and profile.get("height_m"):
        height = float(profile["height_m"])

    ext = p_utm.exterior
    ring = list(ext.coords)
    ccw = ext.is_ccw
    verts = ring[:-1]

    start = len(surfaces)

    if roof_planes:
        _build_roof_from_planes(surfaces, bid, b, back, "detailed" if confidence == "high" else "estimated", verts, ccw, roof_planes, ground_z)
    else:
        roof_shape, roof_h, eave, quality = _resolve_roof(b, height)
        is_rect = _is_rectangle(verts)

        if roof_shape == "flat":
            _build_flat(surfaces, bid, b, back, quality, verts, ccw, height)
        elif roof_shape == "gabled" and is_rect:
            _build_gabled(surfaces, bid, b, back, quality, verts, ccw, eave, roof_h)
        elif roof_shape == "hipped" and is_rect:
            _build_hipped(surfaces, bid, b, back, quality, verts, ccw, eave, roof_h)
        elif roof_shape == "skillion" and is_rect:
            _build_skillion(surfaces, bid, b, back, quality, verts, ccw, eave, roof_h)
        elif roof_shape in ("gabled", "hipped", "pyramidal", "skillion"):
            _build_hip_general(surfaces, bid, b, back, quality, verts, ccw, eave, roof_h)
        else:
            _build_flat(surfaces, bid, b, back, quality, verts, ccw, height)

    for s in surfaces[start:]:
        s["ground_z_m"] = round(ground_z, 2)
        s["geometry_source"] = geometry_source
        s["confidence"] = confidence
        if ground_z:
            s["geometry"] = [[lon_alt[0], lon_alt[1], lon_alt[2] + ground_z] for lon_alt in s["geometry"]]
            s["height_m"] = round(s["height_m"] + ground_z, 3)
            s["samples"] = [(x, y, z + ground_z) for x, y, z in s["samples"]]

    footprints.append((p_utm, height, bid))
