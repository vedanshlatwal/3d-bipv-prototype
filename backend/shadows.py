from __future__ import annotations

import math

from shapely import get_coordinates
from shapely.geometry import LineString
from shapely.strtree import STRtree

MAX_RAY_LEN = 400.0


class ShadowCaster:
    def __init__(self, footprints: list[tuple], sun_e: float, sun_n: float, sun_u: float):
        self.polys = [f[0] for f in footprints]
        self.heights = [f[1] for f in footprints]
        self.ids = [f[2] for f in footprints]
        self.tree = STRtree(self.polys) if self.polys else None
        horiz = math.hypot(sun_e, sun_n)
        if horiz < 1e-9 or sun_u <= 0:
            self.invalid = True
            self.slope = 0.0
            self.far = (0.0, 0.0)
        else:
            self.invalid = False
            self.slope = sun_u / horiz
            self.far = (sun_e / horiz * MAX_RAY_LEN, sun_n / horiz * MAX_RAY_LEN)

    def fraction(self, surface: dict) -> float:
        if self.invalid or not self.tree:
            return 1.0
        sx, sy = self.far
        unshaded = 0
        total = 0
        for px, py, pz in surface["samples"]:
            total += 1
            line = LineString([(px, py), (px + sx, py + sy)])
            blocked = False
            for idx in self.tree.query(line):
                if self.ids[idx] == surface["building_id"]:
                    continue
                inter = line.intersection(self.polys[idx])
                if inter.is_empty:
                    continue
                s = _nearest(px, py, inter)
                if s is None or s < 1e-6:
                    continue
                if pz + s * self.slope <= self.heights[idx]:
                    blocked = True
                    break
            if not blocked:
                unshaded += 1
        return unshaded / total if total else 1.0


def _nearest(px: float, py: float, inter) -> float | None:
    coords = get_coordinates(inter)
    if coords.size == 0:
        return None
    dx = coords[:, 0] - px
    dy = coords[:, 1] - py
    return float((dx * dx + dy * dy).min() ** 0.5)
