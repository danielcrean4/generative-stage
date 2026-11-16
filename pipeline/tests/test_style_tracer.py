"""Tests for pipeline/pipeline_run.py and the tracer data (no GPU, no model: stand-in runners are injected in place of
the image model, principle 2). Prints `STYLE_TRACER cases=<n> ok=<n>`."""
import contextlib
import copy
import functools
import hashlib
import io
import json
import shutil
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pipeline_file as pf  # noqa: E402
import pipeline_resolve as pr  # noqa: E402
import pipeline_run as run  # noqa: E402
import venv_tool  # noqa: E402

DATA = ROOT / "pipelines" / "examples" / "tracer"
ICON = ROOT / "pipelines" / "examples" / "icon.pipeline.json"
PROP = ROOT / "pipelines" / "examples" / "prop.pipeline.json"
TALLY = {"cases": 0, "ok": 0}
STYLES = ("soft_toy", "bad_doodle", "photo_real")


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


def png(colour):
    """A 4x4 RGBA PNG of one colour, written without Pillow."""
    rows = b"".join(b"\x00" + bytes(colour) * 4 for _ in range(4))
    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 4, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


class StandIns:
    """Stand-in runners that count their calls. The concept image's colour comes from the prompt; the tidy step copies it."""

    def __init__(self):
        self.calls = {"concept": 0, "normalize_image": 0}

    def runners(self):
        def concept(stage, inputs, folder, seed):
            self.calls["concept"] += 1
            digest = hashlib.sha256(f"{stage['prompt']}|{seed}".encode()).digest()
            (folder / "image.png").write_bytes(png(digest[:4]))
            return {"seconds": 1.5, "load_seconds": 0.5, "generate_seconds": 1.0}

        def tidy(stage, inputs, folder, seed):
            self.calls["normalize_image"] += 1
            shutil.copy(inputs["image"], folder / "image.png")
            return {"seconds": 0.1}

        return {"concept": run.StageRunner(concept, lambda stage: {"weights_sha256": "w" * 8}, (), True),
                "normalize_image": run.StageRunner(tidy, lambda stage: {}, (), False)}


def job_for(style, subject="hand_drill", seed=2611, data=DATA, pipeline=ICON, motif="motifs/workshop_made.json"):
    return pr.resolve(pf.load(pipeline), pr.load_subject(data / "subjects" / f"{subject}.json"), pr.load_motif(data / motif),
                      pr.load_style(data / "styles" / style), pr.load_contract(data / "contract.json"), seed)


class StyleTracerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name)
        self.fake = StandIns()
        self.quiet = lambda message: None

    def run_style(self, style, **kwargs):
        return run.run_job(job_for(style, **kwargs), self.out, self.fake.runners(), "run-1", self.out / "final", log=self.quiet)

    def sidecar(self, style, subject="hand_drill"):
        return json.loads((self.out / "final" / style / f"{subject}.source.json").read_text())

    @case
    def test_attempt_layout(self):
        record = self.run_style("soft_toy")
        attempt = self.out / "attempts" / record["attempt"]
        self.assertEqual(sorted(p.name for p in attempt.iterdir()), ["attempt.json", "concept", "tidy_image"])
        self.assertTrue((attempt / "concept" / "image.png").is_file() and (attempt / "concept" / "stage.json").is_file())
        saved = json.loads((attempt / "attempt.json").read_text())
        self.assertEqual((saved["status"], saved["seed"], saved["run_id"]), ("generated", 2611, "run-1"))
        self.assertIn("flattened_sha256", saved["sources"]["style"])
        self.assertEqual(saved["resolved_job"]["stages"][0]["key_inputs"], saved["stages"]["concept"]["key_inputs"])
        self.assertEqual(saved["models"], {"concept": {"weights_sha256": "w" * 8}})
        self.assertEqual(saved["stages"]["concept"]["timing"]["generate_seconds"], 1.0)
        stage = json.loads((attempt / "concept" / "stage.json").read_text())
        self.assertIn("workshop-made", stage["prompt"])
        self.assertEqual(stage["outputs"], {"image.png": run.sha256_file(attempt / "concept" / "image.png")})
        self.assertEqual(json.loads((attempt / "tidy_image" / "stage.json").read_text())["inputs"]["image"]["from"], "concept/image.png")

    @case
    def test_sidecar_contents_and_relative_paths(self):
        record = self.run_style("soft_toy")
        sidecar = self.sidecar("soft_toy")
        job = job_for("soft_toy")
        self.assertEqual(sidecar["asset"], {"id": "hand_drill", "kind": "icon"})
        self.assertEqual(sidecar["subject"]["sha256"], job["sources"]["subject"]["sha256"])
        self.assertEqual(sidecar["motif"]["id"], "workshop_made")
        self.assertEqual(sidecar["style"]["id"], "soft_toy")
        self.assertEqual(sidecar["style"]["flattened_sha256"], job["sources"]["style"]["flattened_sha256"])
        self.assertEqual(sidecar["style_reads"], {"concept": {"style.prompt": pr.canonical_sha256(job["stages"][0]["reads"]["style.prompt"])}})
        self.assertEqual((sidecar["pipeline"]["id"], sidecar["seed"], sidecar["run_id"]), ("icon", 2611, "run-1"))
        self.assertEqual(sidecar["attempt"], f"attempts/{record['attempt']}")
        self.assertEqual(sidecar["image"]["sha256"], run.sha256_file(self.out / "final" / "soft_toy" / "hand_drill.png"))
        self.assertEqual(sidecar["stages"]["tidy_image"]["key_inputs"], job["stages"][1]["key_inputs"])
        for path, value in run.leaves(sidecar).items():
            self.assertFalse(isinstance(value, str) and (value.startswith("/") or "Users" in value), f"{path}: {value}")

    @case
    def test_unchanged_stages_are_reused_with_no_generation(self):
        first = self.run_style("bad_doodle")
        again = self.run_style("bad_doodle")
        self.assertEqual(self.fake.calls, {"concept": 1, "normalize_image": 1})
        self.assertTrue(all(s["reused"] for s in again["stages"].values()))
        self.assertEqual(again["stages"]["concept"]["reused_from"], f"attempts/{first['attempt']}/concept")
        self.assertEqual(again["final"]["sha256"], first["final"]["sha256"])
        self.assertTrue((self.out / "attempts" / again["attempt"] / "concept" / "image.png").is_file())

    @case
    def test_a_changed_input_reruns_only_what_it_touches(self):
        self.run_style("soft_toy")
        self.run_style("soft_toy", seed=7)  # new seed: concept reruns, and so does tidy (its input differs)
        self.assertEqual(self.fake.calls, {"concept": 2, "normalize_image": 2})
        self.run_style("soft_toy", seed=7)
        self.assertEqual(self.fake.calls, {"concept": 2, "normalize_image": 2})

    @case
    def test_a_damaged_earlier_output_is_not_reused(self):
        first = self.run_style("soft_toy")
        (self.out / "attempts" / first["attempt"] / "concept" / "image.png").write_bytes(b"damaged")
        self.run_style("soft_toy")
        self.assertEqual(self.fake.calls["concept"], 2)

    @case
    def test_refuses_pipelines_with_tools_it_does_not_run(self):
        with tempfile.TemporaryDirectory() as temp:
            fixtures = ROOT / "tests" / "fixtures" / "pipeline_files"
            job = pr.resolve(pf.load(PROP), pr.load_subject(fixtures / "subject.json"), pr.load_motif(fixtures / "motif.json"),
                             pr.load_style(fixtures / "styles" / "clay"), pr.load_contract(fixtures / "contract.json"), 1)
            with self.assertRaises(run.RunError) as caught:
                run.run_job(job, Path(temp), self.fake.runners(), log=self.quiet)
            self.assertIn("refuses this pipeline", str(caught.exception))
            self.assertIn("stage 'matte' uses the tool 'matte'", str(caught.exception))
            self.assertIn("'mesh'", str(caught.exception))
            self.assertEqual(list(Path(temp).iterdir()), [])
        self.assertEqual(self.fake.calls, {"concept": 0, "normalize_image": 0})

    @case
    def test_dry_run_runs_nothing(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = run.main(["--pipeline", str(ICON), "--subject", str(DATA / "subjects" / "hand_drill.json"), "--motif", str(DATA / "motifs" / "workshop_made.json"),
                             "--style", str(DATA / "styles" / "photo_real"), "--contract", str(DATA / "contract.json"), "--seed", "1",
                             "--out-root", str(self.out), "--dry-run"], runners=self.fake.runners())
        self.assertEqual(code, 0)
        self.assertIn("concept: would run", out.getvalue())
        self.assertEqual(list(self.out.iterdir()), [])
        self.assertEqual(self.fake.calls, {"concept": 0, "normalize_image": 0})

    @case
    def test_same_subject_three_packs_differ_only_in_the_style(self):
        for style in STYLES:
            self.run_style(style)
        sidecars = [self.sidecar(s) for s in STYLES]
        self.assertEqual(len({s["style"]["id"] for s in sidecars}), 3)
        self.assertEqual(len({s["style"]["flattened_sha256"] for s in sidecars}), 3)
        self.assertEqual(len({s["stages"]["concept"]["key"] for s in sidecars}), 3)
        self.assertEqual(len({s["stages"]["tidy_image"]["key_inputs"] for s in sidecars}), 1)  # the capture step does not read the pack
        for first, second in ((0, 1), (0, 2), (1, 2)):
            self.assertEqual(run.style_only_violations(sidecars[first], sidecars[second]), [])
        for field in ("subject", "motif", "pipeline", "contract", "seed", "run_id", "asset"):
            self.assertEqual(len({json.dumps(s[field], sort_keys=True) for s in sidecars}), 1, field)

    @case
    def test_the_sameness_check_can_fail(self):
        for style in ("soft_toy", "bad_doodle"):
            self.run_style(style)
        first, second = self.sidecar("soft_toy"), self.sidecar("bad_doodle")
        for path, change in (("seed", lambda s: s.update(seed=5)), ("subject.sha256", lambda s: s["subject"].update(sha256="x")),
                             ("motif.id", lambda s: s["motif"].update(id="other")), ("pipeline.sha256", lambda s: s["pipeline"].update(sha256="x")),
                             ("stages.tidy_image.key_inputs", lambda s: s["stages"]["tidy_image"].update(key_inputs="x")),
                             ("run_id", lambda s: s.update(run_id="other"))):
            changed = copy.deepcopy(second)
            change(changed)
            self.assertEqual(run.style_only_violations(first, changed), [path])

    @case
    def test_subjects_of_one_pack_differ_in_subject_not_in_style(self):
        self.run_style("soft_toy", subject="hand_drill")
        self.run_style("soft_toy", subject="music_box", seed=2613)
        a, b = self.sidecar("soft_toy", "hand_drill"), self.sidecar("soft_toy", "music_box")
        self.assertEqual(a["style"], b["style"])
        self.assertEqual(a["style_reads"], b["style_reads"])
        self.assertNotEqual(a["subject"], b["subject"])

    def packs_and_places(self):
        tracer = json.loads((DATA / "tracer.json").read_text())
        pipeline, motif = pf.load(DATA / tracer["pipeline"]), pr.load_motif(DATA / tracer["motif"])
        return tracer, pipeline, motif

    @case
    def test_tracer_data_passes_the_lint_for_every_pack(self):
        tracer, pipeline, motif = self.packs_and_places()
        self.assertEqual(len(tracer["subjects"]), 5)
        self.assertEqual(len({e["seed"] for e in tracer["subjects"]}), 5)
        for entry in tracer["subjects"]:
            subject = pr.load_subject(DATA / entry["file"])
            self.assertEqual(subject.body["kind"], "icon")
            for style_id in (*tracer["styles"], "soft_toy_night"):
                style = pr.load_style(DATA / "styles" / style_id)
                self.assertTrue(style.terms)
                self.assertEqual(pr.lint(pipeline, subject, motif, style), [], f"{entry['file']} {style_id}")

    @case
    def test_the_lint_fails_when_a_style_term_is_planted(self):
        tracer, pipeline, motif = self.packs_and_places()
        for style_id, word in (("soft_toy", "toy-like"), ("bad_doodle", "crayon"), ("photo_real", "photograph")):
            style = pr.load_style(DATA / "styles" / style_id)
            with tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / "subject.json"
                path.write_text(json.dumps({"id": "hand_drill", "kind": "icon", "text": f"a hand drill, {word}"}))
                found = pr.lint(pipeline, pr.load_subject(path), motif, style)
            self.assertEqual(len(found), 1, style_id)
            self.assertIn(f"style term '{word}'", found[0])

    @case
    def test_the_three_packs_give_three_different_prompts_from_one_subject(self):
        prompts = {s: job_for(s)["stages"][0]["prompt"] for s in STYLES}
        self.assertEqual(len(set(prompts.values())), 3)
        for prompt in prompts.values():
            self.assertTrue(prompt.startswith("a small child") or "a hand drill with a side handle" in prompt)
            self.assertIn("workshop-made", prompt)
            self.assertIn("#ff00ff", prompt)  # the capture words come from the pipeline file for every pack

    @case
    def test_inheritance_through_soft_toy_night(self):
        parent, child = pr.load_style(DATA / "styles" / "soft_toy"), pr.load_style(DATA / "styles" / "soft_toy_night")
        self.assertEqual([c[0] for c in child.chain], ["soft_toy", "soft_toy_night"])
        self.assertEqual(child.flat["prompt"]["negative"], parent.flat["prompt"]["negative"])  # inherited
        self.assertNotEqual(child.flat["prompt"]["templates"]["icon"], parent.flat["prompt"]["templates"]["icon"])  # changed
        self.assertTrue(set(parent.terms) < set(child.terms) and "moonlit" in child.terms)  # the lint uses the union
        self.assertNotEqual(child.flat_sha256, parent.flat_sha256)
        a, b = job_for("soft_toy"), job_for("soft_toy_night")
        self.assertNotEqual(a["stages"][0]["key_inputs"], b["stages"][0]["key_inputs"])
        self.assertEqual(a["stages"][1]["key_inputs"], b["stages"][1]["key_inputs"])
        self.assertEqual(a["stages"][0]["prompt"].replace("gentle shading", "moonlit blue and silver tones"), b["stages"][0]["prompt"])
        self.assertTrue(set(b["sources"]["style"]["chain"][0]) == {"id", "sha256"})
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(pr.main(["--pipeline", str(ICON), "--subject", str(DATA / "subjects" / "hand_drill.json"), "--motif", str(DATA / "motifs" / "workshop_made.json"),
                                      "--style", str(DATA / "styles" / "soft_toy_night"), "--contract", str(DATA / "contract.json"), "--seed", "1",
                                      "--lint", "--dry-run"]), 0)
        self.assertIn("moonlit", out.getvalue())

    @case
    def test_editing_the_parent_marks_the_child_stale(self):
        with tempfile.TemporaryDirectory() as temp:
            styles = Path(temp) / "styles"
            shutil.copytree(DATA / "styles", styles)
            before = pr.load_style(styles / "soft_toy_night").flat_sha256
            parent = styles / "soft_toy" / "style.json"
            raw = json.loads(parent.read_text())
            raw["prompt"]["negative"] += ", blur"
            parent.write_text(json.dumps(raw))
            self.assertNotEqual(pr.load_style(styles / "soft_toy_night").flat_sha256, before)

    @case
    def test_real_normalizer_under_the_image_interpreter(self):
        venv_tool.require_venv(self)
        runners = run.default_runners()
        tidy = runners["normalize_image"]
        stage = job_for("soft_toy")["stages"][1]
        folder, source = self.out / "tidy", self.out / "in.png"
        folder.mkdir()
        venv_tool.run_code("import sys\nfrom PIL import Image, ImageDraw\nimage = Image.new('RGB', (128, 128), (255, 0, 255))\n"
                           "ImageDraw.Draw(image).ellipse([40, 30, 90, 100], fill=(40, 90, 200))\nimage.save(sys.argv[1])", source)
        timing = tidy.run(stage, {"image": source}, folder, 1)
        report = json.loads((folder / "report.json").read_text())
        self.assertGreater(timing["seconds"], 0)
        self.assertFalse(report["touched_border"])
        self.assertEqual(report["output_mode"], "rgba")
        self.assertTrue((folder / "image.png").is_file())


def tearDownModule():
    print(f"STYLE_TRACER cases={TALLY['cases']} ok={TALLY['ok']}")
