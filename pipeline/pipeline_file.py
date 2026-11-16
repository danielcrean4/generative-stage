"""Read and validate a pipeline file (plain Python, no numpy; docs/pipeline_files.md is the format's owner).

    python3 -I pipeline/pipeline_file.py validate FILE...
    python3 -I pipeline/pipeline_file.py show FILE

load(path) returns a Pipeline of frozen dataclasses (so a field cannot be reassigned) whose `capture`,
`params`, `gate`, `retry` and `inputs` are the validated plain dicts from the file: treat them as read
only. Dataclasses over bare dicts because every consumer (show, resolve, the runner later) then names
fields the validator has proved exist. Validation is in this one module and every problem is a line
`FILE: POINTER: message`, the pointer being a JSON pointer (RFC 6901) to the offending key. All problems
are collected, not just the first.

TOOLS below is the one owner of the list of tool names a pipeline file may use, and of what each tool
takes: the adapter kind it runs (if any), inputs, outputs, the reads it needs and its param keys. A tool joins
the list by one entry here plus its runner. A stage of a tool with an adapter kind may name an adapter by id in
`model`; which ids exist is the machine config's business (adapter_config.py), checked when the stage runs, so a
pipeline file never holds a command and stays the same on every computer. Value checks reuse
normaliser_common, gate_settings and gate_v2_config. The key lists of the three numpy-bound normalisers
(normalize_image, normalize_mesh, decimate_mesh) are re-listed here because those scripts cannot be
imported without numpy; tests/test_pipeline_file.py compares them with the real SCHEMAs under the tools
interpreter. Nothing here has a default: a missing key is an error.
"""
import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import background_spec
import gate_settings
import gate_v2_config
import normaliser_common as common
import rig_gate

VERSION = 1
MAP_NAMES = ("basecolor", "normal", "height", "roughness", "metallic")  # the maps the `texture` tool writes
MAX_RETRIES = 2  # the most extra tries a gate's `retry` block may ask for
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}")
FILE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)*")
ALLOWED_READS = ("capture", "capture.background", "capture.view", "style.prompt", "style.palette",
                 "style.surface", "subject", "motif", "contract")
VERDICTS = ("fail", "review")
CAPTURE_OWNED = {"background_tolerance", "background", "background_color", "tolerance", "color", "camera", "yaw", "elevation"}
CONTRACT_OWNED = {"face_budget", "up_axis", "front_axis", "target_size", "scale_axis"}
INPUT_SUFFIX = {"image": ".png", "mesh": ".glb", "rig": ".json"}
GATE_BUDGET_STAND_IN = 1  # gate_v2_config.parse wants a face budget; the real one is the contract's, checked at resolve
GATE_TAG = "gate_v2_config"
ROOT = "/"
# The choices a pipeline file may declare for a person or an agent starting a run (see "Choices" in
# docs/pipeline_files.md). The names are a closed list: what each one means is fixed here and in the job module that
# acts on it, so a file can offer a few values and cannot invent a new way to reach the command line.
CHOICE_BOUNDS = {"seed": (0, 2**32 - 1), "candidates": (1, 8)}  # the whole-number choices and their widest range
CHOICE_PACKS = ("style", "motif")  # the choices that pick one of a few named packs
CHOICE_COLOUR = "hair_colour"  # a choice among a few "#rrggbb" colours, written to the subject's `hair_colour`
CHOICE_IMAGE = "start_image"  # an optional already-chosen image of the record to start the run from (see "Choices")
CHOICE_NAMES = (*CHOICE_PACKS, *CHOICE_BOUNDS, CHOICE_COLOUR, CHOICE_IMAGE)
MAX_PACK_OPTIONS = 20
HEX_COLOUR = re.compile(r"#[0-9a-fA-F]{6}")
STAGE_FILE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*/[A-Za-z0-9][A-Za-z0-9_.-]*")


class PipelineError(ValueError):
    """One or more problems, each a line `FILE: POINTER: message` (also in .problems)."""

    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("\n".join(self.problems))


def pointer(*parts):
    """A JSON pointer for PARTS (ROOT for none); '~' and '/' inside a key are escaped."""
    return "/" + "/".join(str(part).replace("~", "~0").replace("/", "~1") for part in parts) if parts else ROOT


class Checker:
    """Collects problems for one file; the first problem at a pointer wins."""

    def __init__(self, source):
        self.source = str(source)
        self.problems = []
        self._seen = set()

    def add(self, at, message):
        if at not in self._seen:
            self._seen.add(at)
            self.problems.append(f"{self.source}: {at}: {message}")

    def keys(self, raw, at, required, optional=()):
        """True when RAW is an object; reports missing and unknown keys under AT."""
        if not isinstance(raw, dict):
            self.add(at, "must be an object")
            return False
        for key in required:
            if key not in raw:
                self.add(at.rstrip("/") + "/" + key, "is required")
        for key in raw:
            if key not in required and key not in optional:
                self.add(at.rstrip("/") + "/" + key, "is not a known key (allowed: " + ", ".join([*required, *optional]) + ")")
        return True

    def value(self, at, check, value):
        """Run a normaliser_common style check (raises ValueError); True when it passes."""
        try:
            check(value)
            return True
        except ValueError as exc:
            self.add(at, str(exc))
            return False

    def raise_if_any(self):
        if self.problems:
            raise PipelineError(self.problems)


text = common.text


def identifier(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError("must be a short identifier (letters, digits, '_' and '-', starting with a letter or digit)")


def adapter_id(value):
    """A stage chooses an adapter by its id only; the command is in the machine config (docs/adapters.md)."""
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError("must be an adapter id from the machine config (letters, digits, '_' and '-'); a pipeline "
                         "file never holds a command")


def range_in(limit, name):
    def check(value):
        if not (isinstance(value, list) and len(value) == 3 and all(type(v) in (int, float) for v in value)):
            raise ValueError("must be [from, to, step]")
        start, stop, step = value
        if not -limit <= start <= stop <= limit:
            raise ValueError(f"needs -{limit} <= from <= to <= {limit} ({name})")
        if step <= 0:
            raise ValueError("step must be above 0 (use [0, 0, 1] for no tolerance)")
    return check


def image_side(value):
    if type(value) is not int or not 128 <= value <= 2048 or value % 16:
        raise ValueError("must be a multiple of 16 from 128 to 2048")


def whole_between(low, high):
    def check(value):
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f"must be a whole number from {low} to {high}")
    return check


def keep_share(value):
    if type(value) not in (int, float) or not 0 < value <= 1:
        raise ValueError("must be a number above 0 and at most 1")


CLIP_NAME = re.compile(r"[a-z][a-z0-9_]{0,39}")
MAX_CLIPS = 16


def clip_names(value):
    """Clip names joined by commas ("idle,walk"): one text, so it fills one argument of the adapter's command."""
    names = value.split(",") if isinstance(value, str) else None
    if not names or len(names) > MAX_CLIPS or not all(CLIP_NAME.fullmatch(n) for n in names) or len(set(names)) != len(names):
        raise ValueError(f"must be 1 to {MAX_CLIPS} distinct clip names joined by commas, each lower-case letters, "
                         "digits and '_' (for example \"idle,walk\")")


def orientation(value):
    """null, {"view": the four frame keys} or {"matrix": 3x3 numbers} (rotation property is checked by the tool)."""
    if value is None:
        return
    if not isinstance(value, dict) or len(value) != 1 or next(iter(value)) not in ("view", "matrix"):
        raise ValueError('must be null, {"view": ...} or {"matrix": ...}')
    kind, body = next(iter(value.items()))
    if kind == "matrix":
        if not (isinstance(body, list) and len(body) == 3 and all(
                isinstance(row, list) and len(row) == 3 and all(type(v) in (int, float) for v in row) for row in body)):
            raise ValueError("matrix must be three rows of three numbers")
        return
    if not isinstance(body, dict) or set(body) != gate_v2_config.FRAME_KEYS:
        raise ValueError("view must hold exactly " + ", ".join(sorted(gate_v2_config.FRAME_KEYS)))
    if type(body["drop_axis"]) is not int or body["drop_axis"] not in (0, 1, 2):
        raise ValueError("view.drop_axis must be 0, 1 or 2")
    for key in ("transpose", "flip_x", "flip_y"):
        if type(body[key]) is not bool:
            raise ValueError(f"view.{key} must be true or false")


@dataclass(frozen=True, eq=False)
class Tool:
    """What a pipeline file may say about one registered tool."""
    kind: object           # the adapter kind it runs (adapter_config.KINDS), or None for a tool without a model
    inputs: tuple          # input names, all required
    outputs: tuple         # the files the tool writes, listed exactly in the stage's outputs
    reads: tuple           # reads the tool cannot run without (a parent such as "capture" covers its parts)
    params: dict           # key -> value check; exactly these keys
    gate: bool = False     # the stage carries a gate (and may carry retry)
    sources: tuple = ()    # the tool's source files, relative to tools/; their hash is the tool's version in a cache key


ADAPTER_SOURCES = ("adapter_config.py", "adapter_run.py")  # a model stage's tool: the adapter machinery (the
# adapter's own program and weights are in the model identity of the key)
MASK_SOURCES = ("subject_mask.py", "background_spec.py", "normaliser_common.py")  # imported by every tool that cuts a subject out
FINISH_SOURCES = ("mesh_finish.py", "mesh_io.py", "normaliser_common.py")  # the runner runs the mesh chain through mesh_finish.py

def whole_from(low):
    def check(value):
        if type(value) is not int or value < low:
            raise ValueError(f"must be a whole number, {low} or more")
    return check


COLOUR_HEAD_PARAMS = {  # colour_head.SCHEMA without `background` (read from capture) and `hair_colour` (read from the subject)
    "working_faces": whole_from(100), "posterize": whole_from(0), "seen_facing": common.number_between(-1, 1), "depth_resolution": whole_from(8),
    "depth_tolerance": common.number_between(0, 1), "min_seen_share": common.number_between(0, 1), "horizontal_bias": common.number_between(0, 100),
    "toon_colours": whole_from(1), "broad_share": common.number_between(0, 1), "nape_height": common.number_between(0, 1), "temple_height": common.number_between(0, 1),
    "temple_side": common.number_between(0, 1), "ear_top": common.number_between(0, 1), "ear_side": common.number_between(0, 1), "hair_match": common.number_between(0, 2)}

TOOLS = {
    "concept": Tool("image", (), ("image.png",),
                    ("capture", "style.prompt", "subject", "motif"),
                    {"width": image_side, "height": image_side}, sources=ADAPTER_SOURCES),
    "matte": Tool(None, ("image",), ("matte.png", "matte.json"), ("capture.background",), {}, gate=True,
                  sources=("matte.py", "gate_settings.py", *MASK_SOURCES)),
    "mesh": Tool("image-to-mesh", ("image",), ("mesh.glb",), (),
                 {"steps": whole_between(1, 100), "depth": whole_between(6, 8)}, sources=ADAPTER_SOURCES),
    "texture": Tool("material", ("image",),
                    tuple(f"maps/{name}.png" for name in MAP_NAMES), (), {}, sources=ADAPTER_SOURCES),
    "normalize_image": Tool(None, ("image",), ("image.png",), ("capture.background",),
                            {"canvas_size": common.positive_int, "margin": common.non_negative_int,
                             "output_mode": common.one_of("rgba", "flat")},
                            sources=("normalize_image.py", *MASK_SOURCES)),
    "crop_image": Tool(None, ("image",), ("image.png",), ("capture.background",), {"keep_share": keep_share},
                       sources=("crop_image.py", *MASK_SOURCES)),
    "colour_head": Tool(None, ("mesh", "image"), ("mesh.glb",), ("capture.background", "subject"), COLOUR_HEAD_PARAMS,
                        sources=("colour_head.py", "mesh_decimate.py", "mesh_io.py", *MASK_SOURCES)),
    "normalize_mesh": Tool(None, ("mesh",), ("mesh.glb",), ("contract",),
                           {"weld_distance_share": common.share, "small_piece_area_share": common.share,
                            "orientation": orientation}, sources=("normalize_mesh.py", *FINISH_SOURCES)),
    "decimate_mesh": Tool(None, ("mesh",), ("mesh.glb",), ("contract",), {"preserve_topology": common.boolean},
                          sources=("decimate_mesh.py", "mesh_decimate.py", *FINISH_SOURCES)),
    "rig": Tool("rig", ("mesh",), ("rigged.glb", "rig.json"), (), {}, sources=ADAPTER_SOURCES),
    "rig_gate": Tool(None, ("mesh",), ("rig-validation.json",), (), {}, gate=True,
                     sources=("rig_gate.py", "glb_read.py")),
    "motion": Tool("motion", ("mesh", "rig"), ("animated.glb",), (), {"clips": clip_names}, sources=ADAPTER_SOURCES),
    "mesh_gates": Tool(None, ("mesh", "image"), ("mesh-validation.json",),
                       ("capture.background", "capture.view", "contract"), {}, gate=True,
                       sources=("mesh_gates.py", "gate_v2.py", "gate_v2_config.py", "gate_settings.py", "review_sheet.py",
                                "mesh_render.py", "mesh_decimate.py", "normalize_mesh.py", *MASK_SOURCES, *FINISH_SOURCES)),
}


@dataclass(frozen=True, eq=False)
class Stage:
    id: str
    label: str
    tool: str
    model: object      # str, or None for a tool without a model
    inputs: dict       # input name -> "<stage id>/<file>"
    reads: tuple
    params: dict
    gate: object       # dict or None
    retry: object      # dict or None
    outputs: tuple


@dataclass(frozen=True, eq=False)
class Pipeline:
    path: Path
    sha256: str
    version: int
    id: str
    name: str
    kind: str
    capture: dict
    stages: tuple
    choices: dict = field(default_factory=dict)  # choice name -> its declaration (CHOICE_NAMES); {} when none

    def stage(self, stage_id):
        return next(stage for stage in self.stages if stage.id == stage_id)


def _no_duplicates(pairs):
    seen = {}
    for key, value in pairs:
        if key in seen:
            raise ValueError(f"duplicate key '{key}'")
        seen[key] = value
    return seen


def read_json(path, what="file"):
    """(decoded value, sha256 of the bytes) of the JSON file at PATH; PipelineError names the file."""
    path = Path(path)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise PipelineError([f"{path}: {ROOT}: cannot read {what}: {exc.strerror or exc}"])
    try:
        return json.loads(data, object_pairs_hook=_no_duplicates), hashlib.sha256(data).hexdigest()
    except ValueError as exc:
        raise PipelineError([f"{path}: {ROOT}: {what} is not valid JSON: {exc}"])


def _scan_for(raw, names, at, found):
    """Every key named in NAMES at any depth, as pointers."""
    if isinstance(raw, dict):
        for key, value in raw.items():
            if key in names:
                found.append(at.rstrip("/") + "/" + key.replace("~", "~0").replace("/", "~1"))
            _scan_for(value, names, at.rstrip("/") + "/" + key.replace("~", "~0").replace("/", "~1"), found)
    elif isinstance(raw, list):
        for index, value in enumerate(raw):
            _scan_for(value, names, at.rstrip("/") + f"/{index}", found)
    return found


def _check_background(raw, check):
    """capture.background: the keys of its method (pipeline/background_spec.py owns them) plus color and words, all required."""
    at = "/capture/background"
    method = raw.get("method") if isinstance(raw, dict) else None
    known = method in background_spec.METHODS
    keys = background_spec.allowed_keys(method if known else background_spec.NEAR_WHITE)  # an unknown method is reported once, below
    if not check.keys(raw, at, keys):
        return
    if "method" in raw:
        check.value(f"{at}/method", background_spec.check_for(None, "method"), raw["method"])
    if known:
        for key in raw:
            if key in keys and key != "method":
                check.value(f"{at}/{key}", background_spec.check_for(method, key), raw[key])


def _check_capture(raw, check):
    """Validate the capture block; returns whether it has a (valid) view with a camera."""
    if not check.keys(raw, "/capture", ("background", "framing"), ("view",)):
        return False
    _check_background(raw.get("background"), check)
    if check.keys(raw.get("framing"), "/capture/framing", ("words",)) and "words" in raw["framing"]:
        check.value("/capture/framing/words", text, raw["framing"]["words"])
    if "view" not in raw:
        return False
    view = raw["view"]
    if not check.keys(view, "/capture/view", ("words", "camera")):
        return False
    if "words" in view:
        check.value("/capture/view/words", text, view["words"])
    camera = view.get("camera")
    if not check.keys(camera, "/capture/view/camera", gate_v2_config.CAMERA_AXES):
        return False
    limits = {"yaw": gate_v2_config.MAX_YAW, "elevation": gate_v2_config.MAX_ELEVATION}
    return all([check.value(f"/capture/view/camera/{axis}", range_in(limits[axis], axis), camera[axis])
                for axis in gate_v2_config.CAMERA_AXES if axis in camera]) and set(gate_v2_config.CAMERA_AXES) <= set(camera)


def _parse_gate_block(gate, camera, frame, face_budget, check, at):
    """Run gate_v2_config.parse and turn its dotted messages into pointers under AT; the parsed config or None."""
    try:
        return gate_v2_config.parse({"gate": gate, "capture": {"view": {"camera": camera}}}, GATE_TAG,
                                    supplied={"frame": dict(frame), "face_budget": face_budget})
    except gate_v2_config.ConfigError as exc:
        message = str(exc).removeprefix(f"{GATE_TAG}: ")
        named = re.search(r"\bgate\.(\w+)", message)
        check.add(at + "/" + named.group(1) if named else at, message)
        return None


def mesh_frame(pipeline_stages, index):
    """The frame {"view": ...} of the nearest normalize_mesh stage before INDEX, or None (stages as dicts or Stage objects)."""
    for stage in reversed(pipeline_stages[:index]):
        params = stage["params"] if isinstance(stage, dict) else stage.params
        tool = stage["tool"] if isinstance(stage, dict) else stage.tool
        view = (params.get("orientation") or {}).get("view") if isinstance(params, dict) and tool == "normalize_mesh" else None
        if view:
            return view
    return None


def gate_config(pipeline, stage, face_budget):
    """The parsed v2 gate config of mesh_gates STAGE with the contract's FACE_BUDGET (resolve calls this).

    Returns (config or None, problems); problems are lines for the pipeline file.
    """
    check = Checker(pipeline.path)
    index = pipeline.stages.index(stage)
    frame = mesh_frame(pipeline.stages, index)
    if frame is None:
        return None, [f"{pipeline.path}: {pointer('stages', index, 'gate')}: no frame for the gate (needs an earlier normalize_mesh stage "
                      'whose params.orientation is {"view": ...})']
    config = _parse_gate_block(stage.gate, pipeline.capture["view"]["camera"], frame, face_budget, check, pointer("stages", index, "gate"))
    return config, check.problems


def _check_stage(raw, i, ids, outputs_of, capture_has_view, check):
    """Validate stage I; returns the Stage or None."""
    at = pointer("stages", i)
    if not check.keys(raw, at, ("id", "label", "tool", "inputs", "reads", "params", "outputs"), ("model", "gate", "retry")):
        return None
    if "id" in raw and check.value(at + "/id", identifier, raw["id"]) and ids.index(raw["id"]) != i:
        check.add(at + "/id", f"duplicate stage id '{raw['id']}' (first used at {pointer('stages', ids.index(raw['id']))})")
    if "label" in raw:
        check.value(at + "/label", text, raw["label"])
    tool = TOOLS.get(raw.get("tool"))
    if "tool" in raw and tool is None:
        check.add(at + "/tool", f"unknown tool {raw['tool']!r} (registered: {', '.join(TOOLS)})")
    reads = raw.get("reads")
    if "reads" in raw:
        reads = _check_reads(reads, at + "/reads", tool, capture_has_view, check)
    if tool is None:
        return None
    if "model" in raw and tool.kind is None:
        check.add(at + "/model", f"tool '{raw['tool']}' takes no model")
    elif "model" in raw:
        check.value(at + "/model", adapter_id, raw["model"])
    _check_inputs(raw.get("inputs"), at + "/inputs", tool, i, ids, outputs_of, check) if "inputs" in raw else None
    _check_params(raw.get("params"), at + "/params", tool, reads or (), check) if "params" in raw else None
    gate = raw.get("gate")
    if tool.gate and "gate" not in raw:
        check.add(at + "/gate", f"is required for tool '{raw['tool']}' (it ends in pass, review or fail)")
    elif "gate" in raw and not tool.gate:
        check.add(at + "/gate", f"tool '{raw['tool']}' has no gate")
    elif "gate" in raw:
        _check_gate(raw["tool"], gate, at + "/gate", check)
    if "retry" in raw:
        _check_retry(raw["retry"], at + "/retry", tool, raw["tool"], i, ids, check)
    if "outputs" in raw and isinstance(raw["outputs"], list):
        outputs_of[i] = tuple(o for o in raw["outputs"] if isinstance(o, str))
        _check_outputs(raw["outputs"], at + "/outputs", tool, check)
    elif "outputs" in raw:
        check.add(at + "/outputs", "must be a list of file names")
    return raw


def _check_reads(reads, at, tool, capture_has_view, check):
    if not isinstance(reads, list):
        check.add(at, "must be a list")
        return None
    clean = []
    for j, name in enumerate(reads):
        if name not in ALLOWED_READS:
            check.add(f"{at}/{j}", f"{name!r} is not something a stage can read (allowed: {', '.join(ALLOWED_READS)})")
        elif name in clean:
            check.add(f"{at}/{j}", f"{name!r} is listed twice")
        else:
            if name == "capture.view" and not capture_has_view:
                check.add(f"{at}/{j}", "capture has no view (add capture.view, or do not read it)")
            clean.append(name)
    if tool:
        for need in tool.reads:
            if need not in clean and need.split(".")[0] not in clean:
                check.add(at, f"must include {need!r} (tool needs it)")
    return tuple(clean)


def _check_inputs(inputs, at, tool, i, ids, outputs_of, check):
    if not check.keys(inputs, at, tool.inputs):
        return
    for name in tool.inputs:
        if name not in inputs:
            continue
        value = inputs[name]
        where = f"{at}/{name}"
        parts = value.split("/", 1) if isinstance(value, str) else []
        if len(parts) != 2 or not all(parts):
            check.add(where, "must be '<stage id>/<file>'")
        elif parts[0] not in ids:
            check.add(where, f"names unknown stage '{parts[0]}'")
        elif ids.index(parts[0]) >= i:
            check.add(where, f"must name an earlier stage ('{parts[0]}' is not before this one)")
        elif parts[1] not in outputs_of.get(ids.index(parts[0]), ()):
            check.add(where, f"stage '{parts[0]}' does not list '{parts[1]}' in its outputs")
        elif not parts[1].endswith(INPUT_SUFFIX[name]):
            check.add(where, f"{'an' if name[0] in 'aeiou' else 'a'} {name} input must be a {INPUT_SUFFIX[name]} file")


def _check_params(params, at, tool, reads, check):
    if not isinstance(params, dict):
        check.add(at, "must be an object")
        return
    for key in params:
        if key in tool.params:
            continue
        if key in CAPTURE_OWNED and not any(r == "capture" or r.startswith("capture.") for r in reads):
            check.add(f"{at}/{key}", "is a capture value but the stage reads nothing from capture (declare reads capture.background, do not repeat it)")
        elif key in CAPTURE_OWNED:
            check.add(f"{at}/{key}", "is owned by capture; the stage reads it, do not repeat it in params")
        elif key in CONTRACT_OWNED:
            check.add(f"{at}/{key}", "belongs to the contract; the stage reads it (reads: contract)")
    check.keys(params, at, tuple(tool.params))
    for key, rule in tool.params.items():
        if key in params:
            check.value(f"{at}/{key}", rule, params[key])
    if "canvas_size" in tool.params and all(type(params.get(k)) is int for k in ("canvas_size", "margin")) \
            and 2 * params["margin"] >= params["canvas_size"]:
        check.add(f"{at}/margin", f"{params['margin']} leaves no room in canvas_size {params['canvas_size']} (2 * margin must be below it)")


def _check_gate(tool_name, gate, at, check):
    """The matte and rig gate blocks here; the mesh_gates block needs the frame and camera, so _check_gates does it."""
    if tool_name == "rig_gate":
        if check.keys(gate, at, rig_gate.GATE_KEYS):
            try:
                rig_gate.parse_gate(gate)
            except ValueError as exc:
                check.add(at, str(exc))
        return
    if tool_name != "matte":
        return
    wanted = tuple(k for k in gate_settings.MATTE_DEFAULTS if k != "tolerance")
    if check.keys(gate, at, wanted):
        try:
            gate_settings.matte_settings(gate)
        except ValueError as exc:
            check.add(at, str(exc))


def _check_retry(retry, at, tool, tool_name, i, ids, check):
    if not tool.gate:
        check.add(at, f"belongs to a gate stage; tool '{tool_name}' has no gate")
        return
    if not check.keys(retry, at, ("on", "restart_at", "max", "seed_step")):
        return
    if "on" in retry:
        on = retry["on"]
        if not (isinstance(on, list) and on and len(set(map(str, on))) == len(on) and all(v in VERDICTS for v in on)):
            check.add(at + "/on", "must be a non-empty list of distinct verdicts from: " + ", ".join(VERDICTS))
    if "restart_at" in retry:
        target = retry["restart_at"]
        if target not in ids:
            check.add(at + "/restart_at", f"names unknown stage {target!r}")
        elif ids.index(target) > i:
            check.add(at + "/restart_at", f"must not come after the gate stage ('{target}' is at {pointer('stages', ids.index(target))})")
    if "max" in retry:
        check.value(at + "/max", whole_between(1, MAX_RETRIES), retry["max"])
    if "seed_step" in retry:
        check.value(at + "/seed_step", common.positive_int, retry["seed_step"])


def _check_outputs(outputs, at, tool, check):
    if not all(isinstance(o, str) and FILE_NAME.fullmatch(o) for o in outputs) or len(set(outputs)) != len(outputs):
        check.add(at, "must be a list of distinct plain file names")
    elif sorted(outputs) != sorted(tool.outputs):
        check.add(at, "must list exactly: " + ", ".join(tool.outputs))


def validate(raw, source, sha256=""):
    """Validate decoded RAW; returns the Pipeline or raises PipelineError."""
    check = Checker(source)
    if not isinstance(raw, dict):
        check.add(ROOT, "must be an object")
        check.raise_if_any()
    for found in _scan_for(raw, {"face_budget"}, ROOT, []):
        check.add(found, "the face budget belongs to the contract (reads: contract), not to a pipeline file")
    check.keys(raw, ROOT, ("version", "id", "name", "kind", "capture", "stages"), ("choices",))
    if "version" in raw and raw["version"] != VERSION:
        check.add("/version", f"must be {VERSION}")
    for key, rule in (("id", identifier), ("name", text), ("kind", identifier)):
        if key in raw:
            check.value("/" + key, rule, raw[key])
    has_view = _check_capture(raw["capture"], check) if "capture" in raw else False
    if "choices" in raw:
        _check_choices(raw["choices"], check)
    stages = raw.get("stages")
    parsed = []
    if "stages" in raw:
        if not isinstance(stages, list) or not stages:
            check.add("/stages", "must be a non-empty list")
        else:
            ids = [s.get("id") if isinstance(s, dict) else None for s in stages]
            outputs_of = {}
            for i, stage in enumerate(stages):
                parsed.append(_check_stage(stage, i, ids, outputs_of, has_view, check))
            _check_gates(stages, parsed, raw.get("capture"), has_view, check)
    _check_start_image(raw.get("choices"), parsed, stages, check)
    check.raise_if_any()
    built = tuple(Stage(s["id"], s["label"], s["tool"], s.get("model"), dict(s["inputs"]), tuple(s["reads"]), dict(s["params"]),
                        s.get("gate"), s.get("retry"), tuple(s["outputs"])) for s in stages)
    return Pipeline(Path(source), sha256, raw["version"], raw["id"], raw["name"], raw["kind"], raw["capture"], built, dict(raw.get("choices", {})))


def _check_start_image(choices, parsed, stages, check):
    """The `start_image` choice must start at a later stage than the one that makes the image it supplies, and that image must be
    one of that stage's outputs; the run then starts at `start_at` with the saved file standing in for it."""
    spec = choices.get(CHOICE_IMAGE) if isinstance(choices, dict) else None
    if not isinstance(spec, dict) or not parsed or not isinstance(stages, list):
        return
    at = pointer("choices", CHOICE_IMAGE)
    ids = [s.get("id") if isinstance(s, dict) else None for s in stages]
    start, supplied = spec.get("start_at"), spec.get("supplies")
    if start not in ids:
        check.add(at + "/start_at", "must be the id of a stage of this pipeline")
        return
    if isinstance(supplied, str) and "/" in supplied:
        stage_id, filename = supplied.split("/", 1)
        if stage_id not in ids or ids.index(stage_id) >= ids.index(start):
            check.add(at + "/supplies", f"must name an output of a stage before '{start}'")
        elif not filename.endswith(INPUT_SUFFIX["image"]) or filename not in stages[ids.index(stage_id)].get("outputs", []):
            check.add(at + "/supplies", f"'{filename}' must be a picture the stage '{stage_id}' makes")


def _check_choices(raw, check):
    """`choices`: name -> declaration. A pack choice (style, motif) lists its `options` (ids) and a `default` among them;
    a number choice (seed, candidates) gives `min`, `max` inside the choice's widest range and a `default` between."""
    if not isinstance(raw, dict) or not raw:
        check.add(pointer("choices"), "must be an object with at least one choice")
        return
    for name, spec in raw.items():
        at = pointer("choices", name)
        if name not in CHOICE_NAMES:
            check.add(at, "is not a known choice (known: " + ", ".join(CHOICE_NAMES) + ")")
        elif name == CHOICE_COLOUR:
            if not check.keys(spec, at, ("label", "options"), ("default",)):
                continue
            options = spec.get("options")
            if "label" in spec:
                check.value(at + "/label", text, spec["label"])
            if not isinstance(options, list) or not 1 <= len(options) <= MAX_PACK_OPTIONS or len(set(map(str, options))) != len(options) \
                    or not all(isinstance(o, str) and HEX_COLOUR.fullmatch(o) for o in options):
                check.add(at + "/options", f'must be a list of 1 to {MAX_PACK_OPTIONS} different "#rrggbb" colours')
            elif "default" in spec and spec["default"] not in options:
                check.add(at + "/default", "must be one of the options")
        elif name == CHOICE_IMAGE:
            if not check.keys(spec, at, ("label", "slots", "start_at", "supplies")):
                continue
            if "label" in spec:
                check.value(at + "/label", text, spec["label"])
            slots = spec.get("slots")
            if not isinstance(slots, list) or not 1 <= len(slots) <= MAX_PACK_OPTIONS or len(set(map(str, slots))) != len(slots):
                check.add(at + "/slots", f"must be a list of 1 to {MAX_PACK_OPTIONS} different slot names")
            else:
                for i, slot in enumerate(slots):
                    check.value(f"{at}/slots/{i}", identifier, slot)
            if "start_at" in spec:
                check.value(at + "/start_at", identifier, spec["start_at"])
            if "supplies" in spec and (not isinstance(spec["supplies"], str) or not STAGE_FILE.fullmatch(spec["supplies"])):
                check.add(at + "/supplies", 'must be a stage output such as "concept/image.png"')
        elif name in CHOICE_PACKS:
            if not check.keys(spec, at, ("label", "options", "default")):
                continue
            if "label" in spec:
                check.value(at + "/label", text, spec["label"])
            options = spec.get("options")
            if not isinstance(options, list) or not 1 <= len(options) <= MAX_PACK_OPTIONS or len(set(map(str, options))) != len(options):
                check.add(at + "/options", f"must be a list of 1 to {MAX_PACK_OPTIONS} different ids")
            elif not all(check.value(f"{at}/options/{i}", identifier, o) for i, o in enumerate(options)):
                continue
            elif "default" in spec and spec["default"] not in options:
                check.add(at + "/default", "must be one of the options")
        else:
            if not check.keys(spec, at, ("label", "min", "max", "default")):
                continue
            if "label" in spec:
                check.value(at + "/label", text, spec["label"])
            low, high = CHOICE_BOUNDS[name]
            bounds = [spec.get(k) for k in ("min", "max", "default")]
            if not all(type(v) is int for v in bounds):
                check.add(at, "min, max and default must be whole numbers")
            elif not low <= bounds[0] <= bounds[2] <= bounds[1] <= high:
                check.add(at, f"needs {low} <= min <= default <= max <= {high}")


def resolve_choices(pipeline, given):
    """The values for a run: GIVEN (name -> value) checked against the pipeline's declaration, every other declared
    choice at its default. Raises ValueError("NAME: problem") for a name the pipeline does not declare or a value
    that is not one of its options or inside its range. Nothing outside the declaration passes."""
    values = {name: spec["default"] for name, spec in pipeline.choices.items() if "default" in spec}
    for name, value in given.items():
        spec = pipeline.choices.get(name)
        if spec is None:
            declared = ", ".join(pipeline.choices) or "none"
            raise ValueError(f"{name}: this pipeline offers no such choice (it offers: {declared})")
        if name in CHOICE_PACKS or name == CHOICE_COLOUR:
            if not isinstance(value, str) or value not in spec["options"]:
                raise ValueError(f"{name}: expected one of {', '.join(spec['options'])}")
        elif name == CHOICE_IMAGE:
            if not isinstance(value, str) or value not in spec["slots"]:
                raise ValueError(f"{name}: expected the slot of a chosen image: {', '.join(spec['slots'])}")
        elif type(value) is not int or not spec["min"] <= value <= spec["max"]:
            raise ValueError(f"{name}: expected a whole number from {spec['min']} to {spec['max']}")
        values[name] = value
    return values


def _check_gates(stages, parsed, capture, has_view, check):
    """Full v2 validation of each mesh_gates block (the face budget is a stand-in; resolve checks the real one)."""
    for i, stage in enumerate(parsed):
        if stage is None or stage.get("tool") != "mesh_gates" or "gate" not in stage:
            continue
        frame = mesh_frame(stages, i)
        at = pointer("stages", i, "gate")
        if frame is None:
            check.add(at, 'no frame for the gate (needs an earlier normalize_mesh stage whose params.orientation is {"view": ...})')
        elif has_view:
            _parse_gate_block(stage["gate"], capture["view"]["camera"], frame, GATE_BUDGET_STAND_IN, check, at)


def load(path):
    """Read and validate the pipeline file at PATH; PipelineError lists every problem with file and pointer."""
    raw, sha256 = read_json(path, "pipeline file")
    return validate(raw, path, sha256)


def show(pipeline):
    """The stages as a table for people: id, label, tool, inputs, reads, gate."""
    rows = [("id", "label", "tool", "inputs", "reads", "gate")]
    for stage in pipeline.stages:
        rows.append((stage.id, stage.label, stage.tool, ", ".join(f"{k}={v}" for k, v in stage.inputs.items()) or "-",
                     ", ".join(stage.reads) or "-", "yes" if stage.gate is not None else "no"))
    widths = [max(len(row[col]) for row in rows) for col in range(len(rows[0]))]
    lines = [f"{pipeline.id} ({pipeline.kind}): {pipeline.name}"]
    lines += ["  ".join(cell.ljust(width) for cell, width in zip(row, widths)).rstrip() for row in rows]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("validate").add_argument("files", nargs="+", type=Path)
    commands.add_parser("show").add_argument("file", type=Path)
    args = parser.parse_args(argv)
    if args.command == "show":
        try:
            print(show(load(args.file)))
        except PipelineError as exc:
            print(exc, file=sys.stderr)
            return 1
        return 0
    good = bad = 0
    for path in args.files:
        try:
            print(f"OK {path} {len(load(path).stages)} stages")
            good += 1
        except PipelineError as exc:
            print(exc)
            bad += len(exc.problems)
    print(f"PIPELINE_VALIDATE ok={good} problems={bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
