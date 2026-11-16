# SPDX-License-Identifier: MIT OR GPL-3.0-or-later
"""Rig profiles and forward kinematics.

A rig profile (JSON) describes a jointed body without any meshes:

    {
      "name": "biped",
      "joints": {
        "root":  {"parent": null,   "offset": [0, 0, 0]},
        "hip_l": {"parent": "root", "offset": [0.13, 0.48, 0], "limits": {"x": [-1.6, 1.2]}},
        ...
      },
      "sites": {"foot_l": {"parent": "knee_l", "offset": [0.0, -0.21, -0.07]}},
      "roles": {"hip_l": "hip_l", ...},
      "mirrored": ["arm_l/elbow"]
    }

- **offset:** the joint's rest position in its parent's frame, in metres.
- **limits:** optional per-axis rotation ranges in radians, checked by checks.py.
- **sites:** points that don't rotate (feet, hands), for IK targets and floor checks.
- **roles:** what a generic motion family calls a joint (hip_l, knee_l, elbow_r, body, head…)
  mapped to this rig's own joint names, so families never hard-code a game's names.
- **mirrored:** joints that sit inside a mirrored (scale x = -1) part in the game. Clips are
  authored in true space; the game negates Y and Z rotation for these when it bakes them.
"""
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

Vec = tuple[float, float, float]
Mat = tuple[Vec, Vec, Vec]  # rows

IDENTITY: Mat = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
AXES = "xyz"  # the order rotation components are stored in, whatever order they're applied in


@dataclass(frozen=True)
class Joint:
    name: str
    parent: str | None
    offset: Vec
    limits: dict[str, tuple[float, float]] = field(default_factory=dict)


@dataclass(frozen=True)
class Site:
    name: str
    parent: str
    offset: Vec


@dataclass
class Rig:
    name: str
    joints: dict[str, Joint]  # in parent-before-child order
    sites: dict[str, Site]
    roles: dict[str, str]
    mirrored: frozenset[str]

    def role(self, role: str) -> str | None:
        """This rig's joint (or site) for a generic role, or None if the rig doesn't have one."""
        name = self.roles.get(role)
        return name if name in self.joints or name in self.sites else None

    def offset(self, name: str) -> Vec:
        """A joint's or site's rest offset from its parent."""
        return self.joints[name].offset if name in self.joints else self.sites[name].offset


def load(path: str | Path) -> Rig:
    data = json.loads(Path(path).read_text())
    raw = data["joints"]
    ordered: dict[str, Joint] = {}
    while len(ordered) < len(raw):  # parents before children
        progressed = False
        for name, j in raw.items():
            if name in ordered or (j.get("parent") and j["parent"] not in ordered):
                continue
            limits = {axis: (float(lo), float(hi)) for axis, (lo, hi) in j.get("limits", {}).items()}
            ordered[name] = Joint(name, j.get("parent"), _vec(j["offset"]), limits)
            progressed = True
        if not progressed:
            missing = sorted(set(raw) - set(ordered))
            raise ValueError(f"{path}: joints with a missing parent or a cycle: {missing}")
    sites = {name: Site(name, s["parent"], _vec(s["offset"])) for name, s in data.get("sites", {}).items()}
    for site in sites.values():
        if site.parent not in ordered:
            raise ValueError(f"{path}: site {site.name} hangs off unknown joint {site.parent}")
    mirrored = frozenset(data.get("mirrored", []))
    unknown = sorted(mirrored - set(ordered))
    if unknown:
        raise ValueError(f"{path}: mirrored joints that don't exist: {unknown}")
    return Rig(data["name"], ordered, sites, dict(data.get("roles", {})), mirrored)


# ---- maths (3×3 rotation matrices as row tuples) ----

def euler(rot: Vec) -> Mat:
    """Rotation matrix for Euler angles applied in Godot's default YXZ order: R = Ry · Rx · Rz."""
    x, y, z = rot
    return mul(mul(_ry(y), _rx(x)), _rz(z))


def mul(a: Mat, b: Mat) -> Mat:
    return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3))  # type: ignore[return-value]


def apply(m: Mat, v: Vec) -> Vec:
    return tuple(sum(m[i][k] * v[k] for k in range(3)) for i in range(3))  # type: ignore[return-value]


def add(a: Vec, b: Vec) -> Vec:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def angle_between(a: Mat, b: Mat) -> float:
    """The angle of the rotation that takes a to b, in radians."""
    rel = mul(_transpose(a), b)
    trace = rel[0][0] + rel[1][1] + rel[2][2]
    return math.acos(max(-1.0, min(1.0, (trace - 1.0) / 2.0)))


def forward(rig: Rig, pose: dict[str, Vec], moves: dict[str, Vec] | None = None) -> dict[str, tuple[Vec, Mat]]:
    """World position and orientation of every joint and site for a pose.

    pose maps joint → Euler rotation; moves maps joint → a translation added to its rest offset
    (a root bob, say). Missing joints are at rest.
    """
    moves = moves or {}
    out: dict[str, tuple[Vec, Mat]] = {}
    for name, joint in rig.joints.items():
        local = add(joint.offset, moves.get(name, (0.0, 0.0, 0.0)))
        if joint.parent is None:
            pos, basis = local, IDENTITY
        else:
            ppos, pbasis = out[joint.parent]
            pos, basis = add(ppos, apply(pbasis, local)), pbasis
        out[name] = (pos, mul(basis, euler(pose.get(name, (0.0, 0.0, 0.0)))))
    for name, site in rig.sites.items():
        ppos, pbasis = out[site.parent]
        out[name] = (add(ppos, apply(pbasis, site.offset)), pbasis)
    return out


def _vec(v: list) -> Vec:
    if len(v) != 3:
        raise ValueError(f"expected 3 numbers, got {v}")
    return (float(v[0]), float(v[1]), float(v[2]))


def _transpose(m: Mat) -> Mat:
    return tuple(tuple(m[j][i] for j in range(3)) for i in range(3))  # type: ignore[return-value]


def _rx(a: float) -> Mat:
    c, s = math.cos(a), math.sin(a)
    return ((1.0, 0.0, 0.0), (0.0, c, -s), (0.0, s, c))


def _ry(a: float) -> Mat:
    c, s = math.cos(a), math.sin(a)
    return ((c, 0.0, s), (0.0, 1.0, 0.0), (-s, 0.0, c))


def _rz(a: float) -> Mat:
    c, s = math.cos(a), math.sin(a)
    return ((c, -s, 0.0), (s, c, 0.0), (0.0, 0.0, 1.0))
