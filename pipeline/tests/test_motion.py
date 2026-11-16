"""Motion families: rigs, kinematics, IK, checks and the runner. Plain Python:
python3 -m unittest discover -s tests"""
import contextlib
import io
import json
import math
import random
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BLENDER = ROOT.parent / "blender"
sys.path.insert(0, str(BLENDER))
sys.path.insert(0, str(BLENDER / "motions"))

import build_motions  # noqa: E402
from motion import checks, curves, ik, rig as rigs  # noqa: E402

BIPED = BLENDER / "examples" / "rigs" / "biped.json"
MANIFEST = BLENDER / "examples" / "motion_manifest.json"


def close(a, b, tol: float = 1e-6) -> bool:
    return all(abs(x - y) <= tol for x, y in zip(a, b))


class RigTest(unittest.TestCase):
    def write(self, data: dict) -> Path:
        path = Path(tempfile.mkstemp(suffix=".json")[1])
        path.write_text(json.dumps(data))
        self.addCleanup(path.unlink)
        return path

    def test_joints_come_parent_first(self) -> None:
        rig = rigs.load(self.write({"name": "t", "joints": {
            "b": {"parent": "a", "offset": [0, 1, 0]}, "a": {"parent": None, "offset": [0, 0, 0]}}}))
        self.assertEqual(list(rig.joints), ["a", "b"])

    def test_bad_rigs_are_refused(self) -> None:
        for joints, extra in (
            ({"a": {"parent": "missing", "offset": [0, 0, 0]}}, {}),
            ({"a": {"parent": None, "offset": [0, 0, 0]}}, {"sites": {"s": {"parent": "nope", "offset": [0, 0, 0]}}}),
            ({"a": {"parent": None, "offset": [0, 0, 0]}}, {"mirrored": ["ghost"]}),
        ):
            with self.subTest(joints=joints, extra=extra), self.assertRaises(ValueError):
                rigs.load(self.write({"name": "t", "joints": joints, **extra}))

    def test_euler_is_godot_yxz(self) -> None:
        # Y then X then Z, applied to a vector as Ry · Rx · Rz · v
        self.assertTrue(close(rigs.apply(rigs.euler((0, math.pi / 2, 0)), (0, 0, 1)), (1, 0, 0)))
        self.assertTrue(close(rigs.apply(rigs.euler((math.pi / 2, 0, 0)), (0, 1, 0)), (0, 0, 1)))
        both = rigs.mul(rigs.mul(rigs.euler((0, 0.3, 0)), rigs.euler((0.5, 0, 0))), rigs.euler((0, 0, 0.7)))
        self.assertTrue(all(close(a, b) for a, b in zip(both, rigs.euler((0.5, 0.3, 0.7)))))

    def test_forward_chains_rotations(self) -> None:
        rig = rigs.load(self.write({"name": "t", "joints": {
            "a": {"parent": None, "offset": [0, 0, 0]}, "b": {"parent": "a", "offset": [0, 1, 0]}},
            "sites": {"tip": {"parent": "b", "offset": [0, 1, 0]}}}))
        world = rigs.forward(rig, {"a": (math.pi / 2, 0, 0)}, {"a": (0, 0.5, 0)})
        self.assertTrue(close(world["b"][0], (0, 0.5, 1)))
        self.assertTrue(close(world["tip"][0], (0, 0.5, 2)))


class IkTest(unittest.TestCase):
    def test_round_trip_lands_on_the_target(self) -> None:
        upper, lower = (0.03, -0.18, 0.07), (0.0, -0.30, -0.07)
        rng = random.Random(7)
        for _ in range(200):
            target = (upper[0] + lower[0], rng.uniform(-0.45, -0.15), rng.uniform(-0.2, 0.2))
            a, b, reached = ik.two_bone_x(upper, lower, target)
            knee = rigs.apply(rigs.euler((a, 0, 0)), upper)
            end = rigs.add(knee, rigs.apply(rigs.euler((a + b, 0, 0)), lower))
            self.assertTrue(reached)
            self.assertTrue(close(end[1:], target[1:], 1e-9), (end, target))

    def test_out_of_reach_says_so(self) -> None:
        self.assertFalse(ik.two_bone_x((0, -0.2, 0), (0, -0.2, 0), (0, -1.0, 0))[2])

    def test_keeps_the_rest_bend_direction(self) -> None:
        _, bend, _ = ik.two_bone_x((0, -0.2, 0.05), (0, -0.2, -0.05), (0, -0.3, 0))
        self.assertGreater(bend, 0.0)  # a knee that rests bent forward keeps bending forward


class ChecksTest(unittest.TestCase):
    def setUp(self) -> None:
        self.rig = rigs.load(BIPED)

    def clip(self, **kw) -> curves.Clip:
        return curves.Clip("t", self.rig, kw.pop("length", 1.0), kw.pop("loop", False), **kw)

    def test_limits(self) -> None:
        clip = self.clip()
        clip.rotate("knee_l", lambda t: (3.0 * t, 0, 0))
        self.assertTrue(any(p.startswith("limits: knee_l") for p in checks.check(clip)))

    def test_loop(self) -> None:
        clip = self.clip(loop=True)
        clip.rotate("body", lambda t: (0.5 * t, 0, 0))
        self.assertTrue(any(p.startswith("loop: body") for p in checks.check(clip)))

    def test_events(self) -> None:
        self.assertEqual(checks.check(self.clip(), ["hit"]), ["events: no 'hit' event"])

    def test_floor(self) -> None:
        clip = self.clip()
        clip.move("root", lambda t: (0, -0.2 * t, 0))  # sinks without bending the knees
        self.assertTrue(any(p.startswith("floor: foot_") for p in checks.check(clip)))

    def test_slide(self) -> None:
        clip = self.clip(speed=1.0)  # the body moves but the planted foot doesn't slide back
        clip.contact("foot_l", 0.0, 0.5)
        self.assertTrue(any(p.startswith("slide: foot_l") for p in checks.check(clip)))

    def test_a_still_clip_passes(self) -> None:
        clip = self.clip(loop=True)
        clip.contact("foot_l", 0.0, 1.0)
        self.assertEqual(checks.check(clip), [])


class RunnerTest(unittest.TestCase):
    def build(self) -> Path:
        out = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: [p.unlink() for p in sorted(out.rglob("*"), reverse=True) if p.is_file()])
        with contextlib.redirect_stdout(io.StringIO()):  # the runner prints a line per clip
            self.assertTrue(build_motions.build(MANIFEST, [BLENDER / "motions"], out, []))
        return out

    def test_every_example_clip_passes_and_rebuilds_identically(self) -> None:
        first, second = self.build(), self.build()
        files = sorted(p.relative_to(first) for p in first.rglob("*.json"))
        self.assertGreater(len(files), 10)
        for rel in files:
            with self.subTest(str(rel)):
                self.assertEqual((first / rel).read_bytes(), (second / rel).read_bytes())

    def test_clips_round_trip_through_json(self) -> None:
        out = self.build()
        rig = rigs.load(BIPED)
        data = json.loads((out / "biped" / "walk.json").read_text())
        again = curves.from_dict(data, rig).to_dict()
        self.assertEqual(again, data)


if __name__ == "__main__":
    unittest.main()
