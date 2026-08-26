from __future__ import annotations

import numpy as np
import trimesh

from ..config import Config
from .loader import load_buildings


def _extrude_one(polygon, height: float) -> trimesh.Trimesh:
    return trimesh.creation.extrude_polygon(polygon, height=float(height), transform=None)


def extrude_buildings(gdf, height_column: str = "height") -> tuple[trimesh.Trimesh, np.ndarray]:
    """Extrude footprints to a LoD1 mesh.

    Returns (merged mesh, face_to_building): face_to_building[i] is the
    building_id string for mesh face i.
    """
    meshes: list[trimesh.Trimesh] = []
    face_to_building: list[str] = []
    for _, row in gdf.iterrows():
        geom = row.geometry
        polygons = [geom] if geom.geom_type == "Polygon" else list(geom.geoms)
        for poly in polygons:
            mesh = _extrude_one(poly, row[height_column])
            meshes.append(mesh)
            face_to_building.extend([str(row["building_id"])] * len(mesh.faces))

    merged = trimesh.util.concatenate(meshes)
    merged.remove_unreferenced_vertices()
    merged.process(validate=False)
    return merged, np.asarray(face_to_building, dtype=object)


def build_mesh_from_path(path: str, cfg: Config | None = None) -> tuple[gpd.GeoDataFrame, trimesh.Trimesh, np.ndarray]:
    from ..config import load_config

    cfg = cfg or load_config()
    gdf = load_buildings(path, target_crs=cfg.city.target_crs, default_height=cfg.city.default_building_height)
    mesh, face_to_building = extrude_buildings(gdf)
    return gdf, mesh, face_to_building