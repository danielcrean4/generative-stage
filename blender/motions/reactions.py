# SPDX-License-Identifier: MIT OR GPL-3.0-or-later
"""Reactions to being hit: flinch, stagger, knockout and getting back up. Not looping.

Works on legged and wheeled rigs alike: feet stay planted by IK while the body drops, and a rig
without legs just tips its body. Roles: root, hip_l/r, knee_l/r, foot_l/r, body, head,
shoulder_l/r, elbow_l/r.
"""
from motion import curves, ik

DEFAULTS = {
    "flinch": {"length": 0.45, "attack": 0.06, "hold": 0.05, "recoil": 0.28, "guard": 0.7},
    "stagger": {"length": 0.9, "attack": 0.12, "hold": 0.15, "recoil": 0.45, "guard": 0.4, "drift": 0.08},
    # slump: how far the root drops when down (m), so legs fold; pitch: how far the body tips (rad)
    # squash: the same, for a rig with no legs to fold (suspension only)
    "knockout": {"length": 1.1, "fall": 0.8, "slump": 0.22, "squash": 0.03, "pitch": 0.9},
    "get_up": {"length": 1.2, "slump": 0.22, "squash": 0.03, "pitch": 0.9},
}
EVENTS = {"flinch": ["impact"], "stagger": ["impact"], "knockout": ["down"], "get_up": ["up"]}


def recoil(name: str):
    """A hit pushes the body back and the arms up to guard, then it settles again."""
    def make(rig, p, rng) -> curves.Clip:
        clip = curves.Clip(name, rig, p["length"], loop=False)
        side_bias = rng.uniform(-1.0, 1.0)  # which shoulder takes more of the hit

        def amount(t: float) -> float:
            return curves.envelope(t, p["attack"], p["hold"], p["length"] - p["attack"] - p["hold"])

        drift = p.get("drift", 0.02)

        def push(t: float) -> tuple:
            return (0.0, -0.04 * amount(t), -drift * amount(t))

        ik.lower(clip, push)
        clip.rotate("body", lambda t: (-p["recoil"] * amount(t), 0.15 * side_bias * amount(t), 0.0))
        clip.rotate("head", lambda t: (-0.5 * p["recoil"] * amount(t), 0.0, 0.0))
        for side, out in (("l", 1.0), ("r", -1.0)):
            clip.rotate(f"shoulder_{side}", lambda t, o=out: (-p["guard"] * amount(t), 0.0, o * 0.3 * amount(t)))
            clip.rotate(f"elbow_{side}", lambda t: (-0.25 - 1.0 * amount(t), 0.0, 0.0))
        clip.event(0.0, "impact")
        return clip
    return make


def _down_pose(clip: curves.Clip, p: dict, down) -> None:
    """Keys a fall: down(t) runs 0 (standing) to 1 (collapsed)."""
    drop = p["slump"] if clip.rig.role("knee_l") else p["squash"]

    def slump(t: float) -> tuple:
        return (0.0, -drop * down(t), 0.0)

    ik.lower(clip, slump)
    clip.rotate("body", lambda t: (p["pitch"] * down(t), 0.0, 0.0))
    clip.rotate("head", lambda t: (0.4 * down(t), 0.0, 0.0))
    for side in ("l", "r"):
        # the arms swing back against the tipping body, so they hang rather than dig in
        clip.rotate(f"shoulder_{side}", lambda t: (-0.7 * p["pitch"] * down(t), 0.0, 0.0))
        clip.rotate(f"elbow_{side}", lambda t: (-0.25 - 0.2 * down(t), 0.0, 0.0))


def knockout(rig, p, rng) -> curves.Clip:
    clip = curves.Clip("knockout", rig, p["length"], loop=False)
    _down_pose(clip, p, lambda t: curves.smooth(t / p["fall"]) ** 1.5)  # slow to start, then drops
    clip.event(p["fall"], "down")
    return clip


def get_up(rig, p, rng) -> curves.Clip:
    clip = curves.Clip("get_up", rig, p["length"], loop=False)
    _down_pose(clip, p, lambda t: 1.0 - curves.smooth(t / p["length"]))
    clip.event(p["length"], "up")
    return clip


CLIPS = {"flinch": recoil("flinch"), "stagger": recoil("stagger"), "knockout": knockout, "get_up": get_up}
