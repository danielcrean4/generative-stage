"""Known-bad variants of a mesh, for proving the mesh gate can fail (tools interpreter).

python gate_mutants.py MESH.glb OUT_DIR   writes one <name>.glb per mutant into OUT_DIR

Every mutant is deterministic: the only randomness is one generator with the fixed SCATTER_SEED.
Add a mutant by writing a function (mesh -> mesh) and listing it in MUTANTS; see docs/gate_v2.md.
"""
import sys
from pathlib import Path

import numpy as np
import trimesh

UP = 1                    # glTF is Y-up: "top" and "height" are this axis, "depth" is DEPTH
DEPTH = 2
SCATTER_SEED = 20261111
SCATTER_PIECES = 30
SCATTER_AREA_SHARE = 0.03  # all loose pieces together, as a share of the mesh surface area
SCATTER_MARGIN = 0.1       # pieces sit inside the bounding box grown by this share of its size
SCALE_UP = 3.0


def box(mesh):
    """A plain box with the same bounding box."""
    lo, hi = mesh.bounds
    return trimesh.creation.box(extents=hi - lo, transform=trimesh.transformations.translation_matrix((lo + hi) / 2))


def cut_top(share):
    def cut(mesh):
        lo, hi = mesh.bounds
        keep = mesh.triangles_center[:, UP] < hi[UP] - (hi[UP] - lo[UP]) * share
        out = mesh.copy()
        out.update_faces(keep)
        out.remove_unreferenced_vertices()
        return out
    return cut


def relief(mesh, depth_share=0.15):
    """Depth squashed to a shallow relief about its mean."""
    out = mesh.copy()
    vertices = out.vertices.copy()
    middle = vertices[:, DEPTH].mean()
    vertices[:, DEPTH] = middle + (vertices[:, DEPTH] - middle) * depth_share
    out.vertices = vertices
    return out


def on_side(mesh):
    out = mesh.copy()
    out.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, (1, 0, 0)))
    return out


def scatter(mesh):
    """The mesh plus loose small spheres, placed with a fixed seed."""
    rng = np.random.default_rng(SCATTER_SEED)
    lo, hi = mesh.bounds
    size = hi - lo
    radius = np.sqrt(SCATTER_AREA_SHARE * mesh.area / SCATTER_PIECES / (4 * np.pi))
    parts = [mesh]
    for _ in range(SCATTER_PIECES):
        bit = trimesh.creation.icosphere(subdivisions=1, radius=radius)
        bit.apply_translation(rng.uniform(lo - SCATTER_MARGIN * size, hi + SCATTER_MARGIN * size))
        parts.append(bit)
    return trimesh.util.concatenate(parts)


def mirrored(mesh):
    out = mesh.copy()
    vertices = out.vertices.copy()
    vertices[:, 0] *= -1
    out.vertices = vertices
    out.invert()          # a mirror flips winding; restore outward normals
    return out


def subdivided(mesh):
    return mesh.subdivide().subdivide()


def scaled_up(mesh):
    out = mesh.copy()
    out.apply_scale(SCALE_UP)
    return out


MUTANTS = {
    "box": box,
    "cut_20": cut_top(0.20),
    "cut_33": cut_top(0.33),
    "relief_15": relief,
    "on_side": on_side,
    "scatter": scatter,
    "mirrored": mirrored,
    "subdivided": subdivided,
    "scaled_3x": scaled_up,
}


def write_all(mesh_path, out_dir):
    mesh = trimesh.load(mesh_path, force="mesh", process=False)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, make in MUTANTS.items():
        make(mesh).export(out_dir / f"{name}.glb")


if __name__ == "__main__":
    write_all(Path(sys.argv[1]), Path(sys.argv[2]))
