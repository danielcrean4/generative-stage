"""adapter_config.py: loading and checking adapter entries, configured entries turned into commands, the worked
example of docs/adapters.md, placeholders and the model identity. No model runs: configured commands are rendered and
recorded, never started; the dummy example (no model) is run for real."""
import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))
import adapter_config as ac  # noqa: E402
import adapter_run  # noqa: E402
import machine  # noqa: E402
import pipeline_file as pf  # noqa: E402
import pipeline_resolve as pr  # noqa: E402
import pipeline_run as run  # noqa: E402

DATA = HERE / "fixtures" / "pipeline_files"
PROP = ROOT / "pipelines" / "examples" / "prop.pipeline.json"
EXAMPLES = REPO / "adapters" / "examples"
DOC = REPO / "docs" / "adapters.md"
OFFLINE_NETWORK = "deny"
ENTRY = {"id": "a", "kind": "image", "argv": ["/bin/prog", "{prompt}"], "sandbox": {"network": "allow"}, "licence": "MIT"}


def prop_job():
    return pr.resolve(pf.load(PROP), pr.load_subject(DATA / "subject.json"), pr.load_motif(DATA / "motif.json"),
                      pr.load_style(DATA / "styles" / "clay"), pr.load_contract(DATA / "contract.json"), 42)


def stage_of(job, tool):
    return next(stage for stage in job["stages"] if stage["tool"] == tool)


class Recorder:
    """Stands in for local_run.execute: records what would run and writes the expected output."""

    def __init__(self):
        self.calls = []

    def __call__(self, argv, log, timeout, network="allow", env=None, cwd=None):
        self.calls.append({"argv": [str(a) for a in argv], "timeout": timeout, "network": network, "env": env, "cwd": cwd})


class FakeGpu:
    held = 0

    def hold(self):
        self.held += 1


class Temp(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name).resolve()
        env = patch.dict(os.environ, {"GENSTAGE_IDENTITY_CACHE": str(self.dir / "identity-cache.json")})
        env.start()
        self.addCleanup(env.stop)

    def config(self, raw, name="machine.json"):
        file = self.dir / name
        file.write_text(json.dumps(raw))
        return file

    def adapters(self, raw):
        return ac.from_machine({machine.CONFIG_ENV: str(self.config(raw))}, self.dir)


class DefaultsTests(Temp):
    def test_a_new_install_uses_the_stand_in_for_every_kind_it_has(self):
        for found in (self.adapters({}), ac.from_machine({machine.CONFIG_ENV: ""}, self.dir)):  # empty file; no file
            self.assertEqual(found.defaults, {"image": "standin-image", "image-to-mesh": "standin-mesh",
                                              "text": "standin-text", "review": "standin-review",
                                              "rig": "standin-rig", "motion": "standin-motion", "rules": "rules-kit",
                                              "render": "standin-render", "measure": "standin-measure"})
            self.assertTrue(all(e.sandbox == "allow" and e.requires[0] == "cpu" and not e.gpu
                                for e in found.entries.values()))

    def test_explicit_defaults_win_and_must_name_an_adapter_of_their_kind(self):
        raw = {"adapters": [ENTRY], "defaults": {"image": "a"}}
        self.assertEqual(self.adapters(raw).defaults["image"], "a")
        for defaults, message in (({"image": "nope"}, "defaults.image: no adapter 'nope'"),
                                  ({"image-to-mesh": "a"}, "is of kind 'image'"),
                                  ({"video": "a"}, "'video' is not a kind")):
            with self.subTest(defaults=defaults), self.assertRaisesRegex(ac.AdapterError, message):
                self.adapters({**raw, "defaults": defaults})


class ConfiguredEntryTests(Temp):
    """Entries in the machine config's `adapters` list become the commands the runners start: argv, environment,
    network denial, timeout and the GPU lock exactly as written."""

    def setUp(self):
        super().setUp()
        self.weights = self.dir / "weights"
        for part in ("encoder", "decoder"):
            (self.weights / part).mkdir(parents=True)
            (self.weights / part / "w.bin").write_bytes(part.encode())
        self.program = self.dir / "venv" / "bin" / "make-image"
        self.program.parent.mkdir(parents=True)
        self.program.write_text("#!/bin/sh\n")
        self.python = self.dir / "venv" / "bin" / "python"
        self.python.write_text("")
        self.script = self.dir / "mesh_runner.py"
        self.script.write_text("# a mesh runner\n")
        offline = {"sandbox": {"network": "deny"}, "gpu": True, "licence": "MIT (a test entry)"}
        self.file = self.config({"gpu_lock": str(self.dir / "lock"), "defaults": {
            "image": "img", "image-to-mesh": "mesh", "material": "mat"}, "adapters": [
            {**offline, "id": "img", "kind": "image", "timeout_seconds": 1800,
             "argv": [str(self.program), "--model", str(self.weights), "--prompt", "{prompt}", "--seed", "{seed}",
                      "--width", "{width}", "--height", "{height}", "--output", "{output}"],
             "model": {"name": "test image model", "weights": str(self.weights)}},
            {**offline, "id": "mesh", "kind": "image-to-mesh", "timeout_seconds": 3600,
             "argv": [str(self.python), str(self.script), "{image}", "{output}", "--seed", "{seed}",
                      "--steps", "{params.steps}", "--depth", "{params.depth}"],
             "env": {"MODEL_HOME": str(self.weights)}, "model": {"name": "test mesh model", "weights": str(self.weights)}},
            {**offline, "id": "mat", "kind": "material", "timeout_seconds": 3600,
             "argv": [str(self.python), "-I", str(self.script), "{image}", "{out_dir}/maps", "--seed", "{seed}"]}]})
        env = patch.dict(os.environ, {machine.CONFIG_ENV: str(self.file)})
        env.start()
        self.addCleanup(env.stop)

    def run_stage(self, tool, inputs):
        job, recorder, gpu = prop_job(), Recorder(), FakeGpu()
        stage = stage_of(job, tool) if tool != "texture" else {
            "id": "material", "tool": "texture", "params": {}, "reads": {}}
        folder = self.dir / tool
        folder.mkdir()
        (folder / "step.log").write_text("")
        with patch.object(adapter_run.local_run, "execute", recorder), \
                patch.object(adapter_run.host, "unmet", return_value=[]):
            run.default_runners(job, {}, gpu)[tool].run(stage, inputs, folder, 42)
        self.assertEqual(gpu.held, 1)  # a gpu entry holds the machine GPU lock
        return stage, folder, recorder.calls[0]

    def test_the_named_defaults_win_over_the_stand_ins(self):
        found = ac.from_machine()
        self.assertEqual((found.defaults["image"], found.defaults["image-to-mesh"], found.defaults["material"]),
                         ("img", "mesh", "mat"))
        self.assertEqual(found.defaults["text"], "standin-text")

    def test_the_image_command_is_the_entry_filled_in(self):
        stage, folder, call = self.run_stage("concept", {})
        self.assertEqual(call["argv"], [str(self.program), "--model", str(self.weights), "--prompt", stage["prompt"],
                                        "--seed", "42", "--width", "512", "--height", "512", "--output",
                                        str(folder / "image.png")])
        self.assertEqual((call["timeout"], call["network"], call["env"], call["cwd"]), (1800, OFFLINE_NETWORK, {}, None))

    def test_the_mesh_command_takes_the_stage_params(self):
        image = self.dir / "image.png"
        stage, folder, call = self.run_stage("mesh", {"image": image})
        self.assertEqual(call["argv"], [str(self.python), str(self.script), str(image), str(folder / "mesh.glb"),
                                        "--seed", "42", "--steps", "50", "--depth", "8"])
        self.assertEqual((call["timeout"], call["network"], call["env"]), (3600, OFFLINE_NETWORK,
                                                                           {"MODEL_HOME": str(self.weights)}))

    def test_the_material_command_writes_maps_under_the_stage_folder(self):
        image = self.dir / "image.png"
        _, folder, call = self.run_stage("texture", {"image": image})
        self.assertEqual(call["argv"], [str(self.python), "-I", str(self.script), str(image), str(folder / "maps"),
                                        "--seed", "42"])
        self.assertEqual((call["timeout"], call["network"]), (3600, OFFLINE_NETWORK))

    def test_keys_that_named_one_model_are_refused(self):
        for key in ("image_model", "mesh_repo"):
            with self.subTest(key=key), self.assertRaisesRegex(ac.AdapterError, f"unknown key.*{key}"):
                self.adapters({key: "/x"})

    def test_the_identity_hashes_the_weights_and_the_program(self):
        entry = ac.from_machine().entries["img"]
        first = ac.identity(entry)
        self.assertEqual(first["adapter"], "img")
        self.assertIn("0", first["files_sha256"])  # the program
        (self.weights / "decoder" / "w.bin").write_bytes(b"changed")
        self.assertNotEqual(ac.identity(entry)["weights_sha256"], first["weights_sha256"])
        self.program.write_text("#!/bin/sh\n# another build\n")
        self.assertNotEqual(ac.identity(entry)["files_sha256"], first["files_sha256"])

    def test_missing_weights_name_the_adapter(self):
        entry = ac.from_machine().entries["mesh"]
        for part in ("encoder", "decoder"):
            (self.weights / part / "w.bin").unlink()
            (self.weights / part).rmdir()
        self.weights.rmdir()
        with self.assertRaisesRegex(ac.AdapterError, "'mesh'.*does not exist"):
            ac.identity(entry)


class ExampleTests(Temp):
    """The worked example (adapters/examples/dummy) and the entry printed in docs/adapters.md are the same, valid, and
    run for real: no model, the standard library only."""

    def example(self):
        return json.loads((EXAMPLES / "dummy" / "adapters.json").read_text())

    def test_only_the_dummy_example_ships_and_every_entry_has_a_licence_note(self):
        self.assertEqual(sorted(path.parent.name for path in EXAMPLES.glob("*/adapters.json")), ["dummy"])
        entries = self.example()["adapters"] + json.loads(ac.STANDIN_FILE.read_text())["adapters"]
        for raw in entries:
            with self.subTest(id=raw["id"]):
                self.assertGreater(len(ac.parse_entry(raw, "example").licence), 20)

    def test_the_doc_shows_the_example_entry(self):
        text = DOC.read_text()
        start = text.index("```json\n", text.index("## A worked example")) + len("```json\n")
        shown = json.loads(text[start:text.index("```", start)])
        self.assertEqual(shown, self.example())

    def test_the_example_runs_and_writes_its_output_and_identity(self):
        found = self.adapters(self.example())
        self.assertEqual(found.defaults["image"], "dummy-image")
        folder = self.dir / "concept"
        folder.mkdir()
        data = {"prompt": "a lamp --output /etc/passwd", "seed": 7, "width": 64, "height": 32,
                "output": str(folder / "image.png"), "out_dir": str(folder)}
        argv, env, cwd = ac.command(found.pick(None, "image"), data)
        adapter_run.local_run.execute(argv, folder / "step.log", 60, env=env, cwd=cwd)  # the sandbox: test_adapter_run
        self.assertEqual((folder / "image.png").read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(adapter_run.reported(folder), {"name": "dummy-image", "version": 1})
        self.assertRegex((folder / "step.log").read_text(), run.MESH_TIMES.pattern)


class EntryCheckTests(unittest.TestCase):
    def refused(self, changes, message):
        raw = copy.deepcopy(ENTRY)
        for key, value in changes.items():
            if value is None:
                raw.pop(key)
            else:
                raw[key] = value
        with self.assertRaises(ac.AdapterError) as raised:
            ac.parse_entry(raw, "machine.json: adapters[0]")
        self.assertIn("machine.json: adapters[0]", str(raised.exception))
        self.assertIn(message, str(raised.exception))

    def test_loud_specific_errors(self):
        cases = [
            ({"licence": None}, "key 'licence' is required"),
            ({"shell": True}, "key 'shell' is not known"),
            ({"id": "has space"}, "key 'id'"),
            ({"kind": "video"}, "'video' is not a kind"),
            ({"argv": "/bin/sh -c 'x'"}, "never a shell line"),
            ({"argv": []}, "never a shell line"),
            ({"argv": ["{prompt}"]}, "argv[0]: unknown placeholder {prompt}"),
            ({"argv": ["/bin/prog", "{nope}"]}, "argv[1]: unknown placeholder {nope}"),
            ({"argv": ["/bin/prog", "{image}"]}, "unknown placeholder {image}"),  # image takes no input image
            ({"argv": ["/bin/prog", "{prompt"]}, "a lone '{'"),
            ({"env": {"lower": "x"}}, "upper-case"),
            ({"env": {"PROMPT": "{prompt}"}}, "env PROMPT: unknown placeholder {prompt}"),
            ({"cwd": "{out_dir}"}, "key 'cwd': unknown placeholder {out_dir}"),
            ({"requires": ["quantum"]}, "unknown capability quantum"),
            ({"sandbox": {"network": "open"}}, "key 'sandbox'"),
            ({"sandbox": None}, "key 'sandbox' is required"),
            ({"timeout_seconds": 0}, "key 'timeout_seconds'"),
            ({"gpu": "yes"}, "key 'gpu'"),
            ({"model": {"weights": "/w"}}, "key 'model'"),
        ]
        for changes, message in cases:
            with self.subTest(changes=changes):
                self.refused(changes, message)

    def test_ids_are_unique_and_built_in_ids_are_taken(self):
        for listed, message in (([ENTRY, ENTRY], "adapters[1]: id 'a' is already defined"),
                                ([{**ENTRY, "id": "standin-image"}], "already defined (built in)")):
            with self.subTest(message=message), self.assertRaises(ac.AdapterError) as raised:
                ac.parse({"adapters": listed}, "machine.json")
            self.assertIn(message, str(raised.exception))

    def test_every_kind_loads(self):
        for kind in ac.KINDS:
            self.assertEqual(ac.parse_entry({**ENTRY, "kind": kind, "argv": ["/bin/prog"]}, "x").kind, kind)


class PickAndRenderTests(unittest.TestCase):
    def setUp(self):
        self.found = ac.parse({"adapters": [ENTRY, {**ENTRY, "id": "m", "kind": "image-to-mesh", "argv": ["/m", "{image}"]}]},
                              "machine.json")

    def test_a_stage_chooses_by_id_or_takes_the_default(self):
        self.assertEqual(self.found.pick(None, "image").id, "standin-image")
        self.assertEqual(self.found.pick("a", "image").id, "a")

    def test_an_unknown_id_is_an_error_never_a_fall_back(self):
        with self.assertRaisesRegex(ac.AdapterError, r"no adapter 'other' is configured \(configured: a, m, rules-kit, standin"):
            self.found.pick("other", "image")
        with self.assertRaisesRegex(ac.AdapterError, "is of kind 'image-to-mesh'"):
            self.found.pick("m", "image")
        for chosen in ({"argv": ["/bin/sh"]}, ["/bin/sh"], "/bin/sh -c x", 3):
            with self.subTest(chosen=chosen), self.assertRaisesRegex(ac.AdapterError, "chosen by its id"):
                self.found.pick(chosen, "image")

    def test_values_fill_one_element_each_in_one_pass(self):
        entry = ac.parse_entry({**ENTRY, "argv": ["/bin/prog", "--prompt={prompt}", "{{literal}}", "{out_dir}/x"]}, "x")
        tricky = "a lamp; rm -rf / $(id) `id` {out_dir} {{x}} \"quoted\" --output /etc/passwd"
        argv, env, cwd = ac.command(entry, {"prompt": tricky, "out_dir": "/runs/1"})
        self.assertEqual(argv, ["/bin/prog", "--prompt=" + tricky, "{literal}", "/runs/1/x"])
        self.assertEqual((env, cwd), ({}, None))

    def test_a_run_cannot_reach_a_placeholder_its_kind_does_not_take(self):
        entry = ac.parse_entry(ENTRY, "x")
        for data in ({"python": "/bin/sh"}, {"repo": "/tmp"}, {"command": "x"}, {"image": "/i.png"}):
            with self.subTest(data=data), self.assertRaisesRegex(ac.AdapterError, "takes no value"):
                ac.command(entry, {"prompt": "p", **data})
        with self.assertRaisesRegex(ac.AdapterError, "no value for the placeholder {prompt}"):
            ac.command(entry, {})
        with self.assertRaisesRegex(ac.AdapterError, "takes text or a number"):
            ac.command(entry, {"prompt": ["--evil"]})

    def test_check_lists_every_adapter_and_whether_this_host_can_run_it(self):
        import contextlib
        import io
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as temp:
            file = Path(temp) / "machine.json"
            file.write_text(json.dumps({"adapters": [{**ENTRY, "requires": ["cuda"]}]}))
            with contextlib.redirect_stdout(out), patch.object(ac.host, "accelerators", return_value=["cpu"]):
                self.assertEqual(ac.main(["check", str(file)]), 0)
        self.assertIn("standin-image (default)", out.getvalue())
        self.assertIn("a  [", out.getvalue())
        self.assertIn("not on this host: needs an NVIDIA GPU", out.getvalue())


if __name__ == "__main__":
    unittest.main()
