"""Builds a small multi-part PC as assets/viewer3d/models/cad/pc.glb (needs trimesh).

No PC model exists among the free Khronos samples, so it is generated here. Every part is its
own named node, so viewer_3d explode_model separates them and the hover tooltip shows the name.
Run: python -m core.make_pc_cad
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from core.viewer3d import MODELS_DIR

# name -> (RGBA base colour, metallic, roughness). Units are arbitrary; the viewer rescales.
# The left side of the case (x = -1) is open so the internals stay visible.
MATERIALS = {
    "case": ((150, 158, 170, 255), 1.0, 0.35),
    "motherboard": ((20, 110, 60, 255), 0.1, 0.2),
    "cpu": ((190, 190, 200, 255), 0.9, 0.3),
    "cpu_cooler": ((170, 175, 185, 255), 1.0, 0.25),
    "ram_1": ((212, 175, 55, 255), 1.0, 0.25),
    "ram_2": ((212, 175, 55, 255), 1.0, 0.25),
    "gpu": ((160, 30, 30, 255), 0.6, 0.4),
    "psu": ((50, 50, 55, 255), 0.5, 0.5),
    "fan": ((0, 170, 220, 255), 0.2, 0.4),
}
WALL = 0.05


def _box(trimesh, extents, centre):
    mesh = trimesh.creation.box(extents=extents)
    mesh.apply_translation(centre)
    return mesh


def _disc(trimesh, radius, height, centre):
    """Cylinder whose axis points along x (towards the open side of the case)."""
    mesh = trimesh.creation.cylinder(radius=radius, height=height, sections=40)
    mesh.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0]))
    mesh.apply_translation(centre)
    return mesh


def _part_meshes(trimesh):
    cat = trimesh.util.concatenate
    ram = lambda z: cat([_box(trimesh, (0.08, 0.6, 0.12), (0.62, 0.35, z)),
                         _box(trimesh, (0.1, 0.05, 0.12), (0.62, 0.0, z))])
    fins = [_disc(trimesh, 0.22, 0.02, (0.52 - 0.06 * i, 0.35, 0.0)) for i in range(5)]
    return {
        "case": _case_mesh(trimesh),
        "motherboard": _box(trimesh, (0.06, 1.7, 1.5), (0.7, 0.0, 0.0)),
        "cpu": _box(trimesh, (0.08, 0.3, 0.3), (0.62, 0.35, 0.0)),
        "cpu_cooler": cat([_disc(trimesh, 0.08, 0.3, (0.45, 0.35, 0.0))] + fins),
        "ram_1": ram(0.5),
        "ram_2": ram(0.68),
        "gpu": cat([_box(trimesh, (0.35, 0.18, 1.1), (0.45, -0.25, 0.0)),
                    _disc(trimesh, 0.15, 0.06, (0.24, -0.25, -0.25)),
                    _disc(trimesh, 0.15, 0.06, (0.24, -0.25, 0.25))]),
        "psu": _box(trimesh, (1.0, 0.5, 0.7), (0.0, -0.95, -0.6)),
        "fan": cat([_disc(trimesh, 0.28, 0.06, (0.1, 0.0, -0.95)),
                    _disc(trimesh, 0.06, 0.12, (0.1, 0.0, -0.95))]),
    }


def _case_mesh(trimesh):
    """Open-sided case shell as one mesh: floor, ceiling, back and right panels."""
    h = 1.0
    panels = [
        ((2.0, WALL, 2.0), (0.0, -h, 0.0)),
        ((2.0, WALL, 2.0), (0.0, h, 0.0)),
        ((2.0, 2.0, WALL), (0.0, 0.0, -1.0)),
        ((WALL, 2.0, 2.0), (1.0, 0.0, 0.0)),
    ]
    boxes = []
    for extents, centre in panels:
        box = trimesh.creation.box(extents=extents)
        box.apply_translation(centre)
        boxes.append(box)
    return trimesh.util.concatenate(boxes)


def build_scene():
    try:
        import trimesh
    except ImportError as exc:
        raise RuntimeError("trimesh is not installed: pip install -r requirements-3d.txt") from exc
    scene = trimesh.Scene()
    for name, mesh in _part_meshes(trimesh).items():
        color, metallic, roughness = MATERIALS[name]
        material = trimesh.visual.material.PBRMaterial(
            name=name, baseColorFactor=color, metallicFactor=metallic, roughnessFactor=roughness
        )
        mesh.visual = trimesh.visual.TextureVisuals(
            uv=np.zeros((len(mesh.vertices), 2)), material=material
        )
        scene.add_geometry(mesh, node_name=name, geom_name=name)
    return scene


def make_pc_cad(dest: Path | None = None) -> Path:
    target = Path(dest or MODELS_DIR / "cad") / "pc.glb"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(build_scene().export(file_type="glb"))
    return target


if __name__ == "__main__":
    print(f"Saved {make_pc_cad()}")
