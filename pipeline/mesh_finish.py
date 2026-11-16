"""Finish one mesh: normalise, decimate, then judge it with the v2 gate (tools interpreter).

python mesh_finish.py MESH.glb IMAGE.png OUT_DIR --config CONFIG.json

The chain of docs/gate_v2.md "Finishing chain": normalize_mesh (the fixed frame, weld, drop small
pieces, scale, origin), decimate_mesh, then the v2 gate on the file that would ship. Nothing the gate
finds is fed back into the mesh. The steps are called through their public functions
(normalize_mesh.normalize, decimate_mesh.decimate_file, mesh_gates.v2_report), in this process: it
avoids three interpreter start-ups and re-reading the mesh, and it cannot drift from the CLIs because
they call the same functions.

OUT_DIR gets clean/mesh.glb + clean/report.json, decimate/mesh.glb + decimate/report.json,
gate/mesh-validation.json, gate/review-sheet.png (docs/gate_v2.md "Review sheet", written for every verdict) and finish.json (verdict, each step's time, the config hash).
Exit codes follow the gate: 0 pass, 1 fail, 3 review, 2 usage or config error (nothing is written).

python mesh_finish.py step (clean_mesh|decimate|shape_gate) MESH OUT_DIR --config CONFIG.json [--image IMAGE.png]
runs one of the three stages by itself, for the pipeline runner (pipeline/pipeline_run.py): the same functions as
the chain, one stage per call, writing mesh.glb (clean_mesh, decimate) or mesh-validation.json and
review-sheet.png (shape_gate) straight into OUT_DIR. Exit codes as above; a clean or decimate step that cannot
finish exits 1 and writes step-failed.json.

The config is one file shaped like the stages of docs/pipeline_files.md; every key is required, none
has a default, and this module is the one place that validates it:
  contract    up_axis, front_axis, target_size, scale_axis, face_budget   (the contract for the kind)
  clean_mesh  weld_distance_share, small_piece_area_share, orientation    (orientation is {"view": frame}:
              the mesh model's fixed frame, which the gate also uses as its conventional view)
  decimate    preserve_topology
  capture     background (either {"tolerance": N}, meaning near_white, or a full background settings
              object with its `method`, pipeline/background_spec.py), view.camera.yaw / .elevation
  gate        the v2 gate block (gate_v2_config.GATE_KEYS)
  review_sheet  the look and layout of the sheet (review_sheet.parse validates it)
"""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import background_spec
import decimate_mesh
import gate_v2_config
import mesh_gates
import mesh_io
import normaliser_common as common
import normalize_mesh
import review_sheet

TOOL = "mesh_finish"
EXIT_USAGE = common.EXIT_BAD_INPUT
EXIT_BY_VERDICT = mesh_gates.V2_EXIT
CONTRACT_SCHEMA = {"up_axis": normalize_mesh.signed_axis, "front_axis": normalize_mesh.signed_axis,
                   "target_size": common.positive_number, "scale_axis": normalize_mesh.SCHEMA["scale_axis"],
                   "face_budget": common.positive_int}
CLEAN_SCHEMA = {"weld_distance_share": common.share, "small_piece_area_share": common.share,
                "orientation": normalize_mesh.orientation}
DECIMATE_SCHEMA = {"preserve_topology": common.boolean}
LEGACY_BACKGROUND_KEYS = {"tolerance": common.channel}  # a block with no `method` is near_white with this tolerance
TOP_KEYS = ("contract", "clean_mesh", "decimate", "capture", "gate", "review_sheet")
IDENTITY_TOLERANCE = 1e-9
SHEET_NAME = "review-sheet.png"
STEP_NAMES = ("clean_mesh", "decimate", "shape_gate")  # the pipeline stages this module runs one at a time


class ConfigError(ValueError):
    """The finish config is missing a key or holds an invalid value (the message names file and key)."""


def _block(raw, schema, where, source):
    if not isinstance(raw, dict):
        raise ConfigError(f"{source}: {where} must be an object")
    for key in schema:
        if key not in raw:
            raise ConfigError(f"{source}: missing key {where}.{key}")
    for key in raw:
        if key not in schema:
            raise ConfigError(f"{source}: unknown key {where}.{key}")
    for key, check in schema.items():
        try:
            check(raw[key])
        except ValueError as exc:
            raise ConfigError(f"{source}: {where}.{key} {exc}")
    return raw


def _background(raw, source):
    """The settings object for capture.background; a block with only `tolerance` is the older near_white shape."""
    if isinstance(raw, dict) and "method" not in raw:
        return background_spec.near_white(_block(raw, LEGACY_BACKGROUND_KEYS, "capture.background", source)["tolerance"])
    try:
        return background_spec.parse(raw)
    except background_spec.BackgroundError as exc:
        raise ConfigError(f"{source}: capture.background{'.' + exc.key if exc.key else ''} {exc.message}")


def parse(raw, source):
    """Validate the decoded config and return the step configs each tool takes.

    {"normalize": ..., "decimate": ..., "gate": gate_v2_config.parse(...), "background": the settings object,
    "review_sheet": the validated block, "axes": (up_axis, front_axis)}.
    """
    if not isinstance(raw, dict):
        raise ConfigError(f"{source}: config must be an object")
    for key in TOP_KEYS:
        if key not in raw:
            raise ConfigError(f"{source}: missing key config.{key}")
    for key in raw:
        if key not in TOP_KEYS:
            raise ConfigError(f"{source}: unknown key config.{key}")
    contract = _block(raw["contract"], CONTRACT_SCHEMA, "contract", source)
    clean = _block(raw["clean_mesh"], CLEAN_SCHEMA, "clean_mesh", source)
    decimate = _block(raw["decimate"], DECIMATE_SCHEMA, "decimate", source)
    capture = raw["capture"]
    if not isinstance(capture, dict):
        raise ConfigError(f"{source}: capture must be an object")
    for key in ("background", "view"):
        if key not in capture:
            raise ConfigError(f"{source}: missing key capture.{key}")
    for key in capture:
        if key not in ("background", "view"):
            raise ConfigError(f"{source}: unknown key capture.{key}")
    background = _background(capture["background"], source)
    if contract["up_axis"][1] == contract["front_axis"][1]:
        raise ConfigError(f"{source}: contract.up_axis and contract.front_axis must be different axes")
    if clean["orientation"] is None or "view" not in clean["orientation"]:
        raise ConfigError(f"{source}: clean_mesh.orientation must be {{\"view\": frame}}, the mesh model's fixed frame")
    frame = clean["orientation"]["view"]
    # The gate looks at the normalised mesh through this same frame, so normalising must not turn it.
    rotation = normalize_mesh.view_rotation(frame, normalize_mesh.axis_vector(contract["up_axis"]),
                                            normalize_mesh.axis_vector(contract["front_axis"]))
    if not np.allclose(rotation, np.eye(3), atol=IDENTITY_TOLERANCE):
        raise ConfigError(f"{source}: contract.up_axis/front_axis disagree with clean_mesh.orientation: the frame would "
                          f"be turned by {rotation.round(3).tolist()} and the gate would no longer see the mesh upright")
    gate_raw = {"gate": raw["gate"], "capture": {"view": capture["view"]}}
    try:
        gate = gate_v2_config.parse(gate_raw, source, supplied={"frame": dict(frame), "face_budget": contract["face_budget"]})
    except gate_v2_config.ConfigError as exc:
        raise ConfigError(str(exc))
    try:
        sheet = review_sheet.parse(raw["review_sheet"], source)
    except review_sheet.ConfigError as exc:
        raise ConfigError(str(exc))
    return {"normalize": {**clean, **{k: contract[k] for k in ("up_axis", "front_axis", "target_size", "scale_axis")}},
            "decimate": {"face_budget": contract["face_budget"], **decimate},
            "gate": gate, "background": background,
            "review_sheet": sheet, "axes": (contract["up_axis"], contract["front_axis"])}


def load(path):
    """Read PATH and return (step configs, sha256 of the file); ConfigError names the file and key."""
    path = Path(path)
    try:
        data = path.read_bytes()
        raw = json.loads(data)
    except (OSError, ValueError) as exc:
        raise ConfigError(f"{path}: cannot read config: {exc}")
    return parse(raw, path), hashlib.sha256(data).hexdigest()


def _step_report(path, tool, config, report):
    sha = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    common.write_report(path, {**report, "tool": tool, "config": config, "config_sha256": sha})


def clean_step(mesh_path, out_dir, steps):
    """normalize_mesh on MESH_PATH into OUT_DIR/mesh.glb and report.json; returns the step's report."""
    cleaned, report = normalize_mesh.normalize(mesh_io.load_mesh(mesh_path, TOOL), steps["normalize"])
    mesh_io.save_mesh(cleaned, out_dir / "mesh.glb")
    _step_report(out_dir / "report.json", normalize_mesh.TOOL, steps["normalize"], report)
    return report


def decimate_step(mesh_path, out_dir, steps):
    """decimate_mesh on MESH_PATH into OUT_DIR/mesh.glb and report.json; returns the step's report."""
    report = decimate_mesh.decimate_file(mesh_path, out_dir / "mesh.glb", steps["decimate"])
    _step_report(out_dir / "report.json", decimate_mesh.TOOL, steps["decimate"], report)
    return report


def gate_step(mesh_path, image_path, out_dir, steps):
    """The v2 gate on MESH_PATH into OUT_DIR/mesh-validation.json; returns the report."""
    report = mesh_gates.v2_report(mesh_path, image_path, steps["background"], steps["gate"])
    common.write_report(out_dir / "mesh-validation.json", report)
    return report


def sheet_step(image_path, mesh_path, result, gate_report, steps, out_dir):
    """Write OUT_DIR/review-sheet.png (MESH_PATH None: the chain stopped early); returns the seconds it took."""
    start = time.monotonic()
    sheet = review_sheet.build(image_path, mesh_path, result, gate_report, steps["axes"], steps["review_sheet"])
    out_dir.mkdir(parents=True, exist_ok=True)
    sheet.save(out_dir / SHEET_NAME)
    return time.monotonic() - start


def finish(mesh_path, image_path, out_dir, steps, config_sha):
    """Run the chain into OUT_DIR; returns the finish.json dict."""
    clock = {}
    clean_dir, decimate_dir, gate_dir = out_dir / "clean", out_dir / "decimate", out_dir / "gate"
    verdict = {"verdict": "fail", "passed": False, "reasons": []}
    try:
        start = time.monotonic()
        clean_report = clean_step(mesh_path, clean_dir, steps)
        clock["clean_mesh"] = time.monotonic() - start
        start = time.monotonic()
        decimate_report = decimate_step(clean_dir / "mesh.glb", decimate_dir, steps)
        clock["decimate"] = time.monotonic() - start
        start = time.monotonic()
        gate_report = gate_step(decimate_dir / "mesh.glb", image_path, gate_dir, steps)
        clock["gate"] = time.monotonic() - start
    except common.NormaliserError as exc:
        verdict["reasons"] = [f"could not finish: {exc}"]
        clean_report = decimate_report = gate_report = None
    else:
        verdict = {key: gate_report[key] for key in ("verdict", "passed", "reasons")}
    result = {"tool": TOOL, **verdict, "exit_code": EXIT_BY_VERDICT[verdict["verdict"]],
            "config_sha256": config_sha,
            "seconds": {name: round(value, 3) for name, value in clock.items()},
            "before": clean_report and {k: clean_report["before"][k] for k in ("faces", "pieces")},
            "after": decimate_report and {k: decimate_report["after"][k] for k in ("faces", "pieces")},
            "outputs": {"mesh": "decimate/mesh.glb", "gate_report": "gate/mesh-validation.json"} if gate_report else {}}
    seconds = sheet_step(image_path, decimate_dir / "mesh.glb" if gate_report else None, result, gate_report, steps, gate_dir)
    result["outputs"]["review_sheet"] = f"gate/{SHEET_NAME}"
    result["seconds"]["review_sheet"] = round(seconds, 3)
    return result


def run_single_step(name, mesh_path, image_path, out_dir, steps, config_sha):
    """One stage of the chain for the pipeline runner (docs/pipeline_files.md "Running"): the same functions
    as finish(), one stage per call. Returns the exit code. A clean or decimate step that cannot finish writes
    OUT_DIR/step-failed.json (its reasons) and exits 1; the gate step always writes its report and the sheet
    (the sheet's counts are the gate's own, since the earlier stages are other stages)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        if name == "clean_mesh":
            clean_step(mesh_path, out_dir, steps)
        elif name == "decimate":
            decimate_step(mesh_path, out_dir, steps)
        else:
            report = gate_step(mesh_path, image_path, out_dir, steps)
            counts = report["measures"] and {"faces": report["measures"]["faces"]["value"],
                                             "pieces": report["measures"]["pieces"]["value"]}
            result = {**{key: report[key] for key in ("verdict", "passed", "reasons")}, "before": None, "after": counts}
            sheet_step(image_path, mesh_path if report["measures"] else None, result, report, steps, out_dir)
            return EXIT_BY_VERDICT[report["verdict"]]
    except common.NormaliserError as exc:
        common.write_report(out_dir / "step-failed.json", {"tool": TOOL, "step": name, "reasons": [f"could not finish: {exc}"]})
        return 1
    return 0


def step_main(argv):
    parser = argparse.ArgumentParser(prog="mesh_finish.py step", description="One stage of the chain (clean_mesh, decimate, shape_gate).")
    parser.add_argument("name", choices=STEP_NAMES)
    parser.add_argument("mesh", type=Path)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--image", type=Path, help="the concept image (shape_gate only)")
    args = parser.parse_args(argv)
    try:
        if (args.name == "shape_gate") != (args.image is not None):
            raise ConfigError("--image is needed by shape_gate and by no other step")
        steps, config_sha = load(args.config)
        common.require_file(args.mesh, TOOL, "input mesh")
        if args.image:
            common.require_file(args.image, TOOL, "input image")
    except (ConfigError, common.NormaliserError) as exc:
        print(f"{TOOL}: {exc}", file=sys.stderr)
        return EXIT_USAGE
    return run_single_step(args.name, args.mesh, args.image, args.out_dir, steps, config_sha)


def main():
    if sys.argv[1:2] == ["step"]:
        return step_main(sys.argv[2:])
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mesh", type=Path)
    parser.add_argument("image", type=Path)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    try:
        steps, config_sha = load(args.config)
        common.require_file(args.mesh, TOOL, "input mesh")
        common.require_file(args.image, TOOL, "input image")
    except (ConfigError, common.NormaliserError) as exc:
        print(f"{TOOL}: {exc}", file=sys.stderr)
        return EXIT_USAGE
    result = finish(args.mesh, args.image, args.out_dir, steps, config_sha)
    common.write_report(args.out_dir / "finish.json", result)
    if result["reasons"]:
        print(f"mesh finish {result['verdict']}: " + "; ".join(result["reasons"]), file=sys.stderr)
    return result["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
