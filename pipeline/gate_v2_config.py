"""Load and validate the settings of the v2 mesh gate (plain Python, no numpy).

The one place that knows the shape of a v2 gate config file. Nothing here has a default: every
limit, range, margin, frame and budget comes from the file, and a missing or unknown key is an
error naming the file and the key (docs/gate_v2.md, "Every limit is a required key").

File shape (see pipeline/pipelines/examples/gate_v2.*.json):
    {"gate": {...the gate block...},
     "capture": {"view": {"camera": {"yaw": [from, to, step], "elevation": [from, to, step]}},
                 "background": {...optional background settings, pipeline/background_spec.py...}},
     "frame": {"drop_axis": 2, "transpose": false, "flip_x": false, "flip_y": true},
     "face_budget": 12000}
The result's "gate" holds the gate block plus face_budget, the single dict gate_v2.verdict reads, and
its "background" holds the validated background settings or None (the caller then names the background).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import background_spec

PROFILE = "v2"
RATIO_LIMITS = {  # limit key -> (measure name, "min" or "max")
    "min_silhouette_iou": ("silhouette_iou", "min"),
    "max_aspect_error": ("aspect_error", "max"),
    "max_deficit": ("deficit", "max"),
    "max_excess": ("excess", "max"),
    "min_depth_ratio": ("depth_ratio", "min"),
    "max_thin_sheet_share": ("thin_sheet_share", "max"),
}
GATE_KEYS = {"profile", "thin", "max_pieces", "review_margin", "orientation_margin", "search_seconds",
             *RATIO_LIMITS}
TOP_KEYS = {"gate", "capture", "frame", "face_budget"}
FRAME_KEYS = {"drop_axis", "transpose", "flip_x", "flip_y"}
CAMERA_AXES = ("yaw", "elevation")
MAX_YAW = 90          # degrees; beyond this the camera is behind the object
MAX_ELEVATION = 89    # degrees; 90 looks straight down and is the diagnostic's job
UNIT_KEYS = {"min_silhouette_iou", "max_aspect_error", "max_deficit", "max_excess", "max_thin_sheet_share",
             "review_margin", "orientation_margin"}


class ConfigError(ValueError):
    """A v2 gate config is missing a key or holds an invalid value."""


def _number(value):
    return type(value) in (int, float)


def _object(raw, keys, where, source):
    if not isinstance(raw, dict):
        raise ConfigError(f"{source}: {where} must be an object")
    for key in sorted(keys - set(raw)):
        raise ConfigError(f"{source}: missing key {where}.{key}")
    for key in sorted(set(raw) - keys):
        raise ConfigError(f"{source}: unknown key {where}.{key}")
    return raw


def _range(raw, axis, limit, source):
    where = f"capture.view.camera.{axis}"
    if not (isinstance(raw, list) and len(raw) == 3 and all(_number(v) for v in raw)):
        raise ConfigError(f"{source}: {where} must be [from, to, step]")
    start, stop, step = raw
    if not (-limit <= start <= stop <= limit):
        raise ConfigError(f"{source}: {where} needs -{limit} <= from <= to <= {limit}")
    if step <= 0:
        raise ConfigError(f"{source}: {where} step must be above 0 (use [0, 0, 1] for no tolerance)")
    return [start, stop, step]


def parse(raw, source, supplied=None):
    """Validate the decoded config RAW (SOURCE names it in messages); returns a normalised dict.

    SUPPLIED is for a caller that owns some of the top-level keys (mesh_finish owns "frame" and
    "face_budget"): those keys are taken from it, validated like any other, and RAW must not repeat
    them, so a fact still has one owner. Standalone files pass nothing and hold every key.
    """
    supplied = dict(supplied or {})
    if not set(supplied) <= {"frame", "face_budget"}:
        raise ValueError(f"supplied may only hold frame and face_budget, not {sorted(set(supplied) - {'frame', 'face_budget'})}")
    if isinstance(raw, dict):
        for key in sorted(set(supplied) & set(raw)):
            raise ConfigError(f"{source}: unknown key config.{key} (supplied by the caller, do not repeat it here)")
        raw = {**raw, **supplied}
    raw = _object(raw, TOP_KEYS, "config", source)
    gate = _object(raw["gate"], GATE_KEYS, "gate", source)
    if gate["profile"] != PROFILE:
        raise ConfigError(f"{source}: gate.profile must be \"{PROFILE}\"")
    if type(gate["thin"]) is not bool:
        raise ConfigError(f"{source}: gate.thin must be true or false")
    for key in UNIT_KEYS:
        if not (_number(gate[key]) and 0 <= gate[key] <= 1):
            raise ConfigError(f"{source}: gate.{key} must be a number from 0 to 1")
    if not (_number(gate["min_depth_ratio"]) and gate["min_depth_ratio"] >= 0):
        raise ConfigError(f"{source}: gate.min_depth_ratio must be a number of 0 or more")
    if not (_number(gate["search_seconds"]) and gate["search_seconds"] > 0):
        raise ConfigError(f"{source}: gate.search_seconds must be a number above 0")
    if not (type(gate["max_pieces"]) is int and gate["max_pieces"] >= 1):
        raise ConfigError(f"{source}: gate.max_pieces must be a whole number of 1 or more")
    capture = raw["capture"]
    background = None
    if isinstance(capture, dict) and "background" in capture:
        try:
            background = background_spec.parse(capture["background"])
        except background_spec.BackgroundError as exc:
            where = "capture.background" + (f".{exc.key}" if exc.key else "")
            raise ConfigError(f"{source}: {where} {exc.message}")
        capture = {k: v for k, v in capture.items() if k != "background"}
    view = _object(capture, {"view"}, "capture", source)["view"]
    camera = _object(_object(view, {"camera"}, "capture.view", source)["camera"], set(CAMERA_AXES),
                     "capture.view.camera", source)
    frame = _object(raw["frame"], FRAME_KEYS, "frame", source)
    if frame["drop_axis"] not in (0, 1, 2) or type(frame["drop_axis"]) is not int:
        raise ConfigError(f"{source}: frame.drop_axis must be 0, 1 or 2")
    for key in ("transpose", "flip_x", "flip_y"):
        if type(frame[key]) is not bool:
            raise ConfigError(f"{source}: frame.{key} must be true or false")
    if not (type(raw["face_budget"]) is int and raw["face_budget"] > 0):
        raise ConfigError(f"{source}: face_budget must be a whole number above 0")
    return {"gate": {**gate, "face_budget": raw["face_budget"]}, "frame": dict(frame), "background": background,
            "camera": {"yaw": _range(camera["yaw"], "yaw", MAX_YAW, source),
                       "elevation": _range(camera["elevation"], "elevation", MAX_ELEVATION, source)}}


def load(path):
    """Read and validate the config file at PATH; ConfigError names the file and key."""
    path = Path(path)
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"{path}: cannot read config: {exc}") from exc
    return parse(raw, path)
