"""Tests for pipeline/pipeline_file.py (plain Python, no venv): every validation error with its exact message and
JSON pointer, the example files, the CLI. The combined line `PIPELINE_FILES cases=<n> ok=<n>` is printed by
test_pipeline_resolve (which runs after this module and shares TALLY)."""
import contextlib
import copy
import functools
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pipeline_file as pf  # noqa: E402
import venv_tool  # noqa: E402

EXAMPLES = ROOT / "pipelines" / "examples"
PROP = EXAMPLES / "prop.pipeline.json"
TALLY = {"cases": 0, "ok": 0}


def case(function):
    @functools.wraps(function)
    def wrapper(self):
        TALLY["cases"] += 1
        try:
            function(self)
        except unittest.SkipTest:
            TALLY["cases"] -= 1
            raise
        TALLY["ok"] += 1
    return wrapper


def prop():
    return json.loads(PROP.read_text())


def stage_of(raw, stage_id):
    return next(s for s in raw["stages"] if s["id"] == stage_id)


def problems_of(raw, name="p.json"):
    """The problem lines for the decoded RAW, as the loader reports them for a file called NAME."""
    try:
        pf.validate(raw, name)
    except pf.PipelineError as exc:
        return exc.problems
    return []


# (name, mutation of the prop example, exact problem line). File name in the line is p.json.
def _set(path, value):
    def mutate(raw):
        node = raw
        for part in path[:-1]:
            node = node[part]
        if value is DELETE:
            del node[path[-1]]
        else:
            node[path[-1]] = value
    return mutate


DELETE = object()
ADAPTER_ID = "must be an adapter id from the machine config (letters, digits, '_' and '-'); a pipeline file never holds a command"
GATE = ["stages", 6, "gate"]
BAD = [
    ("version", _set(["version"], 2), "p.json: /version: must be 1"),
    ("id", _set(["id"], "bad id"), "p.json: /id: must be a short identifier (letters, digits, '_' and '-', starting with a letter or digit)"),
    ("name", _set(["name"], ""), "p.json: /name: must be a non-empty string"),
    ("kind missing", _set(["kind"], DELETE), "p.json: /kind: is required"),
    ("unknown top key", _set(["extra"], 1), "p.json: /extra: is not a known key (allowed: version, id, name, kind, capture, stages, choices)"),
    ("background method", _set(["capture", "background", "method"], "green"), "p.json: /capture/background/method: must be one of: 'near_white', 'chroma_key'"),
    ("background colour", _set(["capture", "background", "color"], [1, 2]), "p.json: /capture/background/color: must be a list of three channel values [r, g, b]"),
    ("background tolerance", _set(["capture", "background", "tolerance"], 300), "p.json: /capture/background/tolerance: must be a whole number from 0 to 255"),
    ("background words", _set(["capture", "background", "words"], " "), "p.json: /capture/background/words: must be a non-empty string"),
    ("framing missing", _set(["capture", "framing"], DELETE), "p.json: /capture/framing: is required"),
    ("view words", _set(["capture", "view", "words"], 3), "p.json: /capture/view/words: must be a non-empty string"),
    ("camera range shape", _set(["capture", "view", "camera", "yaw"], [1, 2]), "p.json: /capture/view/camera/yaw: must be [from, to, step]"),
    ("camera range order", _set(["capture", "view", "camera", "elevation"], [10, -10, 5]), "p.json: /capture/view/camera/elevation: needs -89 <= from <= to <= 89 (elevation)"),
    ("camera step", _set(["capture", "view", "camera", "yaw"], [0, 0, 0]), "p.json: /capture/view/camera/yaw: step must be above 0 (use [0, 0, 1] for no tolerance)"),
    ("stages empty", _set(["stages"], []), "p.json: /stages: must be a non-empty list"),
    ("stage id duplicate", _set(["stages", 1, "id"], "concept"), "p.json: /stages/1/id: duplicate stage id 'concept' (first used at /stages/0)"),
    ("stage label", _set(["stages", 0, "label"], ""), "p.json: /stages/0/label: must be a non-empty string"),
    ("stage unknown key", _set(["stages", 0, "colour"], "red"), "p.json: /stages/0/colour: is not a known key (allowed: id, label, tool, inputs, reads, params, outputs, model, gate, retry)"),
    ("tool unknown", _set(["stages", 0, "tool"], "shell"), "p.json: /stages/0/tool: unknown tool 'shell' (registered: concept, matte, mesh, texture, normalize_image, crop_image, colour_head, normalize_mesh, decimate_mesh, rig, rig_gate, motion, mesh_gates)"),
    ("model a command", _set(["stages", 0, "model"], {"argv": ["/bin/sh", "-c", "true"]}), "p.json: /stages/0/model: " + ADAPTER_ID),
    ("model a command line", _set(["stages", 0, "model"], "/bin/sh -c true"), "p.json: /stages/0/model: " + ADAPTER_ID),
    ("model not taken", _set(["stages", 1, "model"], "standin-image"), "p.json: /stages/1/model: tool 'normalize_image' takes no model"),
    ("input from later stage", _set(["stages", 1, "inputs", "image"], "mesh/mesh.glb"), "p.json: /stages/1/inputs/image: must name an earlier stage ('mesh' is not before this one)"),
    ("input unknown stage", _set(["stages", 1, "inputs", "image"], "nope/image.png"), "p.json: /stages/1/inputs/image: names unknown stage 'nope'"),
    ("input file not an output", _set(["stages", 1, "inputs", "image"], "concept/other.png"), "p.json: /stages/1/inputs/image: stage 'concept' does not list 'other.png' in its outputs"),
    ("input shape", _set(["stages", 1, "inputs", "image"], "concept"), "p.json: /stages/1/inputs/image: must be '<stage id>/<file>'"),
    ("input missing", _set(["stages", 1, "inputs", "image"], DELETE), "p.json: /stages/1/inputs/image: is required"),
    ("input name unknown", _set(["stages", 1, "inputs", "mesh"], "concept/image.png"), "p.json: /stages/1/inputs/mesh: is not a known key (allowed: image)"),
    ("input wrong kind of file", _set(["stages", 6, "inputs", "image"], "mesh/mesh.glb"), "p.json: /stages/6/inputs/image: an image input must be a .png file"),
    ("read unknown", _set(["stages", 3, "reads"], ["weather"]), "p.json: /stages/3/reads/0: 'weather' is not something a stage can read (allowed: capture, capture.background, capture.view, style.prompt, style.palette, style.surface, subject, motif, contract)"),
    ("read twice", _set(["stages", 1, "reads"], ["capture.background", "capture.background"]), "p.json: /stages/1/reads/1: 'capture.background' is listed twice"),
    ("read needed", _set(["stages", 4, "reads"], []), "p.json: /stages/4/reads: must include 'contract' (tool needs it)"),
    ("params missing key", _set(["stages", 1, "params", "margin"], DELETE), "p.json: /stages/1/params/margin: is required"),
    ("params bad value", _set(["stages", 1, "params", "output_mode"], "cmyk"), "p.json: /stages/1/params/output_mode: must be one of: 'rgba', 'flat'"),
    ("params margin geometry", _set(["stages", 1, "params", "margin"], 256), "p.json: /stages/1/params/margin: 256 leaves no room in canvas_size 512 (2 * margin must be below it)"),
    ("params mesh depth", _set(["stages", 3, "params", "depth"], 9), "p.json: /stages/3/params/depth: must be a whole number from 6 to 8"),
    ("params concept size", _set(["stages", 0, "params", "width"], 500), "p.json: /stages/0/params/width: must be a multiple of 16 from 128 to 2048"),
    ("params concept steps", _set(["stages", 0, "params", "steps"], 4), "p.json: /stages/0/params/steps: is not a known key (allowed: width, height)"),
    ("params orientation", _set(["stages", 4, "params", "orientation"], {"view": {"drop_axis": 5}}), "p.json: /stages/4/params/orientation: view must hold exactly drop_axis, flip_x, flip_y, transpose"),
    ("face budget in params", _set(["stages", 5, "params", "face_budget"], 4000), "p.json: /stages/5/params/face_budget: the face budget belongs to the contract (reads: contract), not to a pipeline file"),
    ("face budget in gate", _set(GATE + ["face_budget"], 4000), "p.json: /stages/6/gate/face_budget: the face budget belongs to the contract (reads: contract), not to a pipeline file"),
    ("contract value in params", _set(["stages", 4, "params", "target_size"], 2), "p.json: /stages/4/params/target_size: belongs to the contract; the stage reads it (reads: contract)"),
    ("capture value without capture read", _set(["stages", 5, "params", "background_tolerance"], 236), "p.json: /stages/5/params/background_tolerance: is a capture value but the stage reads nothing from capture (declare reads capture.background, do not repeat it)"),
    ("capture value repeated", _set(["stages", 1, "params", "background_color"], [255, 255, 255]), "p.json: /stages/1/params/background_color: is owned by capture; the stage reads it, do not repeat it in params"),
    ("gate missing", _set(["stages", 2, "gate"], DELETE), "p.json: /stages/2/gate: is required for tool 'matte' (it ends in pass, review or fail)"),
    ("gate not allowed", _set(["stages", 1, "gate"], {}), "p.json: /stages/1/gate: tool 'normalize_image' has no gate"),
    ("matte gate key missing", _set(["stages", 2, "gate", "allow_border"], DELETE), "p.json: /stages/2/gate/allow_border: is required"),
    ("matte gate value", _set(["stages", 2, "gate", "min_coverage"], 0.95), "p.json: /stages/2/gate: matte min_coverage must not exceed max_coverage"),
    ("gate v2 value", _set(GATE + ["max_pieces"], 0), "p.json: /stages/6/gate/max_pieces: gate.max_pieces must be a whole number of 1 or more"),
    ("gate v2 key missing", _set(GATE + ["thin"], DELETE), "p.json: /stages/6/gate/thin: missing key gate.thin"),
    ("gate v2 key unknown", _set(GATE + ["mood"], 1), "p.json: /stages/6/gate/mood: unknown key gate.mood"),
    ("gate needs a frame", _set(["stages", 4, "params", "orientation"], None), "p.json: /stages/6/gate: no frame for the gate (needs an earlier normalize_mesh stage whose params.orientation is {\"view\": ...})"),
    ("retry on a stage without a gate", _set(["stages", 1, "retry"], {}), "p.json: /stages/1/retry: belongs to a gate stage; tool 'normalize_image' has no gate"),
    ("retry verdicts", _set(GATE[:2] + ["retry", "on"], ["pass"]), "p.json: /stages/6/retry/on: must be a non-empty list of distinct verdicts from: fail, review"),
    ("retry restart_at unknown", _set(["stages", 6, "retry", "restart_at"], "nope"), "p.json: /stages/6/retry/restart_at: names unknown stage 'nope'"),
    ("retry restart_at after the gate", _set(["stages", 2, "retry"], {"on": ["fail"], "restart_at": "mesh", "max": 1, "seed_step": 1}), "p.json: /stages/2/retry/restart_at: must not come after the gate stage ('mesh' is at /stages/3)"),
    ("retry max", _set(["stages", 6, "retry", "max"], 3), "p.json: /stages/6/retry/max: must be a whole number from 1 to 2"),
    ("retry seed_step", _set(["stages", 6, "retry", "seed_step"], 0), "p.json: /stages/6/retry/seed_step: must be a whole number above 0"),
    ("outputs wrong", _set(["stages", 0, "outputs"], ["picture.png"]), "p.json: /stages/0/outputs: must list exactly: image.png"),
]


def icon():
    return json.loads((EXAMPLES / "icon.pipeline.json").read_text())


ALLOWED_CHROMA = "method, color, tolerance, feather, luma_weight, holes, despill, words"
# (name, mutation of the icon example, exact problem line): the keys of the chroma_key background method
BAD_CHROMA = [
    ("feather missing", _set(["capture", "background", "feather"], DELETE), "p.json: /capture/background/feather: is required"),
    ("holes missing", _set(["capture", "background", "holes"], DELETE), "p.json: /capture/background/holes: is required"),
    ("tolerance range", _set(["capture", "background", "tolerance"], 500), "p.json: /capture/background/tolerance: must be a number from 0 to 360"),
    ("feather range", _set(["capture", "background", "feather"], 0), "p.json: /capture/background/feather: must be a number from 0.5 to 360"),
    ("luma_weight range", _set(["capture", "background", "luma_weight"], 2), "p.json: /capture/background/luma_weight: must be a number from 0 to 1"),
    ("holes type", _set(["capture", "background", "holes"], "yes"), "p.json: /capture/background/holes: must be true or false"),
    ("despill range", _set(["capture", "background", "despill"], -1), "p.json: /capture/background/despill: must be a number from 0 to 1"),
    ("unknown key", _set(["capture", "background", "gloss"], 1), f"p.json: /capture/background/gloss: is not a known key (allowed: {ALLOWED_CHROMA})"),
    ("method decides the keys", _set(["capture", "background", "method"], "near_white"),
     "p.json: /capture/background/feather: is not a known key (allowed: method, color, tolerance, words)"),
]


class PipelineFileTests(unittest.TestCase):
    @case
    def test_examples_validate(self):
        for path in sorted(EXAMPLES.glob("*.pipeline.json")):
            self.assertEqual(pf.load(path).path, path)
        self.assertEqual(sorted(p.name for p in EXAMPLES.glob("*.pipeline.json")), ["character.pipeline.json", "concept.pipeline.json", "icon.pipeline.json", "mesh.pipeline.json", "prop.pipeline.json"])

    @case
    def test_choices_are_declared_closed_and_checked_with_their_defaults(self):
        pipeline = pf.load(PROP)
        self.assertEqual(set(pipeline.choices), {"style", "motif", "seed", "candidates"})
        self.assertEqual(pf.resolve_choices(pipeline, {}), {"style": "clay", "motif": "repair_shop", "seed": 1, "candidates": 1})
        self.assertEqual(pf.resolve_choices(pipeline, {"style": "vinyl_toy", "seed": 9, "candidates": 3})["style"], "vinyl_toy")
        for given, said in (({"style": "../x"}, "style: expected one of clay, vinyl_toy"), ({"style": 3}, "style: expected one of"),
                            ({"seed": -1}, "seed: expected a whole number from 0 to 4294967295"), ({"seed": True}, "seed: expected a whole"),
                            ({"seed": "1"}, "seed: expected a whole"), ({"candidates": 9}, "candidates: expected a whole number from 1 to 4"),
                            ({"width": 5}, "width: this pipeline offers no such choice")):
            with self.subTest(given), self.assertRaises(ValueError) as caught:
                pf.resolve_choices(pipeline, given)
            self.assertIn(said, str(caught.exception))
        none = prop()
        del none["choices"]
        self.assertEqual(pf.validate(none, "p.json").choices, {})
        with self.assertRaises(ValueError):
            pf.resolve_choices(pf.validate(none, "p.json"), {"seed": 1})

    @case
    def test_bad_choice_declarations_report_their_exact_line(self):
        def edit(change):
            raw = prop()
            change(raw["choices"])
            return problems_of(raw)

        self.assertIn("p.json: /choices/colour: is not a known choice (known: style, motif, seed, candidates, hair_colour, start_image)", edit(lambda c: c.update(colour={})))
        self.assertIn("p.json: /choices/style/options: must be a list of 1 to 20 different ids", edit(lambda c: c["style"].update(options=[])))
        self.assertIn("p.json: /choices/style/options/0: must be a short identifier (letters, digits, '_' and '-', starting with a letter or digit)",
                      edit(lambda c: c["style"].update(options=["../x"], default="../x")))
        self.assertIn("p.json: /choices/style/default: must be one of the options", edit(lambda c: c["style"].update(default="other")))
        self.assertIn("p.json: /choices/seed: needs 0 <= min <= default <= max <= 4294967295", edit(lambda c: c["seed"].update(default=-1)))
        self.assertIn("p.json: /choices/candidates: needs 1 <= min <= default <= max <= 8", edit(lambda c: c["candidates"].update(max=99)))
        self.assertIn("p.json: /choices/seed/step: is not a known key (allowed: label, min, max, default)", edit(lambda c: c["seed"].update(step=2)))
        self.assertIn("p.json: /choices: must be an object with at least one choice", problems_of({**prop(), "choices": {}}))

    @case
    def test_a_colour_choice_and_an_image_to_start_from_are_declared_checked_and_optional(self):
        head = pf.load(EXAMPLES.parent / "head.json")
        self.assertNotIn("hair_colour", pf.resolve_choices(head, {}))  # optional: unset leaves the head's hair to the picture
        self.assertEqual(pf.resolve_choices(head, {"hair_colour": "#1c1a19"})["hair_colour"], "#1c1a19")
        with self.assertRaises(ValueError) as caught:
            pf.resolve_choices(head, {"hair_colour": "#ffffff"})
        self.assertIn("hair_colour: expected one of #4d331f", str(caught.exception))
        mesh = pf.load(EXAMPLES / "mesh.pipeline.json")
        self.assertNotIn("start_image", pf.resolve_choices(mesh, {}))  # no default: a run starts at the first stage
        self.assertEqual(pf.resolve_choices(mesh, {"start_image": "main"})["start_image"], "main")
        for bad in ("../x", "mesh", 3):
            with self.subTest(bad), self.assertRaises(ValueError) as caught:
                pf.resolve_choices(mesh, {"start_image": bad})
            self.assertIn("start_image: expected the slot of a chosen image: main", str(caught.exception))

    @case
    def test_bad_colour_and_start_image_declarations_report_their_exact_line(self):
        def edit(name, change):
            raw = json.loads((EXAMPLES / "mesh.pipeline.json").read_text())
            raw["choices"]["hair_colour"] = {"label": "Hair", "options": ["#112233"], "default": "#112233"}
            change(raw["choices"][name])
            return problems_of(raw)

        self.assertIn('p.json: /choices/hair_colour/options: must be a list of 1 to 20 different "#rrggbb" colours',
                      edit("hair_colour", lambda c: c.update(options=["red"], default="red")))
        self.assertIn("p.json: /choices/hair_colour/default: must be one of the options", edit("hair_colour", lambda c: c.update(default="#445566")))
        self.assertNotIn("p.json: /choices/hair_colour", "\n".join(edit("hair_colour", lambda c: c.pop("default"))))
        self.assertIn("p.json: /choices/start_image/start_at: must be the id of a stage of this pipeline",
                      edit("start_image", lambda c: c.update(start_at="nowhere")))
        self.assertIn("p.json: /choices/start_image/supplies: must name an output of a stage before 'tidy_image'",
                      edit("start_image", lambda c: c.update(supplies="mesh/mesh.glb")))
        self.assertIn("p.json: /choices/start_image/supplies: 'matte.png' must be a picture the stage 'concept' makes",
                      edit("start_image", lambda c: c.update(supplies="concept/matte.png")))
        self.assertIn("p.json: /choices/start_image/slots: must be a list of 1 to 20 different slot names",
                      edit("start_image", lambda c: c.update(slots=[])))
        self.assertIn("p.json: /choices/start_image/default: is not a known key (allowed: label, slots, start_at, supplies)",
                      edit("start_image", lambda c: c.update(default="main")))

    @case
    def test_every_bad_file_reports_its_exact_line(self):
        for name, mutate, expected in BAD:
            with self.subTest(name):
                raw = prop()
                mutate(raw)
                self.assertIn(expected, problems_of(raw))
        TALLY["cases"] += len(BAD) - 1  # each table row is a case
        TALLY["ok"] += len(BAD) - 1

    @case
    def test_chroma_background_keys_report_their_exact_line(self):
        for name, mutate, expected in BAD_CHROMA:
            with self.subTest(name):
                raw = icon()
                mutate(raw)
                self.assertIn(expected, problems_of(raw))
        TALLY["cases"] += len(BAD_CHROMA) - 1
        TALLY["ok"] += len(BAD_CHROMA) - 1

    @case
    def test_all_problems_are_reported_not_just_the_first(self):
        raw = prop()
        raw["version"] = 2
        raw["stages"][0]["label"] = ""
        self.assertEqual(len(problems_of(raw)), 2)

    @case
    def test_the_good_example_has_no_problems(self):
        self.assertEqual(problems_of(prop()), [])

    @case
    def test_icon_has_no_view_and_nothing_reads_it(self):
        raw = json.loads((EXAMPLES / "icon.pipeline.json").read_text())
        self.assertNotIn("view", raw["capture"])
        raw["stages"][1]["reads"].append("capture.view")
        self.assertIn("p.json: /stages/1/reads/1: capture has no view (add capture.view, or do not read it)", problems_of(raw))

    @case
    def test_file_level_errors_name_the_file(self):
        with tempfile.TemporaryDirectory() as folder:
            missing = Path(folder) / "nope.json"
            with self.assertRaises(pf.PipelineError) as ctx:
                pf.load(missing)
            self.assertTrue(ctx.exception.problems[0].startswith(f"{missing}: /: cannot read pipeline file:"))
            broken = Path(folder) / "broken.json"
            broken.write_text("{")
            with self.assertRaises(pf.PipelineError) as ctx:
                pf.load(broken)
            self.assertTrue(ctx.exception.problems[0].startswith(f"{broken}: /: pipeline file is not valid JSON:"))
            duplicate = Path(folder) / "dup.json"
            duplicate.write_text('{"version": 1, "version": 1}')
            with self.assertRaises(pf.PipelineError) as ctx:
                pf.load(duplicate)
            self.assertIn("duplicate key 'version'", ctx.exception.problems[0])

    @case
    def test_loaded_pipeline_is_frozen_and_complete(self):
        pipeline = pf.load(PROP)
        self.assertEqual([s.id for s in pipeline.stages], ["concept", "tidy_image", "matte", "mesh", "clean_mesh", "decimate", "shape_gate"])
        with self.assertRaises(Exception):
            pipeline.id = "other"
        self.assertEqual(pipeline.stage("shape_gate").retry["restart_at"], "mesh")
        self.assertEqual(len(pipeline.sha256), 64)

    @case
    def test_cli_validate_and_show(self):
        with tempfile.TemporaryDirectory() as folder:
            bad = Path(folder) / "bad.json"
            raw = prop()
            raw["version"] = 9
            bad.write_text(json.dumps(raw))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = pf.main(["validate", str(PROP), str(bad)])
            lines = out.getvalue().splitlines()
            self.assertEqual(code, 1)
            self.assertEqual(lines[0], f"OK {PROP} 7 stages")
            self.assertEqual(lines[1], f"{bad}: /version: must be 1")
            self.assertEqual(lines[-1], "PIPELINE_VALIDATE ok=1 problems=1")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(pf.main(["validate", str(PROP)]), 0)
        self.assertEqual(out.getvalue().splitlines()[-1], "PIPELINE_VALIDATE ok=1 problems=0")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(pf.main(["show", str(PROP)]), 0)
        table = out.getvalue().splitlines()
        self.assertTrue(table[1].split()[:6] == ["id", "label", "tool", "inputs", "reads", "gate"])
        self.assertTrue(table[-1].rstrip().endswith("yes"))
        self.assertTrue(table[2].rstrip().endswith("no"))

    @case
    def test_tool_key_lists_match_the_real_tools(self):
        """The loader re-lists the numpy-bound normalisers' keys; the real SCHEMAs must agree (under the tools interpreter)."""
        venv_tool.require_venv(self)
        code = ("import sys, json; sys.path.insert(0, sys.argv[1]); import normalize_image, normalize_mesh, decimate_mesh;"
                "print(json.dumps({'normalize_image': sorted(normalize_image.SCHEMA), 'normalize_mesh': sorted(normalize_mesh.SCHEMA),"
                "'decimate_mesh': sorted(decimate_mesh.SCHEMA)}))")
        real = json.loads(venv_tool.run_code(code, TOOLS))
        supplied = {"normalize_image": {"background_tolerance", "background", "background_color"},
                    "normalize_mesh": {"up_axis", "front_axis", "target_size", "scale_axis"},
                    "decimate_mesh": {"face_budget"}}
        for tool, keys in real.items():
            self.assertEqual(sorted(set(pf.TOOLS[tool].params) | supplied[tool]), keys, tool)
        self.assertEqual(pf.TOOLS["normalize_mesh"].params["orientation"].__name__, "orientation")
