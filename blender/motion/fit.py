# SPDX-License-Identifier: MIT OR GPL-3.0-or-later
"""Fit a rig profile to a mesh and weight the mesh to it, classically: no model, plain Python (no Blender).

Used by rig_standin.py, which supplies the mesh's points and, for the inside test, Blender's BVH.

- `fit(rig, points)` places the profile's joints and sites on a mesh by its bounds: height sets the vertical scale,
  the mesh's half-width the lateral scale (held within LATERAL_RANGE of the vertical one), the feet on its lowest
  point, centred on its bounding box. Returns the world positions in glTF axes.
- `pull_inside(world, rig, inside, nearest)` moves each deforming joint that falls outside the mesh to just inside
  its nearest surface, so bones sit in the body.
- `profile(rig, world, ground)` is the fitted profile as JSON (rig.py's format): offsets from the fitted positions,
  the original limits, roles and mirrored joints. Its ground is y = 0 (the mesh's lowest point), as the motion checks
  expect, so its root sits GROUND below where the armature's root does.
- `segments(rig, world)` is one bone segment per deforming joint (to its first child, or a head-sized stub);
  `weights(points, segs)` gives each point its nearest segments' weights, at most MAX_INFLUENCES, normalised.

A profile's `root` (a joint with no parent) carries no weight: it sits on the floor between the feet and only moves
the whole body.
"""
from . import rig as rigs

HEAD_TOP = 0.25          # metres above the head joint the profile's head reaches (build_rigged.py's head box)
LIMB_RADIUS = 0.055      # the profile's limb radius, added to its half-width
LATERAL_RANGE = (0.5, 2.0)  # the lateral scale stays within these multiples of the vertical one
INSIDE_DEPTH = 0.02      # how far inside the surface a pulled joint goes, as a share of the mesh height
MAX_INFLUENCES = 4
FALLOFF = 8.0            # weight ~ (nearest distance / distance) ** FALLOFF: near-rigid, blended at the joints
MIN_WEIGHT = 0.01        # a weight below this is dropped before normalising
EPSILON = 1e-9

Vec = tuple[float, float, float]


def bounds(points: list[Vec]) -> tuple[Vec, Vec]:
    lo = tuple(min(p[i] for p in points) for i in range(3))
    hi = tuple(max(p[i] for p in points) for i in range(3))
    return lo, hi  # type: ignore[return-value]


def rest_world(rig: rigs.Rig) -> dict[str, Vec]:
    world: dict[str, Vec] = {}
    for name in [*rig.joints, *rig.sites]:
        parent = rig.joints[name].parent if name in rig.joints else rig.sites[name].parent
        world[name] = rigs.add(world[parent], rig.offset(name)) if parent else rig.offset(name)
    return world


def deforming(rig: rigs.Rig) -> list[str]:
    """The joints that carry weight: all but the root(s)."""
    return [name for name, joint in rig.joints.items() if joint.parent is not None]


def fit(rig: rigs.Rig, points: list[Vec]) -> tuple[dict[str, Vec], dict[str, float]]:
    """(fitted world positions of every joint and site, the scales, height and ground used)."""
    if not points:
        raise ValueError("the mesh has no vertices")
    rest = rest_world(rig)
    floor = min(p[1] for p in rest.values())
    top = max(rest[name][1] + (HEAD_TOP if name == rig.role("head") else 0.0) for name in rig.joints)
    half_width = max(abs(p[0]) for p in rest.values()) + LIMB_RADIUS
    (lo, hi) = bounds(points)
    height = hi[1] - lo[1]
    if height <= EPSILON or top - floor <= EPSILON:
        raise ValueError("the mesh has no height to fit a body to")
    vertical = height / (top - floor)
    centre = ((lo[0] + hi[0]) / 2, (lo[2] + hi[2]) / 2)
    mesh_half_width = max(hi[0] - centre[0], centre[0] - lo[0])
    lateral = min(max(mesh_half_width / half_width, LATERAL_RANGE[0] * vertical), LATERAL_RANGE[1] * vertical)
    world = {name: (centre[0] + p[0] * lateral, lo[1] + (p[1] - floor) * vertical, centre[1] + p[2] * vertical)
             for name, p in rest.items()}
    return world, {"vertical": vertical, "lateral": lateral, "height": height, "ground": lo[1]}


def pull_inside(world: dict[str, Vec], rig: rigs.Rig, height: float, inside, nearest) -> list[str]:
    """Moves each deforming joint of WORLD that is not INSIDE(point) the mesh to just inside it. NEAREST(point)
    returns (surface point, outward normal). Returns the joints moved. Children keep their own fitted positions."""
    moved = []
    for name in deforming(rig):
        point = world[name]
        if inside(point):
            continue
        surface, normal = nearest(point)
        for share in (INSIDE_DEPTH, INSIDE_DEPTH / 4, INSIDE_DEPTH * 4):
            candidate = tuple(s - n * share * height for s, n in zip(surface, normal, strict=True))
            if inside(candidate):
                world[name] = candidate  # type: ignore[assignment]
                moved.append(name)
                break
    return moved


def profile(rig: rigs.Rig, world: dict[str, Vec], ground: float) -> dict:
    """The fitted rig profile as JSON, in rig.py's format, with the ground (world y = GROUND) at y = 0."""
    def offset(name: str, parent: str | None) -> list[float]:
        here = world[name]
        base = world[parent] if parent else (0.0, ground, 0.0)
        return [round(a - b, 6) + 0.0 for a, b in zip(here, base, strict=True)]

    joints = {}
    for name, joint in rig.joints.items():
        entry: dict = {"parent": joint.parent, "offset": offset(name, joint.parent)}
        if joint.limits:
            entry["limits"] = {axis: list(limit) for axis, limit in joint.limits.items()}
        joints[name] = entry
    sites = {name: {"parent": site.parent, "offset": offset(name, site.parent)} for name, site in rig.sites.items()}
    return {"name": rig.name, "joints": joints, "sites": sites, "roles": dict(rig.roles),
            "mirrored": sorted(rig.mirrored)}


def segments(rig: rigs.Rig, world: dict[str, Vec], vertical: float) -> dict[str, tuple[Vec, Vec]]:
    """{joint: (start, end)} for every deforming joint: to its first child joint or site, else a stub."""
    children: dict[str, list[str]] = {}
    for name in [*rig.joints, *rig.sites]:
        parent = rig.joints[name].parent if name in rig.joints else rig.sites[name].parent
        if parent:
            children.setdefault(parent, []).append(name)
    out = {}
    for name in deforming(rig):
        start = world[name]
        if children.get(name):
            end = world[children[name][0]]
        else:
            end = rigs.add(start, (0.0, HEAD_TOP * vertical, 0.0))
        out[name] = (start, end)
    return out


def _distance(point: Vec, segment: tuple[Vec, Vec]) -> float:
    (a, b) = segment
    ab = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    ap = (point[0] - a[0], point[1] - a[1], point[2] - a[2])
    length = ab[0] ** 2 + ab[1] ** 2 + ab[2] ** 2
    t = 0.0 if length <= EPSILON else max(0.0, min(1.0, (ap[0] * ab[0] + ap[1] * ab[1] + ap[2] * ab[2]) / length))
    d = (ap[0] - ab[0] * t, ap[1] - ab[1] * t, ap[2] - ab[2] * t)
    return (d[0] ** 2 + d[1] ** 2 + d[2] ** 2) ** 0.5


def weights(points: list[Vec], segs: dict[str, tuple[Vec, Vec]]) -> list[dict[str, float]]:
    """Per point, {joint: weight} over at most MAX_INFLUENCES joints, summing to 1. Every point gets a weight."""
    names = list(segs)
    out = []
    for point in points:
        distances = sorted((_distance(point, segs[name]), name) for name in names)[:MAX_INFLUENCES]
        nearest = distances[0][0]
        raw = {name: ((nearest + EPSILON) / (d + EPSILON)) ** FALLOFF for d, name in distances}
        total = sum(raw.values())
        kept = {name: w / total for name, w in raw.items() if w / total >= MIN_WEIGHT}
        total = sum(kept.values())
        out.append({name: w / total for name, w in kept.items()})
    return out
