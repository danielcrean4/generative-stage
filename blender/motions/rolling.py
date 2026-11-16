# SPDX-License-Identifier: MIT OR GPL-3.0-or-later
"""Wheeled or tracked locomotion: idle, walk and run, made in place (the game moves the body).

Wheels spin at exactly the clip's speed for their radius; each clip lasts a whole number of
turns so it loops. Roles: root, wheel_l/r (optional: tracks have none), body, head,
shoulder_l/r, elbow_l/r.
"""
import math

from motion import curves, ik

DEFAULTS = {
    "idle": {"length": 2.0, "bob": 0.004, "look": 0.2},
    "walk": {"speed": 1.2, "wheel_radius": 0.19, "turns": 1, "lean": 0.05, "bob": 0.004, "arm_sway": 0.12},
    "run": {"speed": 3.5, "wheel_radius": 0.19, "turns": 2, "lean": 0.14, "bob": 0.007, "arm_sway": 0.25},
}
BUMPS_PER_CLIP = 4  # suspension bobs while rolling: any whole number keeps the loop seamless


def idle(rig, p, rng) -> curves.Clip:
    period = p["length"]
    clip = curves.Clip("idle", rig, period, loop=True)
    look_phase = rng.random()
    ik.lower(clip, lambda t: (0.0, p["bob"] * curves.wave(t, period), 0.0))
    clip.rotate("head", lambda t: (0.0, p["look"] * curves.wave(t, period, look_phase), 0.0))
    for side in ("l", "r"):
        clip.rotate(f"elbow_{side}", lambda t: (-0.25, 0.0, 0.0))
    return clip


def roll(name: str):
    def make(rig, p, rng) -> curves.Clip:
        speed, radius = p["speed"], p["wheel_radius"]
        length = p["turns"] * 2.0 * math.pi * radius / speed
        clip = curves.Clip(name, rig, length, loop=True, speed=speed)
        bump = length / BUMPS_PER_CLIP
        jitter = rng.random()  # where in its bump the suspension starts
        ik.lower(clip, lambda t: (0.0, p["bob"] * curves.wave(t, bump, jitter), 0.0))
        for side in ("l", "r"):
            clip.rotate(f"wheel_{side}", lambda t: (speed * t / radius, 0.0, 0.0))
            clip.rotate(f"shoulder_{side}", lambda t, s=(1.0 if side == "l" else -1.0): (p["arm_sway"] * s * curves.wave(t, length / p["turns"]), 0.0, 0.0))
            clip.rotate(f"elbow_{side}", lambda t: (-0.4, 0.0, 0.0))
        clip.rotate("body", lambda t: (p["lean"], 0.0, 0.0))
        clip.rotate("head", lambda t: (-p["lean"] * 0.5, 0.0, 0.0))
        return clip
    return make


CLIPS = {"idle": idle, "walk": roll("walk"), "run": roll("run")}
