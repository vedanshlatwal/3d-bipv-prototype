from __future__ import annotations

from shapely.geometry import Polygon

from backend import geometry as g

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

LSHAPE = Polygon(
    [
        (77.20900, 28.61390),
        (77.20930, 28.61390),
        (77.20930, 28.61400),
        (77.20910, 28.61400),
        (77.20910, 28.61410),
        (77.20900, 28.61410),
        (77.20900, 28.61390),
    ]
)


def make_building(geom, shape="", roof_h=None):
    return {
        "building_id": "b1",
        "geometry": geom,
        "height_m": 12.0,
        "height_source": "osm",
        "building_type": "yes",
        "roof_shape": shape,
        "roof_height": roof_h,
        "roof_levels": None,
        "roof_orientation": None,
        "roof_angle": None,
    }


def roofs_and_walls(building):
    surfaces, _ = g.derive_surfaces([building], LON, LAT)
    roofs = [s for s in surfaces if s["surface_type"] == "roof"]
    walls = [s for s in surfaces if s["surface_type"] != "roof"]
    return surfaces, roofs, walls


def test_footprint_preserved_irregular():
    building = make_building(LSHAPE)
    surfaces, roofs, walls = roofs_and_walls(building)
    # L-shape: 6 edges -> 6 walls preserved; untagged defaults to a pitched (hipped) roof
    assert len(walls) == 6
    assert all(w["area_m2"] > 0 for w in walls)
    assert len(roofs) > 0
    assert all(r["area_m2"] > 0 for r in roofs)


def test_flat_roof_explicit_is_detailed():
    building = make_building(RECT, "flat")
    surfaces, roofs, walls = roofs_and_walls(building)
    assert roofs[0]["geometry_quality"] == "detailed"
    assert roofs[0]["tilt_deg"] == 0.0
    assert len(walls) == 4


def test_no_roof_info_is_estimated():
    building = make_building(RECT, "")
    _, roofs, _ = roofs_and_walls(building)
    assert roofs[0]["geometry_quality"] == "estimated"


def test_unsupported_roof_shape_is_estimated():
    building = make_building(RECT, "dome")
    _, roofs, _ = roofs_and_walls(building)
    assert all(r["geometry_quality"] == "estimated" for r in roofs)


def test_gabled_roof_has_two_slopes_and_gables():
    building = make_building(RECT, "gabled", roof_h=3.0)
    surfaces, roofs, walls = roofs_and_walls(building)
    assert len(roofs) == 2
    for roof in roofs:
        assert roof["tilt_deg"] > 0 and roof["tilt_deg"] < 60
        assert roof["area_m2"] > 0
    # 6 wall-like faces: 4 rectangles (to eave) + 2 gable-end triangles
    assert len(walls) == 6
    assert all(w["geometry_quality"] == "detailed" for w in walls)
    assert all(r["geometry_quality"] == "detailed" for r in roofs)


def test_hipped_roof_has_four_slopes():
    building = make_building(RECT, "hipped", roof_h=3.0)
    _, roofs, walls = roofs_and_walls(building)
    assert len(roofs) == 4
    assert all(r["area_m2"] > 0 for r in roofs)
    assert all(r["geometry_quality"] == "detailed" for r in roofs)
    assert len(walls) == 4


def test_pyramidal_roof_is_pitched():
    building = make_building(RECT, "pyramidal", roof_h=3.0)
    _, roofs, walls = roofs_and_walls(building)
    assert len(roofs) > 4  # generalized loft produces multiple sloped facets
    assert all(r["area_m2"] > 0 for r in roofs)
    assert all(r["geometry_quality"] == "detailed" for r in roofs)
    assert len(walls) == 4


def test_skillion_roof_single_slope():
    building = make_building(RECT, "skillion", roof_h=3.0)
    _, roofs, walls = roofs_and_walls(building)
    assert len(roofs) == 1
    assert roofs[0]["tilt_deg"] > 0
    assert roofs[0]["area_m2"] > 0
    assert len(walls) == 4


def test_gabled_on_irregular_gets_pitched_roof():
    building = make_building(LSHAPE, "gabled", roof_h=3.0)
    _, roofs, walls = roofs_and_walls(building)
    assert len(roofs) > 1  # generalized pitched roof, not a flat box
    assert all(r["geometry_quality"] == "detailed" for r in roofs)
    assert len(walls) == 6  # footprint preserved


def test_all_surfaces_have_samples_and_normals():
    for shape in ("", "flat", "gabled", "hipped", "pyramidal", "skillion", "dome"):
        building = make_building(RECT, shape, roof_h=3.0)
        surfaces, _, _ = roofs_and_walls(building)
        assert surfaces, shape
        for s in surfaces:
            assert s["samples"], (shape, s["surface_id"])
            n = s["normal"]
            mag = (n["east"] ** 2 + n["north"] ** 2 + n["up"] ** 2) ** 0.5
            assert abs(mag - 1.0) < 1e-6, (shape, s["surface_id"])


def test_surface_geometry_is_3d():
    building = make_building(RECT, "gabled", roof_h=3.0)
    surfaces, _, _ = roofs_and_walls(building)
    for s in surfaces:
        assert len(s["geometry"]) >= 3
        for coord in s["geometry"]:
            assert len(coord) == 3