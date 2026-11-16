"""Mesh gate v2: measures, camera tolerance and the three-outcome rule (tools interpreter).

Specified in docs/gate_v2.md. Pure functions: they are handed a loaded mesh, a subject mask and a
validated config (gate_v2_config.parse) and return plain dicts. No file is read or written here,
and no limit, range or frame has a default; pipeline/mesh_gates.py does the loading and writing.

Vocabulary
- frame: how the mesh model's fixed frame maps onto an upright picture (drop_axis, transpose,
  flip_x, flip_y: the same names as the v1 report's "view"). It is the convention, never searched.
- camera: yaw and elevation in degrees, turning the camera around the upright mesh. Yaw turns it
  around the vertical axis; positive elevation raises the camera so it sees more of the top.
  The camera is a scoring tolerance only; it is never applied to the mesh that ships.
- outline: the filled silhouette of the mesh (or subject) as a boolean mask, cropped to its box.
"""
import itertools
import time

import numpy as np
import trimesh
from PIL import Image

import gate_v2_config
import mesh_decimate
import mesh_gates

PROXY_FACES = 3000      # the camera search runs on a copy decimated to about this many faces
ORIENTATION_TURN = 90   # degrees; the diagnostic looks from the side and from above
EPS = 1e-9
MARGIN_DIGITS = 9       # margins are compared after rounding so a value exactly on a margin is stable
REPORT_DIGITS = 4
FAIL, REVIEW, PASS = "fail", "review", "pass"


def view_matrix(frame):
    """3x3 matrix whose rows are the picture's right (u), up (v) and toward-viewer (w) axes in mesh coordinates.

    Derived from the v1 view convention: the picture's columns follow the first kept axis and its
    rows the second (downwards); transpose swaps them, flip_x reverses columns, flip_y rows.
    """
    first, second = [a for a in range(3) if a != frame["drop_axis"]]
    right, down = (second, first) if frame["transpose"] else (first, second)
    u, v = np.zeros(3), np.zeros(3)
    u[right] = -1.0 if frame["flip_x"] else 1.0
    v[down] = 1.0 if frame["flip_y"] else -1.0
    return np.array([u, v, np.cross(u, v)])


def camera_rotation(yaw, elevation):
    """Rotation turning the object for a camera at YAW and ELEVATION degrees (in the picture's axes)."""
    a, e = np.radians(yaw), np.radians(elevation)
    around_up = np.array([[np.cos(a), 0, np.sin(a)], [0, 1, 0], [-np.sin(a), 0, np.cos(a)]])
    around_right = np.array([[1, 0, 0], [0, np.cos(e), -np.sin(e)], [0, np.sin(e), np.cos(e)]])
    return around_right @ around_up


def project(vertices, frame, yaw, elevation):
    """Vertices as (right, up, toward-viewer) columns for the camera pose."""
    return (np.asarray(vertices, float) @ view_matrix(frame).T) @ camera_rotation(yaw, elevation).T


def _crop(mask):
    ys, xs = np.nonzero(mask)
    return mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def outline(vertices, faces, frame, yaw, elevation):
    """(mask, width, height): the mesh's filled outline cropped to its box, and its box in mesh units."""
    pts = project(vertices, frame, yaw, elevation)
    flat = np.column_stack([pts[:, 0], -pts[:, 1], np.zeros(len(pts))])  # silhouette() draws rows downwards
    return _crop(mesh_gates.silhouette(flat, faces, 2)), float(np.ptp(pts[:, 0])), float(np.ptp(pts[:, 1]))


def _resize(mask, width, height):
    size = (max(1, int(width)), max(1, int(height)))
    img = Image.fromarray(mask.astype(np.uint8) * 255).resize(size, Image.NEAREST)
    return np.asarray(img) > mesh_gates.MASK_THRESHOLD


def subject_outline(subject):
    """(mask, aspect): the subject cropped to its box, longer side scaled to GRID pixels; aspect is width:height before scaling."""
    crop = _crop(subject)
    height, width = crop.shape
    scale = mesh_gates.GRID / max(height, width)
    return _resize(crop, round(width * scale), round(height * scale)), width / height


def _overlap(subject, mesh, row, col):
    """Pixel counts (both, subject only, mesh only) with the mesh mask placed at (row, col) over the subject mask."""
    top, left = min(0, row), min(0, col)
    rows = max(subject.shape[0], row + mesh.shape[0]) - top
    cols = max(subject.shape[1], col + mesh.shape[1]) - left
    a, b = np.zeros((rows, cols), bool), np.zeros((rows, cols), bool)
    a[-top:-top + subject.shape[0], -left:-left + subject.shape[1]] = subject
    b[row - top:row - top + mesh.shape[0], col - left:col - left + mesh.shape[1]] = mesh
    return int((a & b).sum()), int((a & ~b).sum()), int((b & ~a).sum())


def register(subject, mesh):
    """Overlay the mesh outline on the subject outline and return {"iou", "deficit", "excess"}.

    The mesh outline keeps its own proportions. It is scaled uniformly so that its width, or
    alternatively its height, equals the subject's, and the other axis is aligned at its start,
    middle or end; the placement with the best overlap is used. A missing top therefore shows up
    as missing area (deficit) instead of being stretched away, which fitting each outline to its
    own box (as silhouette_iou does) would do.
      deficit = subject pixels not covered by the mesh / all subject pixels
      excess  = mesh pixels outside the subject / all mesh pixels
      iou     = pixels in both / pixels in either
    """
    hs, ws = subject.shape
    hm, wm = mesh.shape
    wide = _resize(mesh, ws, round(hm * ws / wm))
    tall = _resize(mesh, round(wm * hs / hm), hs)
    placements = [(wide, row, 0) for row in (0, (hs - wide.shape[0]) // 2, hs - wide.shape[0])]
    placements += [(tall, 0, col) for col in (0, (ws - tall.shape[1]) // 2, ws - tall.shape[1])]
    best = None
    for placed, row, col in placements:
        both, s_only, m_only = _overlap(subject, placed, row, col)
        score = both / max(1, both + s_only + m_only)
        if best is None or score > best["iou"]:
            best = {"iou": score, "deficit": s_only / max(1, both + s_only), "excess": m_only / max(1, both + m_only)}
    return best


def range_values(spec):
    """Camera angles of a [from, to, step] range, both ends included when the step reaches them."""
    start, stop, step = spec
    return [start + i * step for i in range(int((stop - start) / step + EPS) + 1)]


def search_camera(vertices, faces, subject, frame, camera, seconds, clock):
    """Best camera pose over the yaw and elevation ranges, scored by register(); stops at the time limit.

    Poses are tried nearest the conventional view first, so a cut-short search still has the
    conventional pose. Returns {"yaw", "elevation", "score", "tried", "total", "complete"}.
    """
    poses = sorted(itertools.product(range_values(camera["yaw"]), range_values(camera["elevation"])),
                   key=lambda p: (abs(p[0]) + abs(p[1]), p))
    start, best, tried = clock(), None, 0
    for yaw, elevation in poses:
        if tried and clock() - start > seconds:
            break
        score = register(subject, outline(vertices, faces, frame, yaw, elevation)[0])["iou"]
        tried += 1
        if best is None or score > best[0]:
            best = (score, yaw, elevation)
    return {"yaw": best[1], "elevation": best[2], "score": best[0], "tried": tried, "total": len(poses),
            "complete": tried == len(poses)}


def orientation_scan(vertices, faces, subject, frame, conventional_score):
    """Score the other two axes (from either side, from above and from below) against the conventional view.

    Returns {"best_other": score, "view": name, "gain": best_other - conventional_score}.
    """
    turns = {"side": (ORIENTATION_TURN, 0), "other_side": (-ORIENTATION_TURN, 0),
             "above": (0, ORIENTATION_TURN), "below": (0, -ORIENTATION_TURN)}
    scores = {name: register(subject, outline(vertices, faces, frame, yaw, elevation)[0])["iou"]
              for name, (yaw, elevation) in turns.items()}
    name = max(scores, key=lambda n: scores[n])
    return {"best_other": scores[name], "view": name, "gain": scores[name] - conventional_score}


def _proxy(vertices, faces):
    """The mesh decimated to about PROXY_FACES faces for the camera search (welded first)."""
    if len(faces) <= PROXY_FACES:
        return vertices, faces
    welded = trimesh.Trimesh(vertices, faces, process=True)
    out_v, out_f, _ = mesh_decimate.decimate(welded.vertices, welded.faces, PROXY_FACES, False)
    return out_v, out_f


def measure(mesh, subject, config, clock=time.monotonic):
    """All v2 measures for MESH against the SUBJECT mask, with the camera and orientation findings.

    Returns {"measures": {...}, "camera": {...}, "orientation": {...}}. The search runs on a proxy;
    the measures are then taken once on the full mesh at the chosen angles. Definitions:
      silhouette_iou   overlap of the mesh outline and the subject outline, each fitted to its own box
      aspect_error     |mesh width:height - subject width:height| / subject width:height, before any fitting
      deficit, excess  see register()
      depth_ratio      extent along the view axis / the smaller of the other two extents (conventional frame)
      thin_sheet_share as v1 (mesh_gates.thin_sheet_share)
      pieces           connected pieces in the file as given; removing small ones is the normaliser's job
      faces            face count of the file as given
      orientation_gain best score from the other axes minus the conventional score (see orientation_scan)
    """
    vertices, faces = np.asarray(mesh.vertices, float), np.asarray(mesh.faces)
    if not len(faces) or mesh.area_faces.sum() <= 0:
        raise ValueError("mesh has no surface")
    if not subject.any():
        raise ValueError("image has no subject")
    frame, gate = config["frame"], config["gate"]
    target, subject_aspect = subject_outline(subject)
    proxy_v, proxy_f = _proxy(vertices, faces)
    camera = search_camera(proxy_v, proxy_f, target, frame, config["camera"], gate["search_seconds"], clock)
    mask, width, height = outline(vertices, faces, frame, camera["yaw"], camera["elevation"])
    if height <= 0 or width <= 0:
        raise ValueError("mesh outline has no area at the conventional view")
    placed = register(target, mask)
    fitted_iou = mesh_gates.iou(mesh_gates.fit(mask), mesh_gates.fit(target))
    extents = np.ptp(project(vertices, frame, 0, 0), axis=0)
    labels = trimesh.graph.connected_component_labels(mesh.face_adjacency, node_count=len(faces))
    diag = np.linalg.norm(vertices.max(axis=0) - vertices.min(axis=0))
    scan = orientation_scan(proxy_v, proxy_f, target, frame, camera["score"])
    values = {"silhouette_iou": fitted_iou, "aspect_error": abs(width / height - subject_aspect) / subject_aspect,
              "deficit": placed["deficit"], "excess": placed["excess"],
              "depth_ratio": extents[2] / max(EPS, min(extents[0], extents[1])),
              "thin_sheet_share": mesh_gates.thin_sheet_share(mesh, diag),
              "pieces": int(labels.max()) + 1, "faces": int(len(faces)), "orientation_gain": scan["gain"]}
    return {"measures": {k: v if isinstance(v, int) else round(float(v), REPORT_DIGITS) for k, v in values.items()},
            "camera": camera, "orientation": scan}


def _finding(name, value, limit_key, limit, margin, outcome, kind):
    word = "below" if kind == "min" else "above"
    if name == "orientation_gain":
        reason = f"unexpected orientation: another view matches {value:.4f} better than the conventional one"
    elif margin < 0:
        reason = f"{name} {value} is {word} {limit_key} {limit} (margin {margin:+.4f})"
    else:
        reason = f"{name} {value} is within the review margin of {limit_key} {limit} (margin {margin:+.4f})"
    return {"measure": name, "value": value, "limit": limit, "limit_key": limit_key,
            "margin": round(float(margin), REPORT_DIGITS), "outcome": outcome,
            "reason": reason if outcome != PASS else None}


def judge(measures, gate):
    """Per-measure findings: a list of {"measure", "value", "limit", "limit_key", "margin", "outcome", "reason"}.

    Ratio measures: margin is the distance inside the limit (negative when broken). More than
    review_margin inside is pass, within review_margin on either side is review, a break by more
    than review_margin is fail. depth_ratio cannot fail when gate["thin"] is true (review
    instead). faces over face_budget fail; pieces over max_pieces and orientation_gain over
    orientation_margin go to review.
    """
    found, band = [], gate["review_margin"]
    for limit_key, (name, kind) in gate_v2_config.RATIO_LIMITS.items():
        value, limit = measures[name], gate[limit_key]
        margin = round(value - limit if kind == "min" else limit - value, MARGIN_DIGITS)
        if margin > band or (band == 0 and margin >= 0):
            outcome = PASS
        else:
            outcome = FAIL if margin < -band else REVIEW
        if name == "depth_ratio" and gate["thin"] and outcome == FAIL:
            outcome = REVIEW
        found.append(_finding(name, value, limit_key, limit, margin, outcome, kind))
    faces, budget = measures["faces"], gate["face_budget"]
    found.append(_finding("faces", faces, "face_budget", budget, budget - faces, FAIL if faces > budget else PASS, "max"))
    pieces, most = measures["pieces"], gate["max_pieces"]
    found.append(_finding("pieces", pieces, "max_pieces", most, most - pieces, REVIEW if pieces > most else PASS, "max"))
    gain, allowed = measures["orientation_gain"], gate["orientation_margin"]
    found.append(_finding("orientation_gain", gain, "orientation_margin", allowed, round(allowed - gain, MARGIN_DIGITS),
                          REVIEW if round(gain - allowed, MARGIN_DIGITS) > 0 else PASS, "max"))
    return found


def verdict(measures, gate):
    """(verdict, reasons): fail if any finding fails, else review if any needs a person, else pass."""
    found = judge(measures, gate)
    outcomes = {f["outcome"] for f in found}
    result = FAIL if FAIL in outcomes else REVIEW if REVIEW in outcomes else PASS
    return result, [f["reason"] for f in found if f["outcome"] != PASS]


def evaluate(mesh, subject, config, clock=time.monotonic):
    """The v2 report (docs/gate_v2.md, Acceptance 4) for MESH against the SUBJECT mask."""
    result = measure(mesh, subject, config, clock)
    found = judge(result["measures"], config["gate"])
    outcome, reasons = verdict(result["measures"], config["gate"])
    camera = result["camera"]
    if not camera["complete"]:
        outcome = FAIL if outcome == FAIL else REVIEW
        reasons.append(f"camera search stopped at search_seconds after {camera['tried']} of {camera['total']} poses")
    scan = result["orientation"]
    return {"profile": gate_v2_config.PROFILE, "verdict": outcome, "reasons": reasons, "passed": outcome == PASS,
            "frame": config["frame"], "camera_ranges": config["camera"],
            "camera": {k: camera[k] for k in ("yaw", "elevation", "tried", "total", "complete")},
            "orientation": {"best_other_view": scan["view"], "best_other_score": round(float(scan["best_other"]), REPORT_DIGITS),
                            "conventional_score": round(float(camera["score"]), REPORT_DIGITS)},
            "measures": {f["measure"]: {k: f[k] for k in ("value", "limit", "limit_key", "margin", "outcome")}
                         for f in found}}
