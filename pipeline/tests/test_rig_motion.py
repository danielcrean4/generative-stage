"""The rig and motion stages: fitting a profile to a mesh, the rig gate and its mutants, the stand-in rigger and
animator in background Blender, and the character pipeline end to end on the stand-ins.

Blender tests are skipped with the reason when `blender` is not on PATH; the walkthrough also needs the tools
interpreter (docs/machine_settings.md)."""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "blender"))
import adapter_config as ac  # noqa: E402
import adapter_run  # noqa: E402
import glb_read  # noqa: E402
import machine  # noqa: E402
import pipeline_file as pf  # noqa: E402
import pipeline_resolve as pr  # noqa: E402
import pipeline_run as run  # noqa: E402
import rig_fixtures  # noqa: E402
import rig_gate  # noqa: E402
import venv_tool  # noqa: E402
from motion import fit, rig as rigs  # noqa: E402
from test_adapter_config import Recorder  # noqa: E402

DATA = HERE / "fixtures" / "pipeline_files"
CHARACTER = ROOT / "pipelines" / "examples" / "character.pipeline.json"
STANDIN = REPO / "adapters" / "standin" / "standin_blender.py"
PROFILE = REPO / "blender" / "examples" / "rigs" / "biped.json"
MANIFEST = REPO / "blender" / "examples" / "motion_manifest.json"
MOTIONS = REPO / "blender" / "motions"
GATE = {"min_weighted_share": 1.0, "max_influences": 4, "min_inside_share": 1.0}
CLIPS = ["idle", "walk", "run", "flinch"]
HAS_BLENDER = shutil.which("blender") is not None


def document(path):
    return glb_read.load(path)[0]


def character_job(seed=7):
    return pr.resolve(pf.load(CHARACTER), pr.load_subject(DATA / "character_subject.json"),
                      pr.load_motif(DATA / "motif.json"), pr.load_style(DATA / "styles" / "vinyl_toy"),
                      pr.load_contract(DATA / "character_contract.json"), seed)


class Temp(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)


class FitTests(unittest.TestCase):
    """motion/fit.py: plain Python, no Blender."""

    def setUp(self):
        self.rig = rigs.load(PROFILE)
        self.points = [(x * 0.5, y * 1.8 + 0.3, z * 0.3) for x in (-1, 1) for y in (0, 1) for z in (-1, 1)]

    def test_the_profile_is_scaled_to_the_mesh_height_and_stands_on_its_lowest_point(self):
        world, scales = fit.fit(self.rig, self.points)
        self.assertAlmostEqual(scales["height"], 1.8)
        self.assertAlmostEqual(scales["ground"], 0.3)
        self.assertAlmostEqual(min(world[s][1] for s in ("foot_l", "foot_r")), 0.3)
        self.assertAlmostEqual(world["head"][1] + fit.HEAD_TOP * scales["vertical"], 2.1)
        low, high = fit.LATERAL_RANGE
        self.assertTrue(low * scales["vertical"] <= scales["lateral"] <= high * scales["vertical"])

    def test_the_fitted_profile_has_its_ground_at_zero_and_loads(self):
        world, scales = fit.fit(self.rig, self.points)
        raw = fit.profile(self.rig, world, scales["ground"])
        path = Path(tempfile.mkstemp(suffix=".json")[1])
        self.addCleanup(path.unlink)
        path.write_text(json.dumps(raw))
        fitted = rigs.load(path)
        rest = rigs.forward(fitted, {})
        self.assertAlmostEqual(min(rest[s][0][1] for s in ("foot_l", "foot_r")), 0.0, places=5)
        self.assertEqual(fitted.roles, self.rig.roles)
        self.assertEqual(fitted.joints["knee_l"].limits, self.rig.joints["knee_l"].limits)

    def test_a_joint_outside_the_body_is_pulled_just_inside(self):
        world, scales = fit.fit(self.rig, self.points)
        outside = {"wrist_l"}

        def inside(point):
            return point != world_before["wrist_l"]

        world_before = dict(world)
        moved = fit.pull_inside(world, self.rig, scales["height"], lambda p: inside(p) if p in world_before.values()
                                else True, lambda p: ((0.5, p[1], p[2]), (1.0, 0.0, 0.0)))
        self.assertEqual(set(moved), outside)
        self.assertAlmostEqual(world["wrist_l"][0], 0.5 - fit.INSIDE_DEPTH * scales["height"])

    def test_every_point_is_weighted_to_at_most_four_bones_summing_to_one(self):
        world, scales = fit.fit(self.rig, self.points)
        segments = fit.segments(self.rig, world, scales["vertical"])
        self.assertNotIn("root", segments)
        for weights in fit.weights(self.points + [world["knee_l"]], segments):
            self.assertTrue(1 <= len(weights) <= fit.MAX_INFLUENCES)
            self.assertAlmostEqual(sum(weights.values()), 1.0)
        knee = fit.weights([world["knee_l"]], segments)[0]
        self.assertEqual(max(knee, key=knee.get) in ("knee_l", "hip_l"), True)


class RigGateTests(Temp):
    """rig_gate.py on a hand-made rig and its mutants: standard library only."""

    def judge(self, data, gate=GATE):
        path = self.dir / "rigged.glb"
        path.write_bytes(data)
        return rig_gate.judge(path, gate)

    def test_a_good_rig_passes(self):
        report = self.judge(rig_fixtures.skinned(1.4))
        self.assertEqual((report["verdict"], report["reasons"]), ("pass", []))
        self.assertEqual(report["facts"]["unused"], ["elbow_l", "elbow_r", "knee_l", "knee_r", "root", "wrist_l",
                                                     "wrist_r"])

    def test_each_mutant_fails_on_its_own_measure(self):
        expected = {"unweighted_lower_half": ("weighted_share", "carry no bone weight"),
                    "bone_outside": ("inside_share", "bones outside the mesh: head"),
                    "too_many_influences": ("influences", "a vertex follows 5 bones")}
        self.assertEqual(set(expected), set(rig_fixtures.MUTANTS))
        good = rig_fixtures.skinned(1.4)
        for name, (measure, words) in expected.items():
            with self.subTest(mutant=name):
                report = self.judge(rig_fixtures.MUTANTS[name](good))
                self.assertEqual(report["verdict"], "fail")
                self.assertEqual([m for m, v in report["measures"].items() if v["outcome"] == "fail"], [measure])
                self.assertIn(words, " ".join(report["reasons"]))

    def test_a_mesh_with_no_skin_fails_with_a_reason(self):
        report = self.judge(rig_fixtures.humanoid())
        self.assertEqual(report["verdict"], "fail")
        self.assertIn("no skinned mesh", report["reasons"][0])

    def test_the_gate_block_has_no_defaults(self):
        for gate, message in (({}, "missing min_weighted_share"), ({**GATE, "extra": 1}, "unknown extra"),
                              ({**GATE, "max_influences": 0}, "max_influences"),
                              ({**GATE, "min_inside_share": 1.5}, "min_inside_share")):
            with self.subTest(gate=gate), self.assertRaisesRegex(ValueError, message):
                rig_gate.parse_gate(gate)

    def test_the_command_line_writes_the_report_and_exits_by_verdict(self):
        good, bad = self.dir / "good.glb", self.dir / "bad.glb"
        good.write_bytes(rig_fixtures.skinned())
        bad.write_bytes(rig_fixtures.bone_outside(rig_fixtures.skinned()))
        (self.dir / "gate.json").write_text(json.dumps(GATE))
        for path, code in ((good, 0), (bad, 1)):
            out = self.dir / path.stem
            result = subprocess.run([sys.executable, "-I", str(ROOT / "rig_gate.py"), str(path), "--gate",
                                     str(self.dir / "gate.json"), "--out", str(out)], capture_output=True, timeout=60)
            self.assertEqual(result.returncode, code, result.stderr)
            self.assertEqual(json.loads((out / "rig-validation.json").read_text())["verdict"],
                             "pass" if code == 0 else "fail")


class PipelineFileTests(unittest.TestCase):
    def test_the_character_pipeline_validates_and_resolves(self):
        job = character_job()
        self.assertEqual([s["tool"] for s in job["stages"]][-3:], ["rig", "rig_gate", "motion"])
        self.assertEqual(run.final_of(job), ("motion", "animated.glb"))

    def test_bad_rig_stages_are_refused_when_the_file_loads(self):
        raw = json.loads(CHARACTER.read_text())
        cases = (
            ((-1, "params", "clips"), "idle --output /etc/passwd", "clip names joined by commas"),
            ((-1, "params", "clips"), "idle,idle", "distinct clip names"),
            ((-2, "gate", "max_influences"), 99, "max_influences"),
            ((-1, "inputs", "rig"), "rig/rigged.glb", "a rig input must be a .json file"),
            ((-3, "model"), {"argv": ["/bin/sh"]}, "must be an adapter id"),
        )
        for (index, *keys), value, message in cases:
            changed = json.loads(json.dumps(raw))
            target = changed["stages"][index]
            for key in keys[:-1]:
                target = target[key]
            target[keys[-1]] = value
            with self.subTest(value=value), self.assertRaisesRegex(pf.PipelineError, message):
                pf.validate(changed, "c.json")


class AdapterTests(Temp):
    """The rig and motion kinds through the adapter machinery: placeholders, the trust rule, host requirements."""

    def test_the_stand_ins_are_the_defaults_and_need_blender(self):
        adapters = ac.parse({}, "none")
        self.assertEqual((adapters.defaults["rig"], adapters.defaults["motion"]), ("standin-rig", "standin-motion"))
        self.assertEqual(adapters.entries["standin-rig"].needs(), ("cpu", "blender"))
        with patch.object(ac.host.shutil, "which", return_value=None), \
                self.assertRaisesRegex(adapter_run.Refused, "needs Blender, run headless"):
            adapter_run.check_host(adapters.entries["standin-rig"])

    def test_each_kind_takes_only_its_own_placeholders(self):
        base = {"id": "r", "sandbox": {"network": "deny"}, "licence": "MIT"}
        ac.parse_entry({**base, "kind": "rig", "argv": ["/r", "{mesh}", "{output}", "{out_dir}", "{seed}"]}, "m")
        ac.parse_entry({**base, "kind": "motion", "argv": ["/m", "{mesh}", "{rig}", "{params.clips}", "{output}"]}, "m")
        for kind, part in (("rig", "{rig}"), ("rig", "{image}"), ("motion", "{prompt}"), ("rig", "{mesh}x{repo}{x}")):
            with self.subTest(kind=kind, part=part), self.assertRaisesRegex(ac.AdapterError, "unknown placeholder"):
                ac.parse_entry({**base, "kind": kind, "argv": ["/p", part]}, "m")
        with self.assertRaisesRegex(ac.AdapterError, "unknown placeholder"):
            ac.parse_entry({**base, "kind": "rig", "argv": ["{mesh}"]}, "m")  # argv[0] is never a run's value

    def test_a_motion_stage_supplies_values_and_never_a_command(self):
        configured = {"id": "anim", "kind": "motion", "sandbox": {"network": "deny"}, "licence": "MIT",
                      "argv": ["/opt/anim/run", "--in={mesh}", "--rig", "{rig}", "--clips", "{params.clips}",
                               "--out", "{output}"]}
        adapters = ac.parse({"adapters": [configured]}, "machine.json")
        stage = {**next(s for s in character_job()["stages"] if s["tool"] == "motion"), "model": "anim",
                 "argv": ["/bin/sh"], "env": {"LD_PRELOAD": "/x"}}
        recorder = Recorder()
        (self.dir / "step.log").write_text("")
        mesh = self.dir / "a b; rm -rf ~ {python}.glb"
        with patch.object(adapter_run.local_run, "execute", recorder), \
                patch.object(adapter_run.host, "unmet", return_value=[]):
            run.default_runners(adapters=adapters)["motion"].run(stage, {"mesh": mesh, "rig": self.dir / "rig.json"},
                                                                 self.dir, 5)
        argv = recorder.calls[0]["argv"]
        self.assertEqual(argv, ["/opt/anim/run", f"--in={mesh}", "--rig", str(self.dir / "rig.json"), "--clips",
                                "idle,walk,run,flinch", "--out", str(self.dir / "animated.glb")])
        self.assertEqual((recorder.calls[0]["env"], recorder.calls[0]["network"]), ({}, "deny"))


@unittest.skipUnless(HAS_BLENDER, "Blender is not on PATH")
class StandinBlenderTests(Temp):
    """The stand-in rigger and animator in background Blender, through their adapter program."""

    def standin(self, *args, env=None):
        return subprocess.run([sys.executable, "-I", str(STANDIN), *map(str, args)], capture_output=True, text=True,
                              timeout=300, env=env)

    def rig(self, body):
        (self.dir / "body.glb").write_bytes(body)
        out = self.dir / "rig"
        result = self.standin("rig", "--mesh", self.dir / "body.glb", "--profile", PROFILE, "--output",
                              out / "rigged.glb", "--out-dir", out)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return out

    def test_a_body_is_rigged_gated_animated_and_exported_with_its_clips(self):
        out = self.rig(rig_fixtures.humanoid(1.4))
        rigged = document(out / "rigged.glb")
        self.assertEqual(len(rigged["skins"]), 1)
        attributes = rigged["meshes"][0]["primitives"][0]["attributes"]
        self.assertTrue({"JOINTS_0", "WEIGHTS_0"} <= set(attributes))
        self.assertNotIn("animations", rigged)
        self.assertEqual(rig_gate.judge(out / "rigged.glb", GATE)["verdict"], "pass")
        self.assertEqual(json.loads((out / "identity.json").read_text())["mode"], "rig")
        self.assertEqual(set(rigs.load(out / "rig.json").joints), set(rigs.load(PROFILE).joints))

        motion = self.dir / "motion"
        result = self.standin("motion", "--mesh", out / "rigged.glb", "--rig", out / "rig.json", "--clips",
                              ",".join(CLIPS), "--manifest", MANIFEST, "--motions", MOTIONS, "--output",
                              motion / "animated.glb", "--out-dir", motion)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        animated = document(motion / "animated.glb")
        self.assertEqual(sorted(a["name"] for a in animated["animations"]), sorted(CLIPS))
        self.assertEqual(len(animated["skins"]), 1)
        report = json.loads((motion / "clips.json").read_text())
        self.assertEqual({c["name"]: c["problems"] for c in report["clips"]}, {name: [] for name in CLIPS})
        self.assertIn("motions/locomotion_biped.py", json.loads((motion / "identity.json").read_text())["scripts_sha256"])

    def test_mutants_of_the_stand_in_output_fail_the_gate(self):
        good = (self.rig(rig_fixtures.humanoid(1.4)) / "rigged.glb").read_bytes()
        for name, mutate in rig_fixtures.MUTANTS.items():
            with self.subTest(mutant=name):
                path = self.dir / f"{name}.glb"
                path.write_bytes(mutate(good))
                self.assertEqual(rig_gate.judge(path, GATE)["verdict"], "fail")

    def test_an_unknown_clip_is_refused_with_the_clips_on_offer(self):
        out = self.rig(rig_fixtures.humanoid())
        result = self.standin("motion", "--mesh", out / "rigged.glb", "--rig", out / "rig.json", "--clips", "moonwalk",
                              "--manifest", MANIFEST, "--motions", MOTIONS, "--output", self.dir / "m" / "animated.glb",
                              "--out-dir", self.dir / "m")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no clip moonwalk for a rig called 'biped' (offered:", result.stdout + result.stderr)

    def test_without_blender_it_says_so(self):
        result = self.standin("rig", "--mesh", "x.glb", "--profile", PROFILE, "--output", self.dir / "r.glb",
                              "--out-dir", self.dir, env={"PATH": str(self.dir)})
        self.assertEqual(result.returncode, 2)
        self.assertIn("need Blender", result.stderr)


class WalkthroughTests(Temp):
    """The character pipeline on a machine config that names no model: concept, mesh, clean-up and shape gate as in
    the prop walkthrough, then rig, rig gate and motion on the stand-ins; and the same pipeline stopped by the rig gate
    when a mutant rig is supplied."""

    def run_pipeline(self, *extra, config=None):
        config = config or {}
        file = self.dir / "machine.json"
        file.write_text(json.dumps(config))
        out, errors = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, {machine.CONFIG_ENV: str(file), "HOME": str(self.dir),
                                     "GENSTAGE_IDENTITY_CACHE": str(self.dir / "cache.json")}), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(errors):
            code = run.main(["--pipeline", str(CHARACTER), "--subject", str(DATA / "character_subject.json"),
                             "--motif", str(DATA / "motif.json"), "--style", str(DATA / "styles" / "vinyl_toy"),
                             "--contract", str(DATA / "character_contract.json"), "--seed", "7",
                             "--out-root", str(self.dir / "out"), "--review-sheet",
                             str(ROOT / "pipelines" / "examples" / "finish.prop.json"), *extra])
        record = json.loads(next((self.dir / "out" / "attempts").glob("*/attempt.json")).read_text())
        return code, record, errors.getvalue() + out.getvalue()

    @unittest.skipUnless(HAS_BLENDER, "Blender is not on PATH")
    def test_the_character_pipeline_runs_end_to_end_on_the_stand_in(self):
        venv_tool.require_venv(self)
        code, record, said = self.run_pipeline(config={"tools_python": str(venv_tool.interpreter())})
        self.assertEqual(code, 0, said)
        self.assertEqual(record["status"], "generated")
        for stage, adapter in (("rig", "standin-rig"), ("motion", "standin-motion")):
            entry = record["stages"][stage]
            self.assertEqual(entry["model"]["adapter"], adapter)
            self.assertEqual(entry["model_reported"]["name"], "standin")
            self.assertIn("files_sha256", entry["model"])
            self.assertNotIn("identity.json", entry["outputs"])
        self.assertEqual(record["stages"]["rig_gate"]["gate"]["verdict"], "pass")
        self.assertEqual(set(record["stages"]["rig"]["outputs"]) >= {"rigged.glb", "rig.json"}, True)
        self.assertEqual(record["final"]["stage"], "motion")
        final = self.dir / "out" / record["final"]["path"]
        self.assertEqual(sorted(a["name"] for a in document(final)["animations"]), sorted(CLIPS))
        sidecar = json.loads(final.with_suffix(".source.json").read_text())
        self.assertEqual(sidecar["models"]["rig"]["adapter"], "standin-rig")

    def test_a_mutant_rig_is_stopped_by_the_rig_gate_and_nothing_is_animated(self):
        mutant, rig_file = self.dir / "mutant.glb", self.dir / "rig.json"
        mutant.write_bytes(rig_fixtures.unweighted_lower_half(rig_fixtures.skinned(1.4)))
        rig_file.write_text(PROFILE.read_text())
        code, record, said = self.run_pipeline("--start-at", "rig_gate", "--input", f"rig/rigged.glb={mutant}",
                                               "--input", f"rig/rig.json={rig_file}")
        self.assertEqual(code, 1, said)
        self.assertEqual((record["status"], record["not_run"]), ("failed", ["motion"]))
        self.assertEqual(record["verdict"]["stage"], "rig_gate")
        self.assertIn("weighted_share", record["verdict"]["deciding"])
        self.assertIn("carry no bone weight", " ".join(record["verdict"]["reasons"]))


if __name__ == "__main__":
    unittest.main()
