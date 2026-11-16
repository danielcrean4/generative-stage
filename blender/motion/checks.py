# SPDX-License-Identifier: MIT OR GPL-3.0-or-later
"""Automatic checks every generated clip must pass before anyone looks at it.

- **limits:** every rotation stays inside its joint's limits.
- **loop:** a looping clip ends where it starts, so it plays without a pop.
- **events:** the events the manifest asks for are there.
- **floor:** no site (a foot, a hand) goes below the ground.
- **slide:** a planted site stays put on the ground while the body moves at the clip's speed.
"""
import math

from . import curves
from . import rig as rigs

LOOP_TOLERANCE = 0.02  # radians (about 1°) between a looping clip's first and last pose
FLOOR_TOLERANCE = 0.005  # metres a site may dip below the ground
SLIDE_LIMIT = 0.01  # metres a planted site may drift during one contact


def check(clip: curves.Clip, required_events: list[str] = ()) -> list[str]:
    """Every problem found, as readable lines; an empty list means the clip passes."""
    rig = clip.rig
    problems = _limits(clip, rig) + _events(clip, required_events)
    if clip.loop:
        problems += _loop(clip)
    poses = [rigs.forward(rig, *clip.pose(i)) for i in range(len(clip.times()))]
    problems += _floor(clip, poses) + _slide(clip, poses)
    return problems


def _limits(clip: curves.Clip, rig: rigs.Rig) -> list[str]:
    out = []
    for joint, keys in clip.rotations.items():
        for axis, (lo, hi) in rig.joints[joint].limits.items():
            i = rigs.AXES.index(axis)
            worst = max(keys, key=lambda v: max(lo - v[i], v[i] - hi))[i]
            if not lo - 1e-6 <= worst <= hi + 1e-6:
                out.append(f"limits: {joint} {axis} reaches {worst:.3f}, outside [{lo:.3f}, {hi:.3f}]")
    return out


def _events(clip: curves.Clip, required: list[str]) -> list[str]:
    have = {name for _, name in clip.events}
    return [f"events: no '{name}' event" for name in required if name not in have]


def _loop(clip: curves.Clip) -> list[str]:
    out = []
    for joint, keys in clip.rotations.items():
        gap = rigs.angle_between(rigs.euler(keys[0]), rigs.euler(keys[-1]))
        if gap > LOOP_TOLERANCE:
            out.append(f"loop: {joint} ends {gap:.3f} rad from where it starts")
    for joint, keys in clip.positions.items():
        gap = max(abs(a - b) for a, b in zip(keys[0], keys[-1]))
        if gap > FLOOR_TOLERANCE:
            out.append(f"loop: {joint} ends {gap:.4f} m from where it starts")
    return out


def _floor(clip: curves.Clip, poses: list[dict]) -> list[str]:
    out = []
    for site in clip.rig.sites:
        lowest = min(range(len(poses)), key=lambda i: poses[i][site][0][1])
        y = poses[lowest][site][0][1]
        if y < -FLOOR_TOLERANCE:
            out.append(f"floor: {site} goes {-y:.3f} m below the ground at {clip.times()[lowest]:.2f} s")
    return out


def _slide(clip: curves.Clip, poses: list[dict]) -> list[str]:
    out = []
    frames = len(poses) - 1
    step = clip.length / frames
    for site, start, end in clip.contacts:
        planted = None
        drift = 0.0
        for k in range(math.ceil(start / step - 1e-9), math.floor(end / step + 1e-9) + 1):
            frame = k % frames if clip.loop else min(k, frames)
            pos = poses[frame][site][0]
            where = (pos[0], pos[1], pos[2] + clip.speed * k * step)  # the body moves +Z at clip.speed
            planted = planted or where
            drift = max(drift, max(abs(a - b) for a, b in zip(where, planted)))
        if drift > SLIDE_LIMIT:
            out.append(f"slide: {site} drifts {drift * 100:.1f} cm while planted ({start:.2f}–{end:.2f} s)")
    return out
