"""Shape gate: measure a generated mesh against the image it was made from (tools interpreter).

python mesh_gates.py MESH.glb IMAGE.png --out mesh-validation.json [--checks '{"max_thin_sheet_share": 0.3}']
python mesh_gates.py MESH.glb IMAGE.png --out mesh-validation.json --profile v2 --gate CONFIG.json
Writes the report, then exits with a code: 0 pass, 1 fail (v1: any gate failed), 2 usage or config
error, 3 review (v2 only: a person decides; see docs/gate_v2.md). v1 is the default profile.
"""
import argparse
import itertools
import json
import sys
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
import background_spec
import gate_settings
import subject_mask

GRID = 128          # silhouette comparison resolution
SUPERSAMPLE = 4     # mesh silhouettes are drawn this many times larger than GRID, then fitted
NORMAL_STEP = 0.1   # normal quantisation (about 6 degrees)
OFFSET_STEP = 0.01  # plane offset bin, as a share of the bounding-box diagonal
SHEET_GAP = 3       # opposite faces within this many offset bins count as one thin sheet
TOP_PLANES = 40     # largest planes examined for a thin sheet
BACK_SHARE = 0.25   # a plane needs an opposite one at least this share of its area to form a sheet
MASK_THRESHOLD = 127
EXIT_GATE_FAILED = 1
EXIT_USAGE = 2
EXIT_REVIEW = 3
PROFILES = ("v1", "v2")
V2_EXIT = {"pass": 0, "fail": EXIT_GATE_FAILED, "review": EXIT_REVIEW}


def fit(mask):
    """Crop to the bounding box and scale, keeping aspect, onto a GRID square."""
    ys, xs = np.nonzero(mask)
    crop = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    h, w = crop.shape
    scale = GRID / max(h, w)
    size = (max(1, round(w * scale)), max(1, round(h * scale)))
    small = np.asarray(Image.fromarray(crop.astype(np.uint8) * 255).resize(size, Image.NEAREST)) > MASK_THRESHOLD
    out = np.zeros((GRID, GRID), bool)
    y, x = (GRID - size[1]) // 2, (GRID - size[0]) // 2
    out[y:y + size[1], x:x + size[0]] = small
    return out


def bbox_fill(mask):
    """Share of the mask's bounding box that the mask covers."""
    ys, xs = np.nonzero(mask)
    return float(mask.sum() / ((np.ptp(ys) + 1) * (np.ptp(xs) + 1)))


def silhouette(vertices, faces, drop):
    keep = [a for a in range(3) if a != drop]
    pts = vertices[:, keep]
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    res = SUPERSAMPLE * GRID
    px = (pts - lo) / max(1e-12, (hi - lo).max()) * (res - 1)
    img = Image.new("1", (res, res), 0)
    draw = ImageDraw.Draw(img)
    for tri in px[faces].reshape(-1, 6).tolist():
        draw.polygon(tri, fill=1, outline=1)
    return np.asarray(img)


def iou(a, b):
    return (a & b).sum() / max(1, (a | b).sum())


def best_view(vertices, faces, target):
    """Best silhouette overlap with the target over the three axes and the eight flips."""
    best_score, best_fitted, best_view_info = 0.0, None, None
    for drop in range(3):
        sil = silhouette(vertices, faces, drop)
        for transpose, flip_x, flip_y in itertools.product((False, True), repeat=3):
            s = sil.T if transpose else sil
            s = s[:, ::-1] if flip_x else s
            s = s[::-1] if flip_y else s
            fitted = fit(s)
            score = iou(fitted, target)
            if best_fitted is None or score > best_score:
                best_score, best_fitted = score, fitted
                best_view_info = {"drop_axis": drop, "transpose": transpose, "flip_x": flip_x, "flip_y": flip_y}
    return best_score, best_fitted, best_view_info


def thin_sheet_share(mesh, diag):
    """Largest share of surface area lying on a plane plus a nearly coincident opposed plane."""
    areas = mesh.area_faces
    total = areas.sum()
    nbin = np.round(mesh.face_normals / NORMAL_STEP).astype(np.int64)
    unit = nbin / np.maximum(1e-9, np.linalg.norm(nbin, axis=1, keepdims=True))
    offset = np.round((unit * mesh.triangles_center).sum(axis=1) / (diag * OFFSET_STEP)).astype(np.int64)
    planes = {}
    for key, area in zip(map(tuple, np.column_stack([nbin, offset]).tolist()), areas.tolist()):
        planes[key] = planes.get(key, 0.0) + area
    sheet = 0.0
    for (nx, ny, nz, d), area in sorted(planes.items(), key=lambda kv: -kv[1])[:TOP_PLANES]:
        back = max(planes.get((-nx, -ny, -nz, -d + k), 0.0) for k in range(-SHEET_GAP, SHEET_GAP + 1))
        if back > BACK_SHARE * area:
            sheet = max(sheet, (area + back) / total)
    return sheet


def measure(mesh_path, image_path, background):
    mesh = trimesh.load(mesh_path, force="mesh", process=False)
    vertices, faces = np.asarray(mesh.vertices, float), np.asarray(mesh.faces)
    if not len(faces) or mesh.area_faces.sum() <= 0:
        raise ValueError("mesh has no surface")
    labels = trimesh.graph.connected_component_labels(mesh.face_adjacency, node_count=len(faces))
    by_piece = np.bincount(labels, weights=mesh.area_faces)
    subject = subject_mask.load_subject(image_path, background)
    if not subject.any():
        raise ValueError("image has no subject")
    target = fit(subject)
    score, fitted, view = best_view(vertices, faces, target)
    image_fill, mesh_fill = bbox_fill(target), bbox_fill(fitted)
    diag = np.linalg.norm(vertices.max(axis=0) - vertices.min(axis=0))
    return {"faces": int(len(faces)), "pieces": int(len(by_piece)),
            "largest_piece_share": round(float(by_piece.max() / by_piece.sum()), 4),
            "watertight": bool(mesh.is_watertight), "silhouette_iou": round(float(score), 4), "view": view,
            "silhouette_fill": round(mesh_fill, 4), "image_fill": round(image_fill, 4),
            "silhouette_excess": round(mesh_fill - image_fill, 4),
            "thin_sheet_share": round(float(thin_sheet_share(mesh, diag)), 4)}


def evaluate(measures, checks):
    """Human-readable reasons for every threshold the measures break."""
    reasons = []
    rules = (("largest_piece_share", "min_largest_piece_share", "below"),
             ("silhouette_iou", "min_silhouette_iou", "below"),
             ("thin_sheet_share", "max_thin_sheet_share", "above"),
             ("silhouette_excess", "max_silhouette_excess", "above"))
    for measure_name, check_name, direction in rules:
        value, limit = measures[measure_name], checks[check_name]
        if (value < limit) if direction == "below" else (value > limit):
            reasons.append(f"{measure_name} {value} is {direction} {check_name} {limit}")
    if checks["require_watertight"] and not measures["watertight"]:
        reasons.append("mesh is not watertight and require_watertight is set")
    return reasons


def v2_report(mesh_path, image_path, background, config):
    """The v2 report for the mesh file against the image (BACKGROUND: the settings object that separates
    the subject), or a fail report saying it could not measure."""
    import gate_v2
    import gate_v2_config
    try:
        mesh = trimesh.load(mesh_path, force="mesh", process=False)
        return gate_v2.evaluate(mesh, subject_mask.load_subject(image_path, background), config)
    except (ValueError, OSError) as exc:
        return {"profile": gate_v2_config.PROFILE, "verdict": gate_v2.FAIL, "passed": False, "measures": None,
                "reasons": [f"could not measure: {exc}"]}


def _tolerance(args):
    return gate_settings.MATTE_DEFAULTS["tolerance"] if args.tolerance is None else args.tolerance


def run_v2(args):
    """The v2 profile: load the inputs, call gate_v2 and write its report; returns the exit code."""
    import gate_v2_config
    try:
        config = gate_v2_config.load(args.gate)
    except gate_v2_config.ConfigError as exc:
        print(f"mesh_gates: {exc}", file=sys.stderr)
        return EXIT_USAGE
    if config["background"] is not None and args.tolerance is not None:
        print("mesh_gates: the gate config has capture.background; do not also pass --tolerance", file=sys.stderr)
        return EXIT_USAGE
    try:
        background = config["background"] or background_spec.near_white(_tolerance(args))
    except background_spec.BackgroundError as exc:
        print(f"mesh_gates: --tolerance {exc}", file=sys.stderr)
        return EXIT_USAGE
    report = v2_report(args.mesh, args.image, background, config)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    if report["reasons"]:
        print(f"mesh gate {report['verdict']}: " + "; ".join(report["reasons"]), file=sys.stderr)
    return V2_EXIT[report["verdict"]]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mesh", type=Path)
    parser.add_argument("image", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--checks", default="{}", help="JSON object overriding thresholds")
    parser.add_argument("--tolerance", type=int, default=None,
                        help="near_white level for the border flood when the image has no alpha (default "
                             f"{gate_settings.MATTE_DEFAULTS['tolerance']}); v2 may take capture.background from the gate config instead")
    parser.add_argument("--profile", choices=PROFILES, default="v1", help="v1 (default) or v2 (docs/gate_v2.md)")
    parser.add_argument("--gate", type=Path, help="v2 only: JSON config with the gate block, camera ranges, frame and face budget")
    args = parser.parse_args()
    if (args.profile == "v2") != (args.gate is not None):
        print("mesh_gates: --gate CONFIG.json is required with --profile v2 and not allowed with v1", file=sys.stderr)
        return EXIT_USAGE
    if args.profile == "v2":
        return run_v2(args)
    try:
        checks = gate_settings.mesh_checks(json.loads(args.checks))
    except ValueError as exc:
        print(f"mesh_gates: {exc}", file=sys.stderr)
        return EXIT_USAGE
    report = {"thresholds": checks, "measures": None}
    try:
        report["measures"] = measure(args.mesh, args.image, background_spec.near_white(_tolerance(args)))
        report["reasons"] = evaluate(report["measures"], checks)
    except (ValueError, OSError) as exc:
        report["reasons"] = [f"could not measure: {exc}"]
    report["passed"] = not report["reasons"]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    if report["reasons"]:
        print("mesh gate failed: " + "; ".join(report["reasons"]), file=sys.stderr)
        return EXIT_GATE_FAILED
    return 0


if __name__ == "__main__":
    sys.exit(main())
