# SPDX-License-Identifier: MIT OR GPL-3.0-or-later
"""Clips: joint rotations (and a few translations) sampled at a fixed frame rate, plus events.

A clip on disk (JSON):

    {"name": "walk", "rig": "biped", "length": 0.6, "loop": true, "fps": 30, "speed": 1.1,
     "tracks": {"hip_l": {"rotation": [[x, y, z], ...]}, "root": {"position": [[x, y, z], ...]}},
     "mirrored": ["arm_l/elbow"],
     "events": [{"time": 0.0, "name": "footfall_l"}]}

- Every track has length * fps + 1 samples, first frame at 0 and last at the clip's end.
- **position** is the joint's absolute local position (its rest offset plus any movement).
- **speed** is the ground speed in metres per second the clip was made for (0 when in place),
  so a game can scale playback to how fast the character is really moving.
- **mirrored** is copied from the rig: the game negates Y and Z rotation on these joints.
- **contacts** say when a site is planted on the ground (`{"site", "start", "end"}`, in
  seconds; on a looping clip end may pass the clip's length and wrap round). The slide check
  uses them, and a game can use them for footstep sounds or foot locking.
"""
import math
from collections.abc import Callable

from . import rig as rigs

FPS = 30
DECIMALS = 5  # rounding for stable, diffable JSON (0.01 mm, 0.0006°)

Fn = Callable[[float], rigs.Vec]


class Clip:
    def __init__(self, name: str, rig: rigs.Rig, length: float, loop: bool, speed: float = 0.0, fps: int = FPS) -> None:
        self.name, self.rig, self.length, self.loop, self.speed, self.fps = name, rig, length, loop, speed, fps
        self.rotations: dict[str, list[rigs.Vec]] = {}
        self.positions: dict[str, list[rigs.Vec]] = {}
        self.events: list[tuple[float, str]] = []
        self.contacts: list[tuple[str, float, float]] = []

    def times(self) -> list[float]:
        frames = max(1, round(self.length * self.fps))
        return [self.length * i / frames for i in range(frames + 1)]

    def rotate(self, role: str, fn: Fn) -> None:
        """Keys a joint's rotation from fn(t). Skips quietly if this rig has no such role."""
        joint = self.rig.role(role)
        if joint in self.rig.joints:
            self.rotations[joint] = [fn(t) for t in self.times()]

    def move(self, role: str, fn: Fn) -> None:
        """Keys a joint's translation away from its rest offset, from fn(t)."""
        joint = self.rig.role(role)
        if joint in self.rig.joints:
            rest = self.rig.joints[joint].offset
            self.positions[joint] = [rigs.add(rest, fn(t)) for t in self.times()]

    def event(self, time: float, name: str) -> None:
        self.events.append((time, name))

    def contact(self, role: str, start: float, end: float) -> None:
        """Marks a site (by role) as planted from start to end seconds."""
        site = self.rig.role(role)
        if site in self.rig.sites:
            self.contacts.append((site, start, end))

    def pose(self, frame: int) -> tuple[dict[str, rigs.Vec], dict[str, rigs.Vec]]:
        """(rotations, movements from rest) at one frame, ready for rig.forward."""
        rotations = {j: keys[frame] for j, keys in self.rotations.items()}
        moves = {j: tuple(p - r for p, r in zip(keys[frame], self.rig.joints[j].offset)) for j, keys in self.positions.items()}
        return rotations, moves  # type: ignore[return-value]

    def to_dict(self) -> dict:
        tracks: dict[str, dict] = {}
        for joint in self.rig.joints:  # rig order, so files diff cleanly
            track = {}
            if joint in self.rotations:
                track["rotation"] = [_round(v) for v in self.rotations[joint]]
            if joint in self.positions:
                track["position"] = [_round(v) for v in self.positions[joint]]
            if track:
                tracks[joint] = track
        return {
            "name": self.name, "rig": self.rig.name, "length": round(self.length, DECIMALS), "loop": self.loop,
            "fps": self.fps, "speed": round(self.speed, DECIMALS), "tracks": tracks,
            "mirrored": sorted(self.rig.mirrored & set(tracks)),
            "events": [{"time": round(t, DECIMALS), "name": n} for t, n in sorted(self.events)],
            "contacts": [{"site": s, "start": round(a, DECIMALS), "end": round(b, DECIMALS)} for s, a, b in sorted(self.contacts)],
        }


def from_dict(data: dict, rig: rigs.Rig) -> Clip:
    """A clip read back from JSON, for checks and filmstrips."""
    clip = Clip(data["name"], rig, data["length"], data["loop"], data.get("speed", 0.0), data["fps"])
    for joint, track in data["tracks"].items():
        if "rotation" in track:
            clip.rotations[joint] = [tuple(v) for v in track["rotation"]]
        if "position" in track:
            clip.positions[joint] = [tuple(v) for v in track["position"]]
    clip.events = [(e["time"], e["name"]) for e in data["events"]]
    clip.contacts = [(c["site"], c["start"], c["end"]) for c in data.get("contacts", [])]
    return clip


# ---- shaping helpers for families ----

def smooth(x: float) -> float:
    """Smoothstep on 0..1: eases in and out, flat at both ends."""
    x = max(0.0, min(1.0, x))
    return x * x * (3.0 - 2.0 * x)


def envelope(t: float, attack: float, hold: float, release: float) -> float:
    """0 → 1 over attack seconds, stays 1 for hold, back to 0 over release; 0 outside."""
    if t < attack:
        return smooth(t / attack) if attack > 0 else 1.0
    if t < attack + hold:
        return 1.0
    return 1.0 - smooth((t - attack - hold) / release) if release > 0 else 0.0


def wave(t: float, period: float, phase: float = 0.0) -> float:
    """sin over one period, starting at phase (0..1 of a cycle). Loops cleanly at whole periods."""
    return math.sin(2.0 * math.pi * (t / period + phase))


def _round(v: rigs.Vec) -> list[float]:
    return [round(c, DECIMALS) + 0.0 for c in v]  # + 0.0 turns -0.0 into 0.0
