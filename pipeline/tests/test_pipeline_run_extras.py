"""Attempt-record versions and the optional material stage of pipeline/pipeline_run.py. No model, no GPU, no interpreter:
stand-in runners and a stand-in package probe take their places."""
import contextlib
import copy
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
import machine  # noqa: E402
import pipeline_file as pf  # noqa: E402
import pipeline_resolve as pr  # noqa: E402
import pipeline_run as run  # noqa: E402
from test_style_tracer import png  # noqa: E402

DATA = HERE / "fixtures" / "pipeline_files"
EXAMPLES = ROOT / "pipelines"
PROP = EXAMPLES / "examples" / "prop.pipeline.json"
DOCS = ROOT.parent / "docs" / "pipeline_files.md"
TEXTURE_STAGE = {"id": "material", "label": "Material maps", "tool": "texture",
                 "inputs": {"image": "concept/image.png"}, "reads": [], "params": {},
                 "outputs": [f"maps/{name}.png" for name in pf.MAP_NAMES]}


def material_job(directory):
    """A resolved job: the prop pipeline's concept stage followed by the material stage (written to DIRECTORY)."""
    raw = json.loads(PROP.read_text())
    raw["id"] = "prop_material"
    raw["stages"] = [raw["stages"][0], copy.deepcopy(TEXTURE_STAGE)]
    path = Path(directory) / "material.pipeline.json"
    path.write_text(json.dumps(raw))
    return pr.resolve(pf.load(path), pr.load_subject(DATA / "subject.json"), pr.load_motif(DATA / "motif.json"),
                      pr.load_style(DATA / "styles" / "clay"), pr.load_contract(DATA / "contract.json"), 7)


def stand_in_runners(calls):
    def concept(stage, inputs, folder, seed):
        (folder / "image.png").write_bytes(png((255, 255, 255, 255)))
        return {"seconds": 1.0}

    def texture(stage, inputs, folder, seed):
        calls.append((stage["id"], sorted(inputs), seed))
        (folder / "maps").mkdir()
        for name in pf.MAP_NAMES:
            (folder / "maps" / f"{name}.png").write_bytes(png((10, 20, 30, 255)))
        return {"seconds": 2.0}

    return {"concept": run.StageRunner(concept, lambda stage: {"weights_sha256": "w"}, (), True),
            "texture": run.StageRunner(texture, lambda stage: {"adapter": "stand-in-material", "weights_sha256": "m"}, (), True)}


class CandidatesTests(unittest.TestCase):
    """--candidates N runs N seeds in one process under one GPU session."""

    def run_main(self, extra, locks):
        import gpu_session
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        out = Path(temp.name) / "out"
        raw = json.loads(PROP.read_text())
        raw["stages"] = raw["stages"][:1]
        pipeline = Path(temp.name) / "concept_only.pipeline.json"
        pipeline.write_text(json.dumps(raw))

        @contextlib.contextmanager
        def fake_lock(log, max_wait_s):
            locks.append("taken")
            yield
            locks.append("released")

        def runners(job, review_sheet, gpu):
            calls = stand_in_runners([])
            inner = calls["concept"].run

            def concept(stage, inputs, folder, seed):
                gpu.hold()
                return inner(stage, inputs, folder, seed)

            return {"concept": run.StageRunner(concept, lambda stage: {"weights_sha256": "w"}, (), True)}

        args = ["--pipeline", str(pipeline), "--subject", str(DATA / "subject.json"),
                "--motif", str(DATA / "motif.json"), "--style", str(DATA / "styles" / "clay"),
                "--contract", str(DATA / "contract.json"), "--seed", "7", "--out-root", str(out), *extra]
        with patch.object(gpu_session, "gpu_lock", fake_lock), patch.object(run, "default_runners", runners), \
                patch.object(run, "environment_versions", lambda job: {}), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = run.main(args)
        return code, out

    def test_three_candidates_take_the_lock_once_and_each_keeps_its_own_final_folder(self):
        locks = []
        code, out = self.run_main(["--candidates", "3"], locks)
        self.assertEqual(locks, ["taken", "released"])
        seeds = sorted(json.loads(p.read_text())["seed"] for p in (out / "attempts").glob("*/attempt.json"))
        self.assertEqual(seeds, [7, 8, 9])
        self.assertEqual(code, 0)
        self.assertEqual(sorted(p.name for p in (out / "final").iterdir()), ["seed-7", "seed-8", "seed-9"])

    def test_without_the_flag_one_seed_runs_and_the_final_folder_is_plain(self):
        locks = []
        code, out = self.run_main([], locks)
        self.assertEqual((locks, code), (["taken", "released"], 0))
        self.assertEqual(len(list((out / "attempts").glob("*/attempt.json"))), 1)
        self.assertFalse(any(p.name.startswith("seed-") for p in (out / "final").iterdir()))


class VersionsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)

    def attempt(self, record, out):
        return json.loads((out / "attempts" / record["attempt"] / "attempt.json").read_text())

    def test_the_attempt_records_versions_and_they_are_not_part_of_a_stage_key(self):
        job = material_job(self.dir)
        first_out, calls = self.dir / "one", []
        versions = {"python": "3.12.1", "tools": {"python": "3.12.1", "packages": {"numpy": "2.0.0"}}}
        first = run.run_job(job, first_out, stand_in_runners(calls), versions=versions, log=lambda m: None)
        self.assertEqual(self.attempt(first, first_out)["versions"], versions)
        second = run.run_job(job, first_out, stand_in_runners(calls), versions={"python": "9.9.9"}, log=lambda m: None)
        self.assertEqual(self.attempt(second, first_out)["versions"], {"python": "9.9.9"})
        self.assertTrue(all(entry["reused"] for entry in second["stages"].values()))  # a new Python does not change the keys
        self.assertEqual(len(calls), 1)

    def test_without_versions_the_record_still_names_this_python(self):
        record = run.run_job(material_job(self.dir), self.dir / "out", stand_in_runners([]), log=lambda m: None)
        self.assertEqual(record["versions"], {"python": sys.version.split()[0]})

    def test_environment_versions_probes_each_adapter_program_by_its_id(self):
        python = self.dir / "bin" / "python"
        program = self.dir / "bin" / "make-image"
        python.parent.mkdir()
        python.write_text("")
        program.write_text("")
        entry = {"sandbox": {"network": "allow"}, "licence": "test"}
        config = self.dir / "machine.json"
        config.write_text(json.dumps({
            "adapters": [{**entry, "id": "img", "kind": "image", "argv": [str(program), "{prompt}"]},
                         {**entry, "id": "mat", "kind": "material", "argv": [str(python), "{image}"]}],
            "defaults": {"image": "img", "material": "mat"}}))
        probed = []

        def probe(found, packages):
            probed.append(found.name)
            return {"python": "3.12.0", "packages": {name: "1.0" for name in packages[:2]}}

        with patch.dict(os.environ, {machine.CONFIG_ENV: str(config)}):
            versions = run.environment_versions(material_job(self.dir), probe)
        self.assertEqual(sorted(versions), ["img", "mat", "python"])  # no numpy tool: no tools interpreter
        self.assertEqual(probed, ["python", "python"])  # a venv's command is probed through the Python beside it
        self.assertEqual(versions["mat"]["python"], "3.12.0")
        self.assertNotIn(str(self.dir), json.dumps(versions))  # adapters are named, paths are not recorded

    def test_an_unconfigured_adapter_or_broken_interpreter_is_recorded_not_fatal(self):
        config = self.dir / "machine.json"
        config.write_text("{}")
        with patch.dict(os.environ, {machine.CONFIG_ENV: str(config)}):
            versions = run.environment_versions(material_job(self.dir), lambda found, packages: {"python": "x"})
        self.assertEqual(versions["stage material"], "adapter not configured")  # no material adapter by default
        self.assertEqual(versions["standin-image"], {"python": "x"})  # the stand-in runs under this interpreter


class BatchVersionsTests(unittest.TestCase):
    def test_a_batch_with_the_real_runners_records_versions_in_every_attempt(self):
        import pipeline_batch
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            material_job(directory)  # writes material.pipeline.json
            marker = {"python": "marker"}
            with patch.object(run, "environment_versions", return_value=marker), \
                 patch.object(run, "default_runners", return_value=stand_in_runners([])):
                batch, folder = pipeline_batch.run_batch(
                    pf.load(directory / "material.pipeline.json"), pr.load_subject(DATA / "subject.json"), pr.load_motif(DATA / "motif.json"),
                    pr.load_style(DATA / "styles" / "clay"), pr.load_contract(DATA / "contract.json"), [3], directory / "out", None, None,
                    session=None, log=lambda m: None, sheet_maker=lambda *a: None)
            record = json.loads((directory / "out" / "attempts" / batch["rows"][0]["attempt"] / "attempt.json").read_text())
            self.assertEqual(record["versions"], marker)


class MaterialStageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)

    def test_a_pipeline_can_enable_the_stage_and_it_runs_after_the_image(self):
        calls = []
        record = run.run_job(material_job(self.dir), self.dir / "out", stand_in_runners(calls), log=lambda m: None)
        self.assertEqual(record["status"], "generated")
        self.assertEqual(calls, [("material", ["image"], 7)])
        outputs = record["stages"]["material"]["outputs"]
        self.assertEqual(sorted(outputs), sorted(f"maps/{name}.png" for name in pf.MAP_NAMES))
        self.assertEqual(record["stages"]["material"]["model"]["adapter"], "stand-in-material")

    def test_no_shipped_pipeline_enables_the_stage(self):
        shipped = sorted(EXAMPLES.rglob("*.json"))
        self.assertTrue(shipped)
        offenders = []
        for path in shipped:
            try:
                body = json.loads(path.read_text())
            except ValueError:
                continue
            if isinstance(body, dict) and any(isinstance(s, dict) and s.get("tool") == "texture" for s in body.get("stages", [])):
                offenders.append(path.name)
        self.assertEqual(offenders, [])

    def test_the_real_runner_is_registered_but_needs_an_adapter(self):
        runners = run.default_runners()
        self.assertIn("texture", runners)
        self.assertEqual([p.name for p in runners["texture"].tool_files], ["adapter_config.py", "adapter_run.py"])
        config = self.dir / "machine.json"
        config.write_text("{}")
        with patch.dict(os.environ, {machine.CONFIG_ENV: str(config)}):
            with self.assertRaisesRegex(run.RunError, "no adapter of kind 'material'"):
                run.default_runners()["texture"].identity({"id": "material", "tool": "texture"})
            with self.assertRaisesRegex(run.RunError, "no adapter 'other-mesh' is configured"):
                run.default_runners()["mesh"].run({"id": "mesh", "tool": "mesh", "params": {}, "model": "other-mesh"},
                                                  {"image": self.dir / "i.png"}, self.dir, 1)

    def test_a_missing_gpu_lock_setting_is_a_clear_refusal_not_a_traceback(self):
        python, weights = self.dir / "python", self.dir / "weights"
        python.write_text("")
        weights.mkdir()
        (weights / "model.bin").write_bytes(b"w")
        config = self.dir / "machine.json"
        config.write_text(json.dumps({"adapters": [{  # a material adapter that holds the GPU lock; no gpu_lock set
            "id": "mat", "kind": "material", "argv": [str(python), "{image}", "{out_dir}/maps"], "gpu": True,
            "sandbox": {"network": "allow"}, "model": {"name": "test material model", "weights": str(weights)},
            "licence": "MIT (a test entry)"}], "defaults": {"material": "mat"}}))
        job_file = self.dir / "job.json"
        job_file.write_text(json.dumps(material_job(self.dir)))
        image = self.dir / "image.png"
        image.write_bytes(png((255, 255, 255, 255)))
        errors = io.StringIO()
        with patch.dict(os.environ, {machine.CONFIG_ENV: str(config), "GENSTAGE_IDENTITY_CACHE": str(self.dir / "identity.json")}):
            with contextlib.redirect_stderr(errors):
                code = run.main(["--job", str(job_file), "--out-root", str(self.dir / "out"), "--start-at", "material",
                                 "--input", f"concept/image.png={image}"])
        self.assertEqual(code, 1)
        self.assertIn("gpu_lock", errors.getvalue())

    def test_the_docs_say_the_stage_is_off_by_default_and_needs_an_adapter(self):
        text = DOCS.read_text()
        section = text[text.index("The texture tool"):]
        for phrase in ("off by default", "material adapter", "adapters.md"):
            self.assertIn(phrase, section)


if __name__ == "__main__":
    unittest.main()
