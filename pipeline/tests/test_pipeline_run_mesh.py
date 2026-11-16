"""Tests for the mesh chain of pipeline/pipeline_run.py (docs/pipeline_files.md "Running"). No GPU and no model: stand-in
runners take the place of the concept image, the tidy step and the mesh model (principle 2). The matte, the clean, decimate
and gate stages are the real tools under the tools interpreter, fed with the gate fixture meshes (docs/gate_tests.md):
the cabinet is a pass, `cut_20` a review, `cut_33` and `relief_15` fails, so the real gate judges them.
Prints `PIPELINE_RUN_MESH cases=<n> ok=<n>`."""
import functools
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
import pipeline_file as pf  # noqa: E402
import pipeline_resolve as pr  # noqa: E402
import pipeline_run as run  # noqa: E402
import venv_tool  # noqa: E402
from test_gate_mutants import BUILD_CODE  # noqa: E402
from test_style_tracer import png  # noqa: E402

FIXTURES = HERE / "fixtures" / "gates"
PIPELINE_DATA = HERE / "fixtures" / "pipeline_files"
PROP = ROOT / "pipelines" / "examples" / "prop.pipeline.json"
FINISH_CONFIG = ROOT / "pipelines" / "examples" / "finish.prop.json"  # holds the review_sheet block
SEED = 42
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


def prop_job(seed=SEED, pipeline=PROP):
    return pr.resolve(pf.load(pipeline), pr.load_subject(PIPELINE_DATA / "subject.json"), pr.load_motif(PIPELINE_DATA / "motif.json"),
                      pr.load_style(PIPELINE_DATA / "styles" / "clay"), pr.load_contract(PIPELINE_DATA / "contract.json"), seed)


class StandIns:
    """Stand-in concept, tidy and mesh runners that count and record their calls. The concept image is IMAGE (a path) or
    plain white; the mesh stage copies the mesh named for its seed in MESHES (a {seed: path} dict)."""

    def __init__(self, image=None, meshes=None):
        self.image, self.meshes = image, meshes or {}
        self.calls = []   # (stage id, sorted input names, sorted read names, seed)

    def runners(self, job, real=None):
        def note(stage, inputs, seed):
            self.calls.append((stage["id"], sorted(inputs), sorted(stage["reads"]), seed))

        def concept(stage, inputs, folder, seed):
            note(stage, inputs, seed)
            if self.image:
                shutil.copy(self.image, folder / "image.png")
            else:
                (folder / "image.png").write_bytes(png((255, 255, 255, 255)))
            return {"seconds": 1.5, "load_seconds": 0.5, "generate_seconds": 1.0}

        def tidy(stage, inputs, folder, seed):
            note(stage, inputs, seed)
            shutil.copy(inputs["image"], folder / "image.png")
            return {"seconds": 0.1}

        def mesh(stage, inputs, folder, seed):
            note(stage, inputs, seed)
            shutil.copy(self.meshes[seed], folder / "mesh.glb")
            return {"seconds": 2.0, "load_seconds": 0.5, "generate_seconds": 1.5}

        runners = real or {}
        runners.update({"concept": run.StageRunner(concept, lambda stage: {"weights_sha256": "w" * 8}, (), True),
                        "normalize_image": run.StageRunner(tidy, lambda stage: {}, (), False),
                        "mesh": run.StageRunner(mesh, lambda stage: {"weights_sha256": "m" * 8}, (), True)})
        return runners


def recording(runner, calls):
    """RUNNER wrapped so every call appends the stage id to CALLS."""
    def counted(stage, inputs, folder, seed):
        calls.append((stage["id"], sorted(inputs), sorted(stage["reads"]), seed))
        return runner.run(stage, inputs, folder, seed)
    return run.StageRunner(counted, runner.identity, runner.tool_files, runner.seeded)


def scripted_chain(verdicts, calls=None, fail_clean_on=()):
    """Stand-in clean, decimate and gate runners: the gate's verdict for the n-th mesh it sees is VERDICTS[n] (and the
    sheet is a PNG); the n-th clean run, for n in FAIL_CLEAN_ON, raises StageFailed."""
    seen, cleans = [], []

    def copy_mesh(stage, inputs, folder, seed):
        calls is None or calls.append((stage["id"], sorted(inputs), sorted(stage["reads"]), seed))
        (folder / "mesh.glb").write_bytes(inputs["mesh"].read_bytes() + stage["id"].encode())
        if stage["tool"] == "normalize_mesh":
            cleans.append(1)
        if stage["tool"] == "normalize_mesh" and len(cleans) - 1 in fail_clean_on:
            raise run.StageFailed(["could not finish: the mesh has no faces"])
        return {"seconds": 0.2}

    def gate(stage, inputs, folder, seed):
        calls is None or calls.append((stage["id"], sorted(inputs), sorted(stage["reads"]), seed))
        verdict = verdicts[len(seen)]
        seen.append(verdict)
        outcome = {"pass": "pass", "review": "review", "fail": "fail"}[verdict]
        report = {"verdict": verdict, "passed": verdict == "pass", "reasons": [] if verdict == "pass" else [f"deficit is {verdict}"],
                  "measures": {"deficit": {"value": 0.2, "limit": 0.15, "limit_key": "max_deficit", "margin": -0.05, "outcome": outcome}}}
        (folder / "mesh-validation.json").write_text(json.dumps(report))
        (folder / run.SHEET_FILE).write_bytes(png((10, 20, 30, 255)))
        return {"seconds": 0.3}

    def matte(stage, inputs, folder, seed):
        calls is None or calls.append((stage["id"], sorted(inputs), sorted(stage["reads"]), seed))
        (folder / "matte.png").write_bytes(b"m")
        (folder / "matte.json").write_text(json.dumps({"reasons": [], "subject_share": 0.3, "largest_component_share": 1.0,
                                                      "component_count": 1, "border_contact": []}))
        return {"seconds": 0.1}

    keep = lambda stage: {}
    return {"normalize_mesh": run.StageRunner(copy_mesh, keep, (), False), "decimate_mesh": run.StageRunner(copy_mesh, keep, (), False),
            "mesh_gates": run.StageRunner(gate, lambda stage: {"frame_sha256": "f"}, (), False),
            "matte": run.StageRunner(matte, keep, (), False)}


class RunnerCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name)
        self.quiet = lambda message: None

    def attempt_json(self, record):
        return json.loads((self.out / "attempts" / record["attempt"] / "attempt.json").read_text())


class OrchestrationTests(RunnerCase):
    """The runner's own logic with every tool a stand-in (no interpreter needed)."""

    def run_scripted(self, verdicts, **kwargs):
        job, calls = prop_job(), []
        for k in range(3):   # a different file per seed, as a real model gives (equal inputs would be reused)
            (self.out / f"mesh{k}.glb").write_bytes((FIXTURES / "cabinet.glb").read_bytes() + bytes([k]))
        fake = StandIns(meshes={SEED + k: self.out / f"mesh{k}.glb" for k in range(3)})
        runners = fake.runners(job, scripted_chain(verdicts, calls, **kwargs))
        fake.calls = calls
        record = run.run_job(job, self.out, runners, "run-1", self.out / "final", log=self.quiet)
        return record, fake

    @venv_tool.needs_gate_meshes
    @case
    def test_stage_order_and_declared_inputs(self):
        record, fake = self.run_scripted(["pass"])
        job = prop_job()
        self.assertEqual([c[0] for c in fake.calls], [s["id"] for s in job["stages"]])
        for stage_id, inputs, reads, _ in fake.calls:
            stage = next(s for s in job["stages"] if s["id"] == stage_id)
            self.assertEqual(inputs, sorted(stage["inputs"]), stage_id)
            self.assertEqual(reads, sorted(stage["reads"]), stage_id)
        by = {c[0]: c for c in fake.calls}
        self.assertEqual(by["mesh"][1:3], (["image"], []))   # the mesh stage reads nothing but its image
        self.assertEqual(by["shape_gate"][1], ["image", "mesh"])
        self.assertEqual(record["status"], "generated")

    @case
    def test_unsupported_tool_is_refused_before_anything_runs(self):
        job, fake = prop_job(), StandIns()
        runners = fake.runners(job)   # concept, tidy and mesh only: matte and the chain have no runner
        with self.assertRaises(run.RunError) as raised:
            run.run_job(job, self.out, runners, log=self.quiet)
        self.assertIn("stage 'matte' uses the tool 'matte'", str(raised.exception))
        self.assertEqual(fake.calls, [])
        self.assertFalse((self.out / "attempts").exists())

    @venv_tool.needs_gate_meshes
    @case
    def test_retry_steps_the_seed_reuses_early_stages_and_exhausts(self):
        record, fake = self.run_scripted(["fail", "fail", "fail"])
        self.assertEqual(record["status"], "failed")
        self.assertEqual([t["seed"] for t in record["tries"]], [SEED, SEED + 1, SEED + 2])   # retry.max 2, seed_step 1
        self.assertEqual([t["verdict"] for t in record["tries"]], ["fail"] * 3)
        self.assertTrue(all(t["review_sheet"] for t in record["tries"]))
        for t in record["tries"]:
            self.assertTrue((self.out / t["review_sheet"]).is_file())
        ran = [c[0] for c in fake.calls]
        self.assertEqual([ran.count(s) for s in ("concept", "tidy_image", "matte", "mesh", "shape_gate")], [1, 1, 1, 3, 3])
        self.assertEqual([c[3] for c in fake.calls if c[0] == "mesh"], [SEED, SEED + 1, SEED + 2])
        self.assertNotIn("final", record)
        self.assertFalse((self.out / "final").exists())
        self.assertEqual(self.attempt_json(record)["status"], "failed")

    @venv_tool.needs_gate_meshes
    @case
    def test_fail_then_pass_on_retry(self):
        record, fake = self.run_scripted(["fail", "pass"])
        self.assertEqual(record["status"], "generated")
        self.assertEqual([t["verdict"] for t in record["tries"]], ["fail", "pass"])
        self.assertEqual(record["tries"][1]["stages"]["mesh"], "mesh.try1")
        self.assertEqual(record["verdict"]["try"], 1)
        self.assertEqual(record["tries"][0]["deciding"]["deficit"]["outcome"], "fail")
        self.assertEqual(sum(1 for c in fake.calls if c[0] == "concept"), 1)
        self.assertTrue((self.out / "final" / "clay" / "hand_drill.glb").is_file())

    @venv_tool.needs_gate_meshes
    @case
    def test_review_ends_the_attempt_as_review(self):
        record, fake = self.run_scripted(["review", "pass"])
        self.assertEqual(record["status"], "review")
        self.assertEqual(len(record["tries"]), 1)   # review is not in retry.on
        self.assertEqual(sum(1 for c in fake.calls if c[0] == "mesh"), 1)
        self.assertNotIn("final", record)
        self.assertFalse((self.out / "final").exists())   # nothing is installed
        self.assertTrue((self.out / record["verdict"]["review_sheet"]).is_file())

    @venv_tool.needs_gate_meshes
    @case
    def test_a_stage_that_cannot_finish_is_a_failed_try(self):
        record, fake = self.run_scripted(["pass"], fail_clean_on=(0,))
        self.assertEqual([t["verdict"] for t in record["tries"]], ["fail", "pass"])
        self.assertIn("the mesh has no faces", record["tries"][0]["reasons"][0])
        self.assertEqual(record["stages"]["clean_mesh"]["failed"], ["could not finish: the mesh has no faces"])
        self.assertIsNone(record["tries"][0]["review_sheet"])

    @venv_tool.needs_gate_meshes
    @case
    def test_per_stage_records(self):
        record, _ = self.run_scripted(["pass"])
        saved = self.attempt_json(record)
        mesh = saved["stages"]["mesh"]
        self.assertEqual(mesh["timing"]["load_seconds"], 0.5)
        self.assertEqual(mesh["timing"]["generate_seconds"], 1.5)
        self.assertEqual(mesh["seed"], SEED)
        self.assertEqual(mesh["model"], {"weights_sha256": "m" * 8})
        self.assertEqual(mesh["key_inputs"], prop_job()["stages"][3]["key_inputs"])
        gate = saved["stages"]["shape_gate"]
        self.assertEqual(gate["gate"]["verdict"], "pass")
        self.assertIn("deficit", gate["gate"]["measures"])
        self.assertIn("tool_version", gate)
        self.assertEqual(saved["models"]["mesh"], {"weights_sha256": "m" * 8})


@venv_tool.needs_gate_meshes
class RealChainTests(RunnerCase):
    """The real matte, clean, decimate and gate on the gate fixtures; only the concept, tidy and mesh are stand-ins."""

    @classmethod
    def setUpClass(cls):
        venv_tool.require_venv(cls)
        cls.temp_meshes = tempfile.TemporaryDirectory()
        cls.meshes = Path(cls.temp_meshes.name)
        venv_tool.run_code(BUILD_CODE, HERE, FIXTURES / "cabinet.glb", cls.meshes)
        shutil.copy(FIXTURES / "cabinet.glb", cls.meshes / "original.glb")
        cls.sheet = run.load_review_sheet(FINISH_CONFIG)

    @classmethod
    def tearDownClass(cls):
        cls.temp_meshes.cleanup()

    def go(self, *mesh_names, image=FIXTURES / "cabinet.png", job=None):
        job = job or prop_job()
        fake = StandIns(image=image, meshes={SEED + k: self.meshes / f"{name}.glb" for k, name in enumerate(mesh_names)})
        real = run.default_runners(job, self.sheet)
        runners = fake.runners(job, {tool: recording(real[tool], fake.calls) for tool in ("matte", "normalize_mesh", "decimate_mesh", "mesh_gates")})
        record = run.run_job(job, self.out, runners, "run-1", self.out / "final", log=self.quiet)
        return record, fake

    @case
    def test_first_try_pass_writes_the_sidecar_and_the_attempt_record(self):
        record, fake = self.go("original")
        self.assertEqual(record["status"], "generated")
        self.assertEqual([t["verdict"] for t in record["tries"]], ["pass"])
        final = self.out / "final" / "clay" / "hand_drill.glb"
        sidecar = json.loads(final.with_suffix(".source.json").read_text())
        self.assertEqual(hashlib.sha256(final.read_bytes()).hexdigest(), sidecar["mesh"]["sha256"])
        self.assertEqual(sidecar["mesh"]["path"], "hand_drill.glb")
        self.assertEqual(sidecar["verdict"]["verdict"], "pass")
        self.assertEqual(sidecar["verdict"]["seed"], SEED)
        sheet = self.out / sidecar["review_sheet"]
        self.assertTrue(sheet.is_file() and sheet.name == "review-sheet.png" and not Path(sidecar["review_sheet"]).is_absolute())
        self.assertEqual(sidecar["attempt"], f"attempts/{record['attempt']}")
        self.assertEqual(set(sidecar["stages"]), {s["id"] for s in prop_job()["stages"]})
        for key in ("subject", "motif", "style", "style_reads", "pipeline", "contract", "models", "seed", "run_id", "asset"):
            self.assertIn(key, sidecar)
        self.assertNotIn(str(self.out), json.dumps(sidecar))   # relative paths only
        saved = self.attempt_json(record)
        self.assertEqual(saved["final"]["stage"], "decimate")
        gate = saved["stages"]["shape_gate"]
        self.assertEqual(gate["gate"]["verdict"], "pass")
        self.assertGreater(gate["timing"]["seconds"], 0)
        self.assertEqual(len(gate["tool_version"]), 64)
        self.assertEqual(saved["stages"]["matte"]["gate"]["verdict"], "pass")
        self.assertIn("subject_share", saved["stages"]["matte"]["gate"]["measures"])
        self.assertEqual([c[0] for c in fake.calls], ["concept", "tidy_image", "matte", "mesh", "clean_mesh", "decimate", "shape_gate"])

    @case
    def test_fail_then_pass_with_the_real_gate(self):
        record, fake = self.go("cut_33", "original")
        self.assertEqual(record["status"], "generated")
        first, second = record["tries"]
        self.assertEqual((first["verdict"], second["verdict"]), ("fail", "pass"))
        self.assertEqual((first["seed"], second["seed"]), (SEED, SEED + 1))
        self.assertIn("deficit", first["deciding"])
        self.assertTrue((self.out / first["review_sheet"]).is_file() and (self.out / second["review_sheet"]).is_file())
        self.assertNotEqual(first["review_sheet"], second["review_sheet"])
        ran = [c[0] for c in fake.calls]
        self.assertEqual([ran.count(s) for s in ("concept", "tidy_image", "matte", "mesh", "clean_mesh", "decimate", "shape_gate")], [1, 1, 1, 2, 2, 2, 2])
        self.assertEqual(self.attempt_json(record)["stages"]["mesh.try1"]["seed"], SEED + 1)

    @case
    def test_retries_exhausted_keeps_every_try(self):
        record, fake = self.go("cut_33", "relief_15", "cut_33")
        self.assertEqual(record["status"], "failed")
        self.assertEqual([t["verdict"] for t in record["tries"]], ["fail"] * 3)
        self.assertEqual(len({t["review_sheet"] for t in record["tries"]}), 3)
        self.assertTrue(all((self.out / t["review_sheet"]).is_file() for t in record["tries"]))
        self.assertIn("depth_ratio", record["tries"][1]["deciding"])
        self.assertFalse((self.out / "final").exists())

    @case
    def test_review_verdict_is_not_retried_and_not_installed(self):
        record, fake = self.go("cut_20", "original")
        self.assertEqual(record["status"], "review")
        self.assertEqual(len(record["tries"]), 1)
        self.assertEqual(record["tries"][0]["verdict"], "review")
        self.assertEqual(sum(1 for c in fake.calls if c[0] == "mesh"), 1)
        self.assertTrue((self.out / record["verdict"]["review_sheet"]).is_file())
        self.assertFalse((self.out / "final").exists())

    @case
    def test_matte_failure_stops_before_the_mesh(self):
        record, fake = self.go("original", image=None)   # a plain white concept image: nothing to cut out
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["verdict"]["stage"], "matte")
        self.assertIn("no subject found", " ".join(record["verdict"]["reasons"]))
        self.assertEqual([c[0] for c in fake.calls], ["concept", "tidy_image", "matte"])
        self.assertEqual(record["not_run"], ["mesh", "clean_mesh", "decimate", "shape_gate"])

    @case
    def test_the_real_tidy_output_goes_through_the_real_matte_and_gate(self):
        job = prop_job()
        fake = StandIns(image=FIXTURES / "cabinet.png", meshes={SEED: self.meshes / "original.glb"})
        real = run.default_runners(job, self.sheet)
        runners = fake.runners(job, {tool: real[tool] for tool in ("matte", "normalize_mesh", "decimate_mesh", "mesh_gates")})
        runners["normalize_image"] = real["normalize_image"]
        record = run.run_job(job, self.out, runners, log=self.quiet)
        print(f"  real tidy on the cabinet: {record['status']} {record['verdict']['deciding']}")
        self.assertIn(record["status"], ("generated", "review"))
        self.assertEqual(record["stages"]["matte"]["gate"]["verdict"], "pass")

    @case
    def test_rerun_of_an_unchanged_job_generates_nothing(self):
        first, _ = self.go("original")
        second, fake = self.go("original")
        self.assertEqual(fake.calls, [])
        self.assertEqual(second["status"], "generated")
        self.assertTrue(all(s["reused"] for s in second["stages"].values()))
        self.assertTrue(all(s["timing"]["seconds"] == 0.0 for s in second["stages"].values()))
        self.assertEqual(first["final"]["sha256"], second["final"]["sha256"])

    @case
    def test_rerun_after_a_failed_first_try_reuses_both_tries(self):
        self.go("cut_33", "original")
        record, fake = self.go("cut_33", "original")
        self.assertEqual(fake.calls, [])
        self.assertEqual([t["verdict"] for t in record["tries"]], ["fail", "pass"])
        self.assertTrue(all(s["reused"] for s in record["stages"].values()))

    @case
    def test_the_sheet_look_is_part_of_the_gate_key(self):
        first, _ = self.go("original")
        changed = json.loads(json.dumps(self.sheet))
        changed["padding"] += 1
        job = prop_job()
        real = run.default_runners(job, changed)
        fake = StandIns(image=FIXTURES / "cabinet.png", meshes={SEED: self.meshes / "original.glb"})
        runners = fake.runners(job, {tool: recording(real[tool], fake.calls) for tool in ("matte", "normalize_mesh", "decimate_mesh", "mesh_gates")})
        run.run_job(job, self.out, runners, log=self.quiet)
        self.assertEqual([c[0] for c in fake.calls], ["shape_gate"])   # only the sheet's stage runs again


class ConfigTests(RunnerCase):
    @case
    def test_a_missing_review_sheet_is_refused_before_anything_runs(self):
        with self.assertRaises(run.RunError) as raised:
            run.default_runners(prop_job(), None)
        self.assertIn("--review-sheet", str(raised.exception))

    @case
    def test_tool_versions_come_from_the_registry(self):
        for tool, entry in pf.TOOLS.items():
            for name in entry.sources:
                self.assertTrue((ROOT / name).is_file(), f"{tool}: {name}")
        self.assertEqual([p.name for p in run.registry_files("mesh")], ["adapter_config.py", "adapter_run.py"])  # a model stage's tool is the adapter machinery


def tearDownModule():
    print(f"PIPELINE_RUN_MESH cases={TALLY['cases']} ok={TALLY['ok']}")


if __name__ == "__main__":
    unittest.main()
