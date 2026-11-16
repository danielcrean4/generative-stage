"""Read and write .glb geometry for the mesh normalisers (tools interpreter: numpy, trimesh).

Geometry only, plus vertex colours when the file has them. Texture materials are not carried (the
pipeline's meshes have none); load_mesh reports what was dropped. Metadata survives a round trip, which
is how normalize_mesh knows it already applied an orientation.
"""
import numpy as np
import trimesh

from normaliser_common import NormaliserError


def load_mesh(path, tool):
    """The mesh at PATH as one Trimesh (no processing), or NormaliserError."""
    try:
        mesh = trimesh.load(path, force="mesh", process=False)
    except Exception as exc:  # trimesh raises many types for unreadable files
        raise NormaliserError(f"{tool}: cannot read mesh {path}: {exc}")
    if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
        raise NormaliserError(f"{tool}: mesh {path} has no faces")
    if not np.isfinite(mesh.vertices).all():
        raise NormaliserError(f"{tool}: mesh {path} has non-finite vertex positions")
    return mesh


def vertex_colors(mesh):
    """uint8 RGBA per vertex, or None when the mesh has none."""
    if mesh.visual.kind == "vertex":
        return np.asarray(mesh.visual.vertex_colors, dtype=np.uint8)
    return None


def visual_kind(mesh):
    """'vertex', 'texture' or None: what the file carried (only 'vertex' is kept)."""
    return mesh.visual.kind


def build(vertices, faces, colors=None, metadata=None):
    mesh = trimesh.Trimesh(np.asarray(vertices, float), np.asarray(faces), process=False,
                           vertex_colors=colors)
    if metadata:
        mesh.metadata.update(metadata)
    return mesh


def save_mesh(mesh, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    mesh.export(path)


def piece_stats(mesh):
    """(count, largest share of surface area) of the connected pieces, as the mesh gate counts them."""
    labels = trimesh.graph.connected_component_labels(mesh.face_adjacency, node_count=len(mesh.faces))
    by_piece = np.bincount(labels, weights=mesh.area_faces)
    return int(len(by_piece)), float(by_piece.max() / by_piece.sum())


def summary(mesh):
    """Before/after numbers shared by the mesh reports."""
    pieces, largest = piece_stats(mesh)
    lo, hi = mesh.bounds
    return {"faces": int(len(mesh.faces)), "pieces": pieces, "largest_piece_share": round(largest, 6),
            "watertight": bool(mesh.is_watertight),
            "bounds": {"min": [round(float(v), 6) for v in lo], "max": [round(float(v), 6) for v in hi]}}
