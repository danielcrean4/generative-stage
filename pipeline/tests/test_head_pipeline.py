"""Tests for the head pipeline (docs/pipeline_files.md): pipelines/head.json and its two tools (crop_image, colour_head),
starting a run from saved files, the job-level GPU lock, the seed batch and its contact sheet. No GPU and no model:
stand-in runners take the place of the concept bust and the mesh model (principle 2); every other stage is the real tool
under the tools interpreter.
Prints `HEAD_PIPELINE cases=<n> ok=<n>`."""
import functools
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
import gpu_session  # noqa: E402
import pipeline_batch as batch  # noqa: E402
import pipeline_file as pf  # noqa: E402
import pipeline_resolve as pr  # noqa: E402
import pipeline_run as run  # noqa: E402
import test_pipeline_run_mesh as base  # noqa: E402
import venv_tool  # noqa: E402
from test_style_tracer import png  # noqa: E402

HEAD = ROOT / "pipelines" / "head.json"
DATA = ROOT / "pipelines" / "examples" / "head"
SHEET_LOOK = ROOT / "pipelines" / "examples" / "finish.head.json"
GATE_FIXTURES = HERE / "fixtures" / "gates"
SEEDS = [5, 6, 7]
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


def head_sources():
    return (pf.load(HEAD), pr.load_subject(DATA / "subjects" / "friendly_adult.json"), pr.load_motif(DATA / "motifs" / "plain_character.json"),
            pr.load_style(DATA / "styles" / "vinyl_toy"), pr.load_contract(DATA / "contract.json"))


def head_job(seed=5):
    pipeline, subject, motif, style, contract = head_sources()
    return pr.resolve(pipeline, subject, motif, style, contract, seed)


def head_raw():
    return json.loads(HEAD.read_text())


def stage_of(raw, stage_id):
    return next(s for s in raw["stages"] if s["id"] == stage_id)


def problems_of(raw):
    try:
        pf.validate(raw, "h.json")
    except pf.PipelineError as exc:
        return exc.problems
    return []


class FileTests(unittest.TestCase):
    @case
    def test_the_head_file_validates_and_is_in_the_order_of_the_issue(self):
        pipeline = pf.load(HEAD)
        self.assertEqual([s.tool for s in pipeline.stages],
                         ["concept", "crop_image", "matte", "mesh", "colour_head", "normalize_mesh", "decimate_mesh", "mesh_gates"])
        self.assertTrue(pipeline.stage("matte").gate["allow_border"])     # the crop cuts through the neck
        self.assertTrue(all(s.retry is None for s in pipeline.stages))    # seeds are the batch's business, not a retry

    @case
    def test_the_mesh_model_gets_the_cut_out_and_the_gate_gets_the_bust(self):
        """The mesh script crops to the image's alpha: an opaque bust is a white rectangle to it, and it builds a card
        (the first real run did exactly that). So the mesh reads the matte's RGBA output; the colour projection and the
        gate compare against the cropped bust itself."""
        pipeline = pf.load(HEAD)
        self.assertEqual(pipeline.stage("mesh").inputs, {"image": "matte/matte.png"})
        self.assertEqual(pipeline.stage("colour").inputs["image"], "crop/image.png")
        self.assertEqual(pipeline.stage("shape_gate").inputs["image"], "crop/image.png")

    @case
    def test_bad_files_fail_with_the_key_named(self):
        def drop(stage, section, key):
            def mutate(raw):
                del stage_of(raw, stage)[section][key]
            return mutate

        def put(stage, section, key, value):
            def mutate(raw):
                stage_of(raw, stage)[section][key] = value
            return mutate
        bad = [
            (drop("crop", "params", "keep_share"), "h.json: /stages/1/params/keep_share: is required"),
            (put("crop", "params", "keep_share", 1.5), "h.json: /stages/1/params/keep_share: must be a number above 0 and at most 1"),
            (drop("colour", "params", "posterize"), "h.json: /stages/4/params/posterize: is required"),
            (put("colour", "params", "nape_height", 2), "h.json: /stages/4/params/nape_height: must be a number from 0 to 1"),
            (put("colour", "params", "hair_colour", "#000000"), "h.json: /stages/4/params/hair_colour: is not a known key"),
            (put("colour", "params", "tolerance", 236), "h.json: /stages/4/params/tolerance: is owned by capture"),
            (lambda raw: stage_of(raw, "colour").update(reads=["capture.background"]), "h.json: /stages/4/reads: must include 'subject' (tool needs it)"),
            (lambda raw: stage_of(raw, "crop").update(reads=[]), "h.json: /stages/1/reads: must include 'capture.background' (tool needs it)"),
            (lambda raw: stage_of(raw, "crop")["inputs"].update(image="bust/mesh.glb"), "h.json: /stages/1/inputs/image: stage 'bust' does not list 'mesh.glb' in its outputs"),
            (lambda raw: stage_of(raw, "colour").update(outputs=["head.glb"]), "h.json: /stages/4/outputs: must list exactly: mesh.glb"),
        ]
        for mutate, expected in bad:
            raw = head_raw()
            mutate(raw)
            self.assertTrue(any(line.startswith(expected) for line in problems_of(raw)), f"{expected!r} not in {problems_of(raw)}")

    @case
    def test_look_is_data_not_code(self):
        job = head_job()
        prompt = next(s["prompt"] for s in job["stages"] if "prompt" in s)
        for words in ("clay vinyl-toy style", "pure white background", "head and neck only", "facing camera directly"):
            self.assertIn(words, prompt)
        style_terms = [t for t in pr.load_style(DATA / "styles" / "vinyl_toy").terms] + ["pure white", "collarbone", "facing camera"]
        for script in ("pipeline_run.py", "pipeline_batch.py", "crop_image.py", "colour_head.py", "batch_sheet.py", "pipeline_file.py"):
            text = (ROOT / script).read_text().lower()
            for term in style_terms:
                self.assertNotIn(term.lower(), text, f"{script} spells the style word {term!r}")
        self.assertEqual(pr.lint(*[head_sources()[i] for i in (0, 1, 2, 3)]), [])

    @case
    def test_tool_sources_exist_and_head_tools_are_registered(self):
        for tool in ("crop_image", "colour_head"):
            self.assertIn(tool, pf.TOOLS)
            for name in pf.TOOLS[tool].sources:
                self.assertTrue((ROOT / name).is_file(), f"{tool}: {name}")
            self.assertEqual(len(run.registry_files(tool)), len(set(run.registry_files(tool))))

    @case
    def test_param_lists_match_the_real_tool_schemas(self):
        venv_tool.require_venv(self)
        out = venv_tool.run_code("import sys, json; sys.path.insert(0, sys.argv[1]); import crop_image, colour_head; "
                                 "print(json.dumps([sorted(crop_image.SCHEMA), sorted(colour_head.SCHEMA)]))", ROOT)
        crop_keys, colour_keys = json.loads(out)
        self.assertEqual(crop_keys, sorted(["background", *pf.TOOLS["crop_image"].params]))
        self.assertEqual(colour_keys, sorted(["background", "hair_colour", *pf.TOOLS["colour_head"].params]))

    @case
    def test_subject_hair_colour_is_checked(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "s.json"
            path.write_text(json.dumps({"id": "a", "kind": "head", "text": "x", "hair_colour": "brown"}))
            with self.assertRaises(pf.PipelineError) as raised:
                pr.load_subject(path)
            self.assertIn("/hair_colour: must be a \"#rrggbb\" colour", str(raised.exception))


class ToolTests(unittest.TestCase):
    def setUp(self):
        venv_tool.require_venv(self)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        self.background = {"method": "near_white", "tolerance": 236}

    def config(self, name, body):
        path = self.dir / name
        path.write_text(json.dumps(body))
        return path

    def crop(self, config, image):
        return venv_tool.run_tool("crop_image.py", image, self.dir / "out.png", "--config", self.config("crop.json", config), "--report", self.dir / "crop.json")

    @case
    def test_crop_keeps_the_top_share_of_the_subject(self):
        image = self.dir / "in.png"
        venv_tool.run_code("from PIL import Image, ImageDraw; import sys; i = Image.new('RGB', (100, 200), (255, 255, 255)); "
                           "ImageDraw.Draw(i).rectangle([20, 40, 80, 140], fill=(40, 40, 40)); i.save(sys.argv[1])", image)
        result = self.crop({"background": self.background, "keep_share": 0.5}, image)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads((self.dir / "crop.json").read_text())
        self.assertEqual(report["subject_rows"], [40, 140])
        self.assertEqual(report["output_size"], [100, 90])   # the subject's top row + half of its height (rows 40 to 139)

    @case
    def test_crop_names_a_missing_key_and_refuses_an_empty_image(self):
        image = self.dir / "blank.png"
        venv_tool.run_code("from PIL import Image; import sys; Image.new('RGB', (40, 40), (255, 255, 255)).save(sys.argv[1])", image)
        result = self.crop({"background": self.background}, image)
        self.assertEqual(result.returncode, 2)
        self.assertIn("missing required key 'keep_share'", result.stderr)
        result = self.crop({"background": self.background, "keep_share": 0.5}, image)
        self.assertEqual(result.returncode, 2)
        self.assertIn("no subject found", result.stderr)

    def colour_config(self, **change):
        params = pf.load(HEAD).stage("colour").params
        return {"background": self.background, "hair_colour": "#4d331f", **params, **change}

    @venv_tool.needs_gate_meshes
    @case
    def test_colour_head_keeps_the_geometry_and_adds_colours(self):
        out = self.dir / "coloured.glb"
        result = venv_tool.run_tool("colour_head.py", GATE_FIXTURES / "head.glb", GATE_FIXTURES / "head.png", out, "--config",
                                    self.config("c.json", self.colour_config()), "--report", self.dir / "r.json")
        self.assertEqual(result.returncode, 0, result.stderr)
        facts = json.loads(venv_tool.run_code(
            "import sys, json, trimesh, numpy as np; a = trimesh.load(sys.argv[1], force='mesh', process=False); "
            "b = trimesh.load(sys.argv[2], force='mesh', process=False); "
            "print(json.dumps({'same': bool(np.allclose(a.vertices, b.vertices) and (a.faces == b.faces).all()), 'kind': b.visual.kind, "
            "'colours': int(len(np.unique(b.visual.vertex_colors[:, :3], axis=0)))}))", GATE_FIXTURES / "head.glb", out))
        self.assertEqual((facts["same"], facts["kind"]), (True, "vertex"))
        self.assertGreater(facts["colours"], 3)

    @case
    def test_colour_head_names_a_missing_key_and_a_bad_value(self):
        broken = self.colour_config()
        del broken["posterize"]
        result = venv_tool.run_tool("colour_head.py", GATE_FIXTURES / "head.glb", GATE_FIXTURES / "head.png", self.dir / "o.glb",
                                    "--config", self.config("a.json", broken), "--report", self.dir / "r.json")
        self.assertEqual(result.returncode, 2)
        self.assertIn("missing required key 'posterize'", result.stderr)
        result = venv_tool.run_tool("colour_head.py", GATE_FIXTURES / "head.glb", GATE_FIXTURES / "head.png", self.dir / "o.glb",
                                    "--config", self.config("b.json", self.colour_config(hair_colour="brown")), "--report", self.dir / "r.json")
        self.assertIn("key 'hair_colour'", result.stderr)

    @venv_tool.needs_gate_meshes
    @case
    def test_colour_head_refuses_a_projection_that_misses_the_mesh(self):
        result = venv_tool.run_tool("colour_head.py", GATE_FIXTURES / "head.glb", GATE_FIXTURES / "head.png", self.dir / "o.glb", "--config",
                                    self.config("m.json", self.colour_config(seen_facing=1, min_seen_share=0.9)), "--report", self.dir / "r.json")
        self.assertEqual(result.returncode, 2)
        self.assertIn("seen by the front view", result.stderr)


def stand_ins(session=None, crash_seeds=(), meshes=None):
    """Stand-in concept, crop, mesh and colour runners (the GPU ones call session.hold(), as the real ones do)."""
    def hold():
        if session is not None:
            session.hold()

    def concept(stage, inputs, folder, seed):
        hold()
        if seed in crash_seeds:
            raise RuntimeError("the model crashed")
        (folder / "image.png").write_bytes(png((255, 255, 255, 255)))
        return {"seconds": 1.0}

    def crop(stage, inputs, folder, seed):
        shutil.copy(inputs["image"], folder / "image.png")
        return {"seconds": 0.1}

    def mesh(stage, inputs, folder, seed):
        hold()
        shutil.copy(meshes[seed], folder / "mesh.glb")
        return {"seconds": 2.0}

    def colour(stage, inputs, folder, seed):
        shutil.copy(inputs["mesh"], folder / "mesh.glb")
        return {"seconds": 0.3}

    return {"concept": run.StageRunner(concept, lambda stage: {"w": "1"}, (), True),
            "crop_image": run.StageRunner(crop, lambda stage: {}, (), False),
            "mesh": run.StageRunner(mesh, lambda stage: {"m": "1"}, (), True),
            "colour_head": run.StageRunner(colour, lambda stage: {}, (), False)}


class StartAtTests(base.RunnerCase):
    def runners(self, verdicts=("pass",)):
        return {**stand_ins(), **base.scripted_chain(list(verdicts))}

    def saved(self):
        (self.out / "bust.png").write_bytes(png((200, 100, 50, 255)))
        (self.out / "raw.glb").write_bytes(b"mesh bytes")
        return {"crop/image.png": self.out / "bust.png", "mesh/mesh.glb": self.out / "raw.glb"}

    @case
    def test_starting_at_a_stage_runs_only_from_there_and_records_the_saved_files(self):
        job = head_job()
        record = run.run_job(job, self.out, self.runners(), "r", self.out / "final", log=self.quiet, start_at="colour", supplied=self.saved())
        self.assertEqual(record["status"], "generated")
        self.assertEqual(list(record["stages"]), ["colour", "clean_mesh", "decimate", "shape_gate"])   # nothing earlier is shown as done
        self.assertEqual(record["start_at"], "colour")
        self.assertEqual(sorted(record["supplied"]), ["crop/image.png", "mesh/mesh.glb"])
        self.assertEqual(record["supplied"]["mesh/mesh.glb"]["sha256"], run.sha256_file(self.out / "raw.glb"))
        self.assertEqual(record["stages"]["shape_gate"]["gate"]["verdict"], "pass")
        self.assertGreater(record["stages"]["shape_gate"]["timing"]["seconds"], 0)
        self.assertEqual(self.attempt_json(record)["supplied"], record["supplied"])

    @case
    def test_a_missing_saved_input_names_the_stage_and_file(self):
        saved = self.saved()
        del saved["mesh/mesh.glb"]
        with self.assertRaises(run.RunError) as raised:
            run.run_job(head_job(), self.out, self.runners(), log=self.quiet, start_at="colour", supplied=saved)
        self.assertIn("mesh/mesh.glb", str(raised.exception))
        self.assertIn("starting at 'colour'", str(raised.exception))

    @case
    def test_other_start_mistakes_are_refused(self):
        saved = self.saved()
        for kwargs, words in (({"start_at": "nowhere", "supplied": saved}, "'nowhere' is not a stage"),
                              ({"start_at": "colour", "supplied": {**saved, "bust/image.png": saved["crop/image.png"]}}, "bust/image.png"),
                              ({"supplied": saved}, "without --start-at")):
            with self.assertRaises(run.RunError) as raised:
                run.run_job(head_job(), self.out, self.runners(), log=self.quiet, **kwargs)
            self.assertIn(words, str(raised.exception))
        with self.assertRaises(run.RunError) as raised:
            run.run_job(head_job(), self.out, self.runners(), log=self.quiet, start_at="colour", supplied={**saved, "mesh/mesh.glb": self.out / "gone.glb"})
        self.assertIn("missing or empty", str(raised.exception))

    @case
    def test_a_failing_gate_ends_the_run_failed_with_its_sheet(self):
        record = run.run_job(head_job(), self.out, self.runners(["fail"]), log=self.quiet, start_at="colour", supplied=self.saved())
        self.assertEqual((record["status"], record["verdict"]["verdict"]), ("failed", "fail"))
        self.assertTrue((self.out / record["verdict"]["review_sheet"]).is_file())
        self.assertNotIn("final", record)

    @case
    def test_cli_input_arguments(self):
        self.assertEqual(run.parse_inputs(["crop/image.png=/x/a.png"]), {"crop/image.png": Path("/x/a.png")})
        for bad in ("crop=/x", "crop/image.png=", "nothing"):
            with self.assertRaises(run.RunError):
                run.parse_inputs([bad])


class RealChainTests(base.RunnerCase):
    """The real colour, clean, decimate and gate stages on the committed gate fixture head, behind a session that must never be taken."""

    def setUp(self):
        venv_tool.require_venv(self)
        super().setUp()

    def session(self):
        def never(log, max_wait_s):
            raise AssertionError("a run from saved files must not take the GPU lock")
        return gpu_session.GpuSession(self.quiet, 1, acquire=never)

    def go(self, image, mesh):
        job = head_job()
        with self.session() as session:
            runners = run.default_runners(job, run.load_review_sheet(SHEET_LOOK), session)
            return run.run_job(job, self.out, runners, final_dir=self.out / "final", log=self.quiet, start_at="colour",
                               supplied={"crop/image.png": image, "mesh/mesh.glb": mesh}), session

    @venv_tool.needs_gate_meshes
    @case
    def test_fixture_head_passes_end_to_end_without_the_gpu(self):
        record, session = self.go(GATE_FIXTURES / "head.png", GATE_FIXTURES / "head.glb")
        self.assertEqual(record["status"], "generated", record.get("verdict"))
        self.assertFalse(session.held)
        final = self.out / record["final"]["path"]
        facts = json.loads(venv_tool.run_code("import sys, json, trimesh; m = trimesh.load(sys.argv[1], force='mesh'); "
                                              "print(json.dumps([m.visual.kind, len(m.faces)]))", final))
        self.assertEqual(facts[0], "vertex")             # the colour survived clean and decimate
        self.assertLessEqual(facts[1], 8000)

    @venv_tool.needs_gate_meshes
    @case
    def test_the_gate_can_fail_a_head_that_does_not_match_its_bust(self):
        wrong = self.out / "wrong.png"
        venv_tool.run_code("from PIL import Image, ImageDraw; import sys; i = Image.new('RGB', (512, 355), (255, 255, 255)); "
                           "ImageDraw.Draw(i).ellipse([20, 150, 490, 350], fill=(120, 80, 60)); i.save(sys.argv[1])", wrong)
        record, _ = self.go(wrong, GATE_FIXTURES / "head.glb")
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["verdict"]["verdict"], "fail")


class GpuSessionTests(unittest.TestCase):
    def fake(self):
        events = []

        class Hold:
            def __init__(self, log, max_wait_s):
                events.append(("wait", max_wait_s))

            def __enter__(self):
                events.append("held")

            def __exit__(self, *exc):
                events.append("released")
        return events, Hold

    @case
    def test_one_lock_for_many_holds_released_on_close(self):
        events, hold = self.fake()
        with gpu_session.GpuSession(print, 77, acquire=hold) as session:
            self.assertFalse(session.held)
            session.hold()
            session.hold()
            self.assertTrue(session.held)
        self.assertEqual(events, [("wait", 77), "held", "released"])

    @case
    def test_a_session_that_never_holds_never_takes_the_lock(self):
        events, hold = self.fake()
        with gpu_session.GpuSession(print, 1, acquire=hold):
            pass
        self.assertEqual(events, [])

    @case
    def test_released_when_the_job_raises(self):
        events, hold = self.fake()
        with self.assertRaises(KeyError):
            with gpu_session.GpuSession(print, 1, acquire=hold) as session:
                session.hold()
                raise KeyError("boom")
        self.assertEqual(events[-1], "released")

    @case
    def test_the_real_lock_is_taken_and_given_back(self):
        import gpu_lock
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "lock"
            import contextlib

            @contextlib.contextmanager
            def acquire(log, max_wait_s):
                with gpu_lock.held(path, "test", max_wait_s, log):
                    yield
            with gpu_session.GpuSession(print, 5, acquire=acquire) as session:
                session.hold()
                self.assertTrue(path.exists())
                session.hold()   # would wait on itself if it took the lock a second time
            self.assertFalse(path.exists())


class BatchTests(base.RunnerCase):
    def setUp(self):
        super().setUp()
        self.meshes = {}
        for seed in SEEDS:
            self.meshes[seed] = self.out / f"mesh{seed}.glb"
            self.meshes[seed].write_bytes(b"mesh" + bytes([seed]))
        self.events = []
        events = self.events

        class Hold:
            def __init__(self, log, max_wait_s):
                pass

            def __enter__(self):
                events.append("held")

            def __exit__(self, *exc):
                events.append("released")
        self.hold = Hold
        self.sheets = []

    def maker(self, batch_file, out, out_root, look):
        self.sheets.append(json.loads(Path(batch_file).read_text()))
        Path(out).write_bytes(png((1, 2, 3, 255)))

    def go(self, verdicts, crash_seeds=()):
        pipeline, subject, motif, style, contract = head_sources()
        review_sheet = run.load_review_sheet(SHEET_LOOK)
        with gpu_session.GpuSession(self.quiet, 5, acquire=self.hold) as session:
            runners = {**stand_ins(session, crash_seeds, self.meshes), **base.scripted_chain(list(verdicts))}
            return batch.run_batch(pipeline, subject, motif, style, contract, SEEDS, self.out, review_sheet, SHEET_LOOK, session,
                                   log=self.quiet, sheet_maker=self.maker, runners=runners)

    @case
    def test_n_seeds_one_lock_one_sheet_and_a_row_each(self):
        result, folder = self.go(["pass", "review", "fail"])
        self.assertEqual(self.events, ["held", "released"])        # one owner for all three seeds
        self.assertEqual([r["seed"] for r in result["rows"]], SEEDS)
        self.assertEqual([(r["status"], r["verdict"]) for r in result["rows"]],
                         [("generated", "pass"), ("review", "review"), ("failed", "fail")])
        self.assertEqual(len({r["attempt"] for r in result["rows"]}), 3)
        self.assertTrue((self.out / result["rows"][0]["final"]).is_file())   # only a passing seed has a final file
        self.assertIsNone(result["rows"][1]["final"])
        for row in result["rows"]:
            self.assertTrue((self.out / row["review_sheet"]).is_file())
        saved = json.loads((folder / "batch.json").read_text())
        self.assertEqual(saved["contact_sheet"], f"batches/{result['batch']}/contact-sheet.png")
        self.assertEqual(self.sheets[0]["rows"][2]["verdict"], "fail")      # the sheet maker saw every seed's outcome

    @case
    def test_a_crashed_seed_is_a_row_and_the_rest_go_on(self):
        result, _ = self.go(["pass", "pass"], crash_seeds=(6,))
        by_seed = {r["seed"]: r for r in result["rows"]}
        self.assertEqual(by_seed[6]["status"], "error")
        self.assertIn("the model crashed", by_seed[6]["error"])
        self.assertIsNone(by_seed[6]["review_sheet"])
        self.assertEqual((by_seed[5]["status"], by_seed[7]["status"]), ("generated", "generated"))
        self.assertEqual(self.events, ["held", "released"])

    @case
    def test_seed_list_rules(self):
        self.assertEqual(batch.parse_seeds("5,6,7"), [5, 6, 7])
        for bad in ("5,5", "a,b", ""):
            with self.assertRaises(run.RunError):
                batch.parse_seeds(bad)

    @case
    def test_the_contact_sheet_stacks_labelled_sheets_and_a_dead_seed(self):
        venv_tool.require_venv(self)
        result, folder = self.go(["pass", "fail"], crash_seeds=(7,))
        batch.make_sheet(folder / "batch.json", folder / "sheet.png", self.out, SHEET_LOOK)
        height, width = json.loads(venv_tool.run_code(
            "import sys, json; from PIL import Image; i = Image.open(sys.argv[1]); print(json.dumps([i.height, i.width]))", folder / "sheet.png"))
        look = run.load_review_sheet(SHEET_LOOK)
        picture = 4   # the stand-in review sheets are 4 pixels high
        # a title line, then a label line and a gap per seed, and a picture for the two seeds that have a sheet (not the dead one)
        self.assertEqual(height, 2 * look["padding"] + look["line_height"] + 3 * (look["gap"] + look["line_height"]) + 2 * picture)


def tearDownModule():
    print(f"HEAD_PIPELINE cases={TALLY['cases']} ok={TALLY['ok']}")


if __name__ == "__main__":
    unittest.main()
