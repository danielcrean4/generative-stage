# SPDX-License-Identifier: MIT OR GPL-3.0-or-later
"""Two-legged locomotion: idle, walk and run, made in place (the game moves the body).

Feet are placed by IK, so they stay planted while the body travels at the clip's speed. Roles:
root, hip_l/r, knee_l/r, foot_l/r (sites on the soles), body, head, shoulder_l/r, elbow_l/r.
A rig without legs still gets the upper-body motion.
"""
import math

from motion import curves, ik

DEFAULTS = {
    "idle": {"length": 2.4, "breathe": 0.012, "sway": 0.03, "look": 0.25},
    # stride: how far a foot travels while planted (m); stance: share of the cycle a foot is down
    "walk": {"period": 0.62, "stride": 0.34, "stance": 0.6, "crouch": 0.07, "lift": 0.07, "bob": 0.012,
             "lean": 0.08, "arm_swing": 0.45, "elbow": 0.35},
    "run": {"period": 0.42, "stride": 0.44, "stance": 0.42, "crouch": 0.12, "lift": 0.12, "bob": 0.02,
            "lean": 0.22, "arm_swing": 0.8, "elbow": 0.9},
}
EVENTS = {"walk": ["footfall_l", "footfall_r"], "run": ["footfall_l", "footfall_r"]}
SIDES = {"l": 0.0, "r": 0.5}  # where in the cycle each foot lands


def idle(rig, p, rng) -> curves.Clip:
    period = p["length"]
    clip = curves.Clip("idle", rig, period, loop=True)
    look_phase = rng.random()  # where in its slow glance the head starts

    def drop(t: float) -> tuple:
        return (0.0, -p["breathe"] * (1.0 + curves.wave(t, period)) - 0.02, 0.0)

    clip.move("root", drop)
    ik.plant_legs(clip, drop)
    clip.rotate("body", lambda t: (p["breathe"] * 2 * curves.wave(t, period), p["sway"] * curves.wave(t, period, 0.25), 0.0))
    clip.rotate("head", lambda t: (0.0, p["look"] * curves.wave(t, period, look_phase), 0.0))
    for side, out in (("l", 1.0), ("r", -1.0)):
        clip.rotate(f"shoulder_{side}", lambda t, o=out: (0.04 * curves.wave(t, period, 0.1), 0.0, o * 0.06))
        clip.rotate(f"elbow_{side}", lambda t: (-0.25, 0.0, 0.0))
        clip.contact(f"foot_{side}", 0.0, period)
    return clip


def gait(name: str):
    def make(rig, p, rng) -> curves.Clip:
        period, stride, stance = p["period"], p["stride"], p["stance"]
        clip = curves.Clip(name, rig, period, loop=True, speed=stride / (stance * period))
        swing = p["arm_swing"] * (1.0 + rng.uniform(-0.06, 0.06))  # a little character per rig

        def cycle(side: str, t: float) -> float:
            return (t / period + SIDES[side]) % 1.0

        def foot_z(side: str, t: float) -> float:
            """Foot position along +Z, relative to its rest place."""
            u = cycle(side, t)
            if u < stance:  # planted: slides back under the body at exactly the body's speed
                return stride / 2 - stride * (u / stance)
            return -stride / 2 + stride * curves.smooth((u - stance) / (1.0 - stance))  # swinging forward

        def foot(side: str, t: float) -> tuple:
            u = cycle(side, t)
            lift = 0.0 if u < stance else p["lift"] * math.sin(math.pi * (u - stance) / (1.0 - stance))
            return (0.0, lift, foot_z(side, t))

        def drop(t: float) -> tuple:
            return (0.0, -p["crouch"] + p["bob"] * curves.wave(t, period / 2, 0.25), 0.0)

        clip.move("root", drop)
        ik.plant_legs(clip, drop, foot)
        clip.rotate("body", lambda t: (p["lean"], 0.08 * curves.wave(t, period), 0.0))
        clip.rotate("head", lambda t: (-p["lean"] * 0.6, -0.06 * curves.wave(t, period), 0.0))
        for side in SIDES:
            # an arm swings back while its own foot is forward (+X swings a hanging arm back)
            clip.rotate(f"shoulder_{side}", lambda t, s=side: (swing * foot_z(s, t) / (stride / 2), 0.0, 0.0))
            clip.rotate(f"elbow_{side}", lambda t: (-p["elbow"], 0.0, 0.0))
            land = ((-SIDES[side]) % 1.0) * period
            clip.event(land, f"footfall_{side}")
            clip.contact(f"foot_{side}", land, land + stance * period)
        return clip
    return make


CLIPS = {"idle": idle, "walk": gait("walk"), "run": gait("run")}
