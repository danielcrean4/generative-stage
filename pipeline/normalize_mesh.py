"""Put a generated mesh in a known pose, size and origin (tools interpreter: numpy, scipy, trimesh).

python normalize_mesh.py INPUT.glb OUTPUT.glb --config CONFIG.json --report REPORT.json

Steps, in order: orientation, merge close vertices, drop small pieces, fix normals and winding,
scale, move the origin to the base centre. Geometry and vertex colours only. Exits 2 on bad input.

Config keys (all required, no defaults; see docs/normalisers.md):
  orientation            null, {"matrix": 3x3 rotation} or {"view": {drop_axis, transpose, flip_x,
                         flip_y}} exactly as mesh_gates.py writes it in its report
  up_axis, front_axis    signed axes such as "+y" and "-z", perpendicular; the pose the output has
  weld_distance_share    vertices closer than this share of the bounding-box diagonal merge (0 merges
                         only identical points)
  small_piece_area_share connected pieces below this share of the surface area are dropped; the
                         largest piece is always kept
  target_size            the output extent along scale_axis
  scale_axis             "largest" (longest extent) or "x", "y", "z" (an output axis)

A "view" is the gate's best silhouette match: image columns, rows and flips of the mesh axes. It is
turned into the rotation that makes the mesh upright in that image, with the depth axis sign chosen
so the result is a rotation, never a mirror (front versus back cannot be told from a silhouette).
Orientation is applied once: the output records a hash of the orientation block and the axes, and a
rerun with the same ones skips the rotation, which keeps the whole script idempotent.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import trimesh
from scipy import sparse
from scipy.sparse import csgraph
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mesh_io
import normaliser_common as common

TOOL = "normalize_mesh"
STAMP_KEY = "normalize_mesh_frame_sha256"
AXES = "xyz"
ORTHONORMAL_TOLERANCE = 1e-6
VIEW_KEYS = {"drop_axis": int, "transpose": bool, "flip_x": bool, "flip_y": bool}


def signed_axis(value):
    if not isinstance(value, str) or len(value) != 2 or value[0] not in "+-" or value[1] not in AXES:
        raise ValueError('must be a signed axis such as "+y" or "-z"')


def orientation(value):
    if value is None:
        return
    if not isinstance(value, dict) or len(value) != 1 or next(iter(value)) not in ("matrix", "view"):
        raise ValueError('must be null, {"matrix": ...} or {"view": ...}')
    kind, body = next(iter(value.items()))
    if kind == "view":
        if not isinstance(body, dict) or not set(VIEW_KEYS) <= set(body):
            raise ValueError("view must hold " + ", ".join(VIEW_KEYS))
        for key, kind_ in VIEW_KEYS.items():
            if type(body[key]) is not kind_ or (kind_ is int and body[key] not in (0, 1, 2)):
                raise ValueError(f"view.{key} is invalid")
        return
    try:
        matrix = np.array(body, float)
    except (TypeError, ValueError):
        raise ValueError("matrix must be three rows of three numbers")
    if matrix.shape != (3, 3) or not np.isfinite(matrix).all():
        raise ValueError("matrix must be three rows of three numbers")
    if not np.allclose(matrix @ matrix.T, np.eye(3), atol=ORTHONORMAL_TOLERANCE) or np.linalg.det(matrix) < 0:
        raise ValueError("matrix must be a rotation (orthonormal, determinant +1), not a scale or a mirror")


SCHEMA = {"orientation": orientation, "up_axis": signed_axis, "front_axis": signed_axis,
          "weld_distance_share": common.share, "small_piece_area_share": common.share,
          "target_size": common.positive_number, "scale_axis": common.one_of("largest", "x", "y", "z")}


def axis_vector(text):
    vector = np.zeros(3)
    vector[AXES.index(text[1])] = 1.0 if text[0] == "+" else -1.0
    return vector


def check_config(config, path):
    """The one cross-key check: up and front must be different axes."""
    if config["up_axis"][1] == config["front_axis"][1]:
        raise common.NormaliserError(f"{TOOL}: config {path} up_axis and front_axis must be different axes")


def view_rotation(view, up, front):
    """Rotation that makes the mesh upright as the gate's best view saw it, in the up/front pose.

    The gate draws the two axes it keeps (every axis but drop_axis) as image column then row, swaps
    them if transpose, and mirrors columns for flip_x and rows for flip_y. Image right is +X, image up
    is -row, and the third axis (toward the viewer) is X cross Y: the drop axis with the sign that
    makes a rotation. That "viewer" frame (X right, Y up, Z toward the viewer) is then carried onto up/front.
    """
    drop = view["drop_axis"]
    column, row = [axis for axis in range(3) if axis != drop]
    if view["transpose"]:
        column, row = row, column
    viewer = np.zeros((3, 3))
    viewer[0, column] = -1.0 if view["flip_x"] else 1.0
    viewer[1, row] = 1.0 if view["flip_y"] else -1.0
    viewer[2] = np.cross(viewer[0], viewer[1])  # lands on the drop axis, signed so this is a rotation
    target = np.column_stack([np.cross(up, front), up, front])  # viewer X, Y, Z written in output axes
    return target @ viewer


def weld(vertices, faces, colors, distance):
    """Merge vertices within DISTANCE (first of each cluster stays); drop faces that collapse."""
    pairs = cKDTree(vertices).query_pairs(distance, output_type="ndarray")
    count = len(vertices)
    graph = sparse.coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(count, count))
    _, labels = csgraph.connected_components(graph, directed=False)
    unique, first = np.unique(labels, return_index=True)
    order = np.argsort(first)
    new_id = np.empty(len(unique), int)
    new_id[unique[order]] = np.arange(len(unique))
    keep_rows = first[order]
    new_faces = new_id[labels[faces]]
    alive = (new_faces[:, 0] != new_faces[:, 1]) & (new_faces[:, 1] != new_faces[:, 2]) & (new_faces[:, 0] != new_faces[:, 2])
    return (vertices[keep_rows], new_faces[alive], None if colors is None else colors[keep_rows],
            int(count - len(unique)), int((~alive).sum()))


def drop_small_pieces(mesh, min_share):
    """Remove connected pieces below MIN_SHARE of the area; returns (count removed, share removed)."""
    labels = trimesh.graph.connected_component_labels(mesh.face_adjacency, node_count=len(mesh.faces))
    by_piece = np.bincount(labels, weights=mesh.area_faces)
    total = by_piece.sum()
    keep_piece = by_piece / total >= min_share
    keep_piece[int(np.argmax(by_piece))] = True
    if keep_piece.all():
        return 0, 0.0
    mesh.update_faces(keep_piece[labels])
    mesh.remove_unreferenced_vertices()
    return int((~keep_piece).sum()), float(by_piece[~keep_piece].sum() / total)


def frame_hash(config):
    block = {"orientation": config["orientation"], "up_axis": config["up_axis"], "front_axis": config["front_axis"]}
    return hashlib.sha256(json.dumps(block, sort_keys=True).encode()).hexdigest()


def apply_orientation(vertices, config, already):
    """Return (vertices, report body); skipped when the input already carries this frame's stamp."""
    spec = config["orientation"]
    if spec is None:
        return vertices, {"applied": False, "reason": "orientation is null"}
    if already:
        return vertices, {"applied": False, "reason": "input already carries this orientation (stamp matches)"}
    kind, body = next(iter(spec.items()))
    if kind == "view":
        rotation = view_rotation(body, axis_vector(config["up_axis"]), axis_vector(config["front_axis"]))
    else:
        rotation = np.array(body, float)
    return vertices @ rotation.T, {"applied": True, "kind": kind, "matrix": rotation.round(9).tolist()}


def normalize(mesh, config):
    """Return (output mesh, report body)."""
    before = mesh_io.summary(mesh)
    colors = mesh_io.vertex_colors(mesh)
    frame = frame_hash(config)
    already = mesh.metadata.get(STAMP_KEY) == frame
    vertices, oriented = apply_orientation(np.asarray(mesh.vertices, float), config, already)
    diagonal = float(np.linalg.norm(vertices.max(axis=0) - vertices.min(axis=0)))
    vertices, faces, colors, merged, collapsed = weld(
        vertices, np.asarray(mesh.faces), colors, config["weld_distance_share"] * diagonal)
    if not len(faces):
        raise common.NormaliserError(f"{TOOL}: no faces left after merging vertices; weld_distance_share is too large")
    out = mesh_io.build(vertices, faces, colors)
    out.remove_unreferenced_vertices()
    dropped, dropped_share = drop_small_pieces(out, config["small_piece_area_share"])
    faces_before_fix = np.asarray(out.faces).copy()
    trimesh.repair.fix_normals(out, multibody=True)
    flipped = int((np.asarray(out.faces) != faces_before_fix).any(axis=1).sum())
    vertices = np.asarray(out.vertices, float)
    up = axis_vector(config["up_axis"])
    up_index = int(np.argmax(np.abs(up)))
    lo, hi = vertices.min(axis=0), vertices.max(axis=0)
    extents = hi - lo
    extent = float(extents.max()) if config["scale_axis"] == "largest" else float(extents[AXES.index(config["scale_axis"])])
    if extent <= 0:
        raise common.NormaliserError(f"{TOOL}: mesh has no extent along scale_axis '{config['scale_axis']}'")
    scale = config["target_size"] / extent
    vertices = vertices * scale
    lo, hi = vertices.min(axis=0), vertices.max(axis=0)
    shift = -(lo + hi) / 2
    shift[up_index] = -lo[up_index] if up[up_index] > 0 else -hi[up_index]
    out = mesh_io.build(vertices + shift, out.faces, mesh_io.vertex_colors(out),
                        {STAMP_KEY: frame} if config["orientation"] is not None else
                        ({STAMP_KEY: mesh.metadata[STAMP_KEY]} if STAMP_KEY in mesh.metadata else {}))
    report = {"orientation": oriented, "vertices_merged": merged, "faces_collapsed_by_merge": collapsed,
              "pieces_dropped": dropped, "dropped_area_share": round(dropped_share, 6),
              "faces_rewound": flipped, "scale_applied": round(scale, 9),
              "vertex_colors": {"present": mesh_io.vertex_colors(mesh) is not None,
                                "kept": mesh_io.vertex_colors(out) is not None},
              "dropped_visual": mesh_io.visual_kind(mesh) not in (None, "vertex"),
              "before": before, "after": mesh_io.summary(out)}
    return out, report


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    config, config_sha = common.load_config(args.config, SCHEMA, TOOL)
    check_config(config, args.config)
    common.require_file(args.input, TOOL, "input mesh")
    out, report = normalize(mesh_io.load_mesh(args.input, TOOL), config)
    mesh_io.save_mesh(out, args.output)
    report.update({"tool": TOOL, "config": config, "config_sha256": config_sha})
    common.write_report(args.report, report)
    return 0


if __name__ == "__main__":
    sys.exit(common.run(TOOL, main))
