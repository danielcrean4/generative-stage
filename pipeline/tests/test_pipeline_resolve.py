"""Tests for pipeline/pipeline_resolve.py (plain Python, no venv): shapes, extends, prompt assembly, reads,
key_inputs staleness, lint and --dry-run. Prints the combined `PIPELINE_FILES cases=<n> ok=<n>` line (the
tally is shared with test_pipeline_file, which unittest discovery runs first)."""
import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_pipeline_file as base  # noqa: E402
import pipeline_file as pf  # noqa: E402
import pipeline_resolve as pr  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "pipeline_files"
PROP = base.PROP
case = base.case
SEED = 42
VINYL_PROP = ("a hand drill with a side handle, repair-shop, brass and recycled parts, soft vinyl toy, smooth rounded forms, "
              "plain white background, single object, whole object in frame, even light, no cast shadow, three-quarter view")
CLAY_PROP = ("a hand drill with a side handle made of repair-shop, brass and recycled parts, hand-sculpted clay, visible thumb marks, "
             "plain white background, single object, whole object in frame, even light, no cast shadow, three-quarter view")


class Fixture:
    """A temp copy of the fixtures that a test may edit."""

    def __init__(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for item in FIXTURES.iterdir():
            (shutil.copytree if item.is_dir() else shutil.copy)(item, self.root / item.name)

    def edit(self, relative, change):
        path = self.root / relative
        raw = json.loads(path.read_text())
        change(raw)
        path.write_text(json.dumps(raw))

    def resolve(self, style="clay", pipeline=PROP, seed=SEED):
        return pr.resolve(pf.load(pipeline), pr.load_subject(self.root / "subject.json"), pr.load_motif(self.root / "motif.json"),
                          pr.load_style(self.root / "styles" / style), pr.load_contract(self.root / "contract.json"), seed)

    def args(self, *extra, style="clay"):
        return ["--pipeline", str(PROP), "--subject", str(self.root / "subject.json"), "--motif", str(self.root / "motif.json"),
                "--style", str(self.root / "styles" / style), "--contract", str(self.root / "contract.json"), "--seed", str(SEED), *extra]


def keys(job):
    return {s["id"]: s["key_inputs"] for s in job["stages"]}


def run_cli(args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = pr.main(args)
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


class ResolveTests(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture()
        self.addCleanup(self.fx.temp.cleanup)

    @case
    def test_prompt_text_is_exact_for_each_style(self):
        self.assertEqual(self.fx.resolve("vinyl_toy")["stages"][0]["prompt"], VINYL_PROP)
        self.assertEqual(self.fx.resolve("clay")["stages"][0]["prompt"], CLAY_PROP)

    @case
    def test_prompt_without_a_view_skips_it(self):
        words = {"background": {"words": "bg"}, "framing": {"words": "fr"}}
        self.assertEqual(pr.assemble_prompt("{subject} {motif}", "S", "M", words), "S M, bg, fr")

    @case
    def test_a_value_that_looks_like_a_variable_is_not_filled_twice(self):
        self.assertEqual(pr.fill("{subject}|{motif}", "{motif}", "m"), "{motif}|m")

    @case
    def test_stage_gets_only_the_reads_it_declares(self):
        job = self.fx.resolve()
        by_id = {s["id"]: s for s in job["stages"]}
        for stage in pf.load(PROP).stages:
            self.assertEqual(sorted(by_id[stage.id]["reads"]), sorted(stage.reads))
        self.assertEqual(by_id["mesh"]["reads"], {})
        self.assertNotIn("style.prompt", json.dumps(by_id["clean_mesh"]))
        self.assertEqual(by_id["decimate"]["reads"]["contract"]["face_budget"], 8000)
        self.assertNotIn("prompt", by_id["decimate"])
        self.assertEqual(set(by_id["tidy_image"]["reads"]), {"capture.background"})

    @case
    def test_child_prompt_changes_concept_key_not_mesh_key(self):
        before = keys(self.fx.resolve())
        self.fx.edit("styles/clay/style.json", lambda raw: raw["prompt"]["templates"].update(prop="{subject}, {motif}, wobbly crayon"))
        after = keys(self.fx.resolve())
        self.assertNotEqual(before["concept"], after["concept"])
        for stage in before:
            if stage != "concept":
                self.assertEqual(before[stage], after[stage], stage)

    @case
    def test_face_budget_changes_decimate_and_gate_not_concept(self):
        before = keys(self.fx.resolve())
        self.fx.edit("contract.json", lambda raw: raw.update(face_budget=4000))
        after = keys(self.fx.resolve())
        self.assertNotEqual(before["decimate"], after["decimate"])
        self.assertNotEqual(before["shape_gate"], after["shape_gate"])
        for stage in ("concept", "tidy_image", "matte", "mesh"):
            self.assertEqual(before[stage], after[stage], stage)

    @case
    def test_parent_edit_changes_child_flattened_hash(self):
        before = self.fx.resolve()
        self.fx.edit("styles/vinyl_toy/style.json", lambda raw: raw["prompt"].update(negative="blur"))
        after = self.fx.resolve()
        self.assertNotEqual(before["sources"]["style"]["flattened_sha256"], after["sources"]["style"]["flattened_sha256"])
        self.assertNotEqual(keys(before)["concept"], keys(after)["concept"])
        self.assertEqual([c["id"] for c in after["sources"]["style"]["chain"]], ["vinyl_toy", "clay"])

    @case
    def test_flattening_child_overrides_parent_and_inherits_the_rest(self):
        flat = pr.load_style(self.fx.root / "styles" / "clay").flat
        self.assertEqual(flat["id"], "clay")
        self.assertNotIn("extends", flat)
        self.assertEqual(flat["prompt"]["negative"], "text, watermark")
        self.assertEqual(flat["prompt"]["templates"]["icon"], "{subject}, {motif}, flat toy-like icon")
        self.assertEqual(flat["terms"], ["clay"])
        self.assertEqual(flat["surface"]["posterize"], 4)

    @case
    def test_sources_hash_every_file(self):
        sources = self.fx.resolve()["sources"]
        for name, path in (("subject", "subject.json"), ("motif", "motif.json"), ("contract", "contract.json")):
            import hashlib
            self.assertEqual(sources[name]["sha256"], hashlib.sha256((self.fx.root / path).read_bytes()).hexdigest())
        self.assertEqual(sources["pipeline"]["sha256"], pf.load(PROP).sha256)

    @case
    def test_style_errors_name_file_and_key(self):
        self.fx.edit("styles/clay/style.json", lambda raw: raw["prompt"]["templates"].update(prop="{subject} {colour}"))
        with self.assertRaises(pf.PipelineError) as ctx:
            pr.load_style(self.fx.root / "styles" / "clay")
        self.assertEqual(ctx.exception.problems,
                         [f"{self.fx.root / 'styles/clay/style.json'}: /prompt/templates/prop: has the variable {{colour}}; only {{subject}} and {{motif}} are allowed"])
        self.fx.edit("styles/clay/style.json", lambda raw: raw["prompt"]["templates"].update(prop="{subject}"))
        with self.assertRaises(pf.PipelineError) as ctx:
            pr.load_style(self.fx.root / "styles" / "clay")
        self.assertIn("/prompt/templates/prop: must contain {motif}", ctx.exception.problems[0])

    @case
    def test_extends_cycle_missing_parent_and_id_mismatch(self):
        self.fx.edit("styles/vinyl_toy/style.json", lambda raw: raw.update(extends="clay"))
        with self.assertRaises(pf.PipelineError) as ctx:
            pr.load_style(self.fx.root / "styles" / "clay")
        self.assertIn("/extends: cycle: clay -> vinyl_toy -> clay", ctx.exception.problems[0])
        self.fx.edit("styles/clay/style.json", lambda raw: raw.update(extends="ghost"))
        with self.assertRaises(pf.PipelineError) as ctx:
            pr.load_style(self.fx.root / "styles" / "clay")
        self.assertIn("/extends: parent style 'ghost' not found", ctx.exception.problems[0])
        self.fx.edit("styles/clay/style.json", lambda raw: raw.update(id="mud"))
        with self.assertRaises(pf.PipelineError) as ctx:
            pr.load_style(self.fx.root / "styles" / "clay")
        self.assertIn("/id: is 'mud' but the folder is 'clay'", ctx.exception.problems[0])

    @case
    def test_shape_errors_for_subject_motif_contract(self):
        self.fx.edit("subject.json", lambda raw: raw.update(colours=["red"], extra=1))
        with self.assertRaises(pf.PipelineError) as ctx:
            pr.load_subject(self.fx.root / "subject.json")
        path = self.fx.root / "subject.json"
        self.assertEqual(sorted(ctx.exception.problems),
                         sorted([f"{path}: /extra: is not a known key (allowed: id, kind, text, colours, materials, hair_colour)",
                                 f'{path}: /colours: must be a non-empty list of "#rrggbb" colours']))
        self.fx.edit("motif.json", lambda raw: raw.pop("text"))
        with self.assertRaises(pf.PipelineError) as ctx:
            pr.load_motif(self.fx.root / "motif.json")
        self.assertEqual(ctx.exception.problems, [f"{self.fx.root / 'motif.json'}: /text: is required"])
        self.fx.edit("contract.json", lambda raw: raw.update(up_axis="y", front_axis="+y"))
        with self.assertRaises(pf.PipelineError) as ctx:
            pr.load_contract(self.fx.root / "contract.json")
        self.assertEqual(ctx.exception.problems, [f'{self.fx.root / "contract.json"}: /up_axis: must be a signed axis such as "+y" or "-z"'])
        self.fx.edit("contract.json", lambda raw: raw.update(up_axis="+y", front_axis="-y"))
        with self.assertRaises(pf.PipelineError) as ctx:
            pr.load_contract(self.fx.root / "contract.json")
        self.assertIn("/front_axis: must be a different axis from up_axis", ctx.exception.problems[0])

    @case
    def test_kind_mismatch_missing_template_and_bad_seed(self):
        self.fx.edit("subject.json", lambda raw: raw.update(kind="icon"))
        with self.assertRaises(pf.PipelineError) as ctx:
            self.fx.resolve()
        self.assertIn(f"{self.fx.root / 'subject.json'}: /kind: is 'icon' but the pipeline {PROP} makes 'prop'", ctx.exception.problems)
        self.fx.edit("subject.json", lambda raw: raw.update(kind="prop"))
        with self.assertRaises(pf.PipelineError) as ctx:
            self.fx.resolve(seed=-1)
        self.assertEqual(ctx.exception.problems, ["seed: must be a whole number from 0 to 2**32 - 1"])
        with self.assertRaises(pf.PipelineError) as ctx:
            self.fx.resolve(seed=2**32 - 1)
        self.assertEqual(ctx.exception.problems, ["seed: seed plus the largest retry.max must stay below 2**32"])
        self.fx.edit("styles/vinyl_toy/style.json", lambda raw: raw["prompt"]["templates"].pop("prop"))
        self.fx.edit("styles/clay/style.json", lambda raw: raw["prompt"].pop("templates"))
        with self.assertRaises(pf.PipelineError) as ctx:
            self.fx.resolve()
        self.assertIn("/prompt/templates/prop: the style 'clay' has no template for kind 'prop'", ctx.exception.problems[0])

    @case
    def test_stage_reading_a_field_the_style_lacks_fails(self):
        raw = json.loads(PROP.read_text())
        raw["stages"][1]["reads"].append("style.palette")
        self.fx.edit("styles/vinyl_toy/style.json", lambda r: r.pop("palette"))
        pipeline = pf.validate(raw, "p.json")
        with self.assertRaises(pf.PipelineError) as ctx:
            pr.resolve(pipeline, pr.load_subject(self.fx.root / "subject.json"), pr.load_motif(self.fx.root / "motif.json"),
                       pr.load_style(self.fx.root / "styles/clay"), pr.load_contract(self.fx.root / "contract.json"), SEED)
        self.assertEqual(ctx.exception.problems,
                         ["p.json: /stages/1/reads: stage 'tidy_image' reads style.palette but the style 'clay' sets none"])
        raw["stages"][1]["reads"].append("style.surface")
        job = pr.resolve(pf.validate({**raw, "stages": [raw["stages"][0], {**raw["stages"][1], "reads": ["capture.background", "style.surface"]}]}, "p.json"),
                         pr.load_subject(self.fx.root / "subject.json"), pr.load_motif(self.fx.root / "motif.json"),
                         pr.load_style(self.fx.root / "styles/clay"), pr.load_contract(self.fx.root / "contract.json"), SEED)
        self.assertEqual(job["stages"][1]["reads"]["style.surface"], {"posterize": 4, "roughness": 0.85})

    @case
    def test_resolve_checks_the_real_face_budget_in_the_gate(self):
        pipeline = pf.load(PROP)
        gate = pipeline.stage("shape_gate")
        config, problems = pf.gate_config(pipeline, gate, 8000)
        self.assertEqual((problems, config["gate"]["face_budget"]), ([], 8000))
        _, problems = pf.gate_config(pipeline, gate, 0)
        self.assertEqual(problems, [f"{PROP}: /stages/6/gate: face_budget must be a whole number above 0"])

    @case
    def test_lint_finds_terms_in_subject_motif_and_capture_words(self):
        pipeline = pf.load(PROP)
        style = pr.load_style(self.fx.root / "styles" / "clay")
        self.assertEqual(style.terms, ("vinyl", "toy-like", "clay"))
        subject, motif = pr.load_subject(self.fx.root / "subject.json"), pr.load_motif(self.fx.root / "motif.json")
        self.assertEqual(pr.lint(pipeline, subject, motif, style), [])
        self.fx.edit("subject.json", lambda raw: raw.update(text="a Vinyl hand drill"))
        self.fx.edit("motif.json", lambda raw: raw.update(text="toy-like parts, clay"))
        subject, motif = pr.load_subject(self.fx.root / "subject.json"), pr.load_motif(self.fx.root / "motif.json")
        found = pr.lint(pipeline, subject, motif, style)
        self.assertEqual(found, [
            f"{subject.path}: /text: contains the style term 'vinyl' (a style word belongs in the style pack 'clay', not here)",
            f"{motif.path}: /text: contains the style term 'toy-like' (a style word belongs in the style pack 'clay', not here)",
            f"{motif.path}: /text: contains the style term 'clay' (a style word belongs in the style pack 'clay', not here)"])
        raw = json.loads(PROP.read_text())
        raw["capture"]["framing"]["words"] += ", clay-free"
        raw["capture"]["background"]["words"] = "vinyl background"
        found = pr.lint(pf.validate(raw, "p.json"), subject, motif, style)
        self.assertIn("p.json: /capture/background/words: contains the style term 'vinyl' (a style word belongs in the style pack 'clay', not here)", found)
        self.assertEqual(len([f for f in found if f.startswith("p.json: /capture/framing")]), 1)  # "clay-free": the term 'clay' as a word

    @case
    def test_lint_does_not_match_inside_a_longer_word(self):
        pipeline = pf.load(PROP)
        style = pr.load_style(self.fx.root / "styles" / "clay")
        self.fx.edit("motif.json", lambda raw: raw.update(text="claymore parts"))
        found = pr.lint(pipeline, pr.load_subject(self.fx.root / "subject.json"), pr.load_motif(self.fx.root / "motif.json"), style)
        self.assertEqual(found, [])

    @case
    def test_cli_lint_fails_and_writes_nothing(self):
        self.fx.edit("subject.json", lambda raw: raw.update(text="a vinyl hand drill"))
        out = self.fx.root / "job.json"
        code, _, err = run_cli(self.fx.args("--lint", "--out", str(out)))
        self.assertEqual(code, 1)
        self.assertIn("/text: contains the style term 'vinyl'", err)
        self.assertFalse(out.exists())

    @case
    def test_cli_dry_run_prints_and_writes_nothing(self):
        before = sorted(p.name for p in self.fx.root.rglob("*"))
        code, out, _ = run_cli(self.fx.args("--lint", "--dry-run"))
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines()[0], f"prompt (concept): {CLAY_PROP}")
        self.assertIn("negative (concept): text, watermark", out)
        self.assertIn("shape_gate  mesh_gates", out)
        self.assertEqual(sorted(p.name for p in self.fx.root.rglob("*")), before)

    @case
    def test_cli_out_writes_the_job_and_is_deterministic(self):
        first, second = self.fx.root / "a" / "job.json", self.fx.root / "b" / "job.json"
        self.assertEqual(run_cli(self.fx.args("--out", str(first)))[0], 0)
        self.assertEqual(run_cli(self.fx.args("--out", str(second)))[0], 0)
        self.assertEqual(first.read_bytes(), second.read_bytes())
        job = json.loads(first.read_text())
        self.assertEqual((job["seed"], job["stages"][0]["prompt"]), (SEED, CLAY_PROP))

    @case
    def test_cli_needs_exactly_one_of_dry_run_and_out(self):
        self.assertEqual(run_cli(self.fx.args())[0], 2)
        self.assertEqual(run_cli(self.fx.args("--dry-run", "--out", str(self.fx.root / "x.json")))[0], 2)

    @case
    def test_icon_pipeline_resolves_with_the_icon_template(self):
        self.fx.edit("subject.json", lambda raw: raw.update(kind="icon"))
        self.fx.edit("contract.json", lambda raw: raw.update(kind="icon"))
        job = self.fx.resolve("vinyl_toy", pipeline=base.EXAMPLES / "icon.pipeline.json")
        self.assertEqual(job["stages"][0]["prompt"],
                         "a hand drill with a side handle, repair-shop, brass and recycled parts, flat toy-like icon, "
                         "flat pure bright magenta #ff00ff background, single isolated whole object, centered, generous margins, "
                         "readable inventory icon, no text or logos, no cast shadow")


class PromptPartsTests(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture()
        self.addCleanup(self.fx.temp.cleanup)

    def concept(self, style="clay", **kwargs):
        return self.fx.resolve(style, **kwargs)["stages"][0]

    def kinds(self, parts):
        return [(p["source"]["kind"], p["source"].get("id"), p["text"]) for p in parts]

    @case
    def test_parts_joined_are_the_prompt_for_each_style(self):
        for style, expected in (("vinyl_toy", VINYL_PROP), ("clay", CLAY_PROP)):
            stage = self.concept(style)
            self.assertEqual("".join(p["text"] for p in stage["prompt_parts"]), stage["prompt"])
            self.assertEqual(stage["prompt"], expected)
            at = 0
            for part in stage["prompt_parts"]:
                self.assertEqual((part["start"], part["end"]), (at, at + len(part["text"])))
                self.assertEqual(stage["prompt"][part["start"]:part["end"]], part["text"])
                at = part["end"]
            self.assertEqual(at, len(stage["prompt"]))

    @case
    def test_each_part_names_its_source(self):
        parts = self.concept("clay")["prompt_parts"]
        got = self.kinds(parts)
        self.assertEqual(got[0], ("subject", "hand_drill", "a hand drill with a side handle"))
        self.assertEqual(got[1], ("style_pack", "clay", " made of "))
        self.assertEqual(got[2][:2], ("motif", "repair_shop"))
        self.assertEqual(got[3], ("style_pack", "clay", ", hand-sculpted clay, visible thumb marks"))
        self.assertEqual([g[0] for g in got[4:]], ["glue", "pipeline", "glue", "pipeline", "glue", "pipeline"])
        self.assertEqual(parts[1]["source"]["key"], "prompt.templates.prop")
        self.assertEqual(parts[0]["source"]["sha256"], pr.load_subject(self.fx.root / "subject.json").sha256)
        self.assertEqual(parts[-1]["source"]["key"], "capture.view.words")
        self.assertEqual(parts[-1]["source"]["id"], "prop")

    @case
    def test_template_of_a_parent_pack_is_credited_to_the_parent_and_the_negative_to_its_owner(self):
        self.fx.edit("styles/clay/style.json", lambda raw: raw["prompt"]["templates"].pop("prop"))
        stage = self.concept("clay")
        self.assertEqual({p["source"]["id"] for p in stage["prompt_parts"] if p["source"]["kind"] == "style_pack"}, {"vinyl_toy"})
        self.assertEqual(self.kinds(stage["negative_parts"]), [("style_pack", "vinyl_toy", "text, watermark")])
        source = stage["negative_parts"][0]["source"]
        self.assertEqual((source["key"], source["version"]), ("prompt.negative", 1))
        self.assertEqual(stage["negative_parts"][0]["end"], len("text, watermark"))

    @case
    def test_trailing_commas_and_spaces_leave_the_parts_too(self):
        words = {"background": {"words": "bg"}, "framing": {"words": "fr"}}
        pieces = pr.assemble_parts("{subject}, {motif}, ", "S", "M, ", words)
        self.assertEqual("".join(t for t, _ in pieces), "S, M, bg, fr")
        self.assertEqual([t for t, _ in pieces], ["S", ", ", "M", ", ", "bg", ", ", "fr"])
        pieces = pr.assemble_parts("{subject} {motif}", "S", "M, ,", words)
        self.assertEqual([t for t, _ in pieces][:3], ["S", " ", "M"])
        self.assertEqual(pr.assemble_prompt("{subject} {motif}", "S", "M", words), "S M, bg, fr")

    @case
    def test_a_template_ending_in_a_variable_gives_no_empty_parts(self):
        words = {"background": {"words": "bg"}, "framing": {"words": "fr"}}
        pieces = pr.assemble_parts("x, {subject} {motif}", "S", " ,", words)
        self.assertTrue(all(text for text, _ in pieces))
        self.assertEqual("".join(t for t, _ in pieces), "x, S, bg, fr")

    @case
    def test_parts_do_not_change_any_stage_key(self):
        job = self.fx.resolve()
        stage = job["stages"][0]
        self.assertEqual(pr.canonical_sha256({"tool": stage["tool"], "model": stage["model"], "params": stage["params"],
                                              "gate": stage["gate"], "reads": stage["reads"]}), stage["key_inputs"])

    @case
    def test_only_the_concept_stage_has_parts(self):
        job = self.fx.resolve()
        self.assertEqual([s["id"] for s in job["stages"] if "prompt_parts" in s], ["concept"])


def tearDownModule():
    print(f"PIPELINE_FILES cases={base.TALLY['cases']} ok={base.TALLY['ok']}")
