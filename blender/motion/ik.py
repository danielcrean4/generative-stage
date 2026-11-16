# SPDX-License-Identifier: MIT OR GPL-3.0-or-later
"""Inverse kinematics, solved when a clip is generated so the game only plays it back.

lower and plant_legs key whole legs for a family; two_bone_x is the solver underneath. It solves a
leg or arm that bends around X (a hinge in the forward/up plane): given
where the end (a foot or hand site) should be, it returns the upper and lower joints' X
rotations. X positions can't change under X rotation, so only the target's Y and Z matter.
"""
import math
from collections.abc import Callable

from . import curves
from . import rig as rigs

REACH = 0.999  # never solve to a perfectly straight limb: the bend direction would flip


def two_bone_x(upper: rigs.Vec, lower: rigs.Vec, target: rigs.Vec) -> tuple[float, float, bool]:
    """(upper joint angle, lower joint angle, reached) for an end target.

    upper is the lower joint's rest offset from the upper joint; lower is the end site's rest
    offset from the lower joint; target is where the end should be, relative to the upper
    joint, in the upper joint's unrotated frame. The limb keeps bending the way it bends at
    rest. If the target is out of reach, the limb points at it as far as it goes.
    """
    l1, l2 = math.hypot(upper[1], upper[2]), math.hypot(lower[1], lower[2])
    want = math.hypot(target[1], target[2])
    reach = min(max(want, abs(l1 - l2) / REACH), (l1 + l2) * REACH)
    rest_bend = _wrap(_angle(lower) - _angle(upper))
    cos_bend = (reach * reach - l1 * l1 - l2 * l2) / (2.0 * l1 * l2)
    bend = math.copysign(math.acos(max(-1.0, min(1.0, cos_bend))), rest_bend if rest_bend else 1.0)
    lower_angle = bend - rest_bend
    c, s = math.cos(lower_angle), math.sin(lower_angle)
    end = (upper[1] + lower[1] * c - lower[2] * s, upper[2] + lower[1] * s + lower[2] * c)
    upper_angle = _wrap(_angle(target) - math.atan2(end[1], end[0]))
    return upper_angle, _wrap(lower_angle), abs(reach - want) < 1e-6


def lower(clip: curves.Clip, drop: Callable[[float], rigs.Vec]) -> None:
    """Moves the body by drop(t). On legs, the root moves and the legs fold to keep the feet
    planted; on wheels or tracks, which would sink with the root, the body rides its suspension."""
    if clip.rig.role("knee_l"):
        clip.move("root", drop)
        plant_legs(clip, drop)
    else:
        clip.move("body", drop)


def plant_legs(clip: curves.Clip, root_move: Callable[[float], rigs.Vec],
               foot: Callable[[str, float], rigs.Vec] = lambda side, t: (0.0, 0.0, 0.0)) -> None:
    """Keys hips and knees so each foot site sits at its rest place plus foot(side, t), while
    the root moves by root_move(t). Rigs without legs (or a root) are left alone."""
    rig = clip.rig
    root = rig.role("root")
    rest = rigs.forward(rig, {})
    for side in ("l", "r"):
        hip, knee, sole = rig.role(f"hip_{side}"), rig.role(f"knee_{side}"), rig.role(f"foot_{side}")
        if not (root and hip and knee and sole):
            continue
        solved: dict[float, tuple[float, float]] = {}

        def solve(t: float, s=side, hip=hip, knee=knee, sole=sole) -> tuple[float, float]:
            if t not in solved:
                hip_at = rigs.forward(rig, {}, {root: root_move(t)})[hip][0]
                target = rigs.add(rest[sole][0], foot(s, t))
                rel = (target[0] - hip_at[0], target[1] - hip_at[1], target[2] - hip_at[2])
                solved[t] = two_bone_x(rig.offset(knee), rig.offset(sole), rel)[:2]
            return solved[t]

        clip.rotate(f"hip_{side}", lambda t, f=solve: (f(t)[0], 0.0, 0.0))
        clip.rotate(f"knee_{side}", lambda t, f=solve: (f(t)[1], 0.0, 0.0))


def _angle(v: rigs.Vec) -> float:
    """Angle of a vector's (Y, Z) part, measured so a positive X rotation increases it."""
    return math.atan2(v[2], v[1])


def _wrap(a: float) -> float:
    return math.atan2(math.sin(a), math.cos(a))
