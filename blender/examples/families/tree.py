# SPDX-License-Identifier: MIT OR GPL-3.0-or-later
"""Tree family: five species, each with leaning, tapering trunks and lumpy canopies so no
two look stamped. Species cycle with the variant index so every one appears.

- broadleaf: a branching trunk under clustered round canopy blobs
- birch: tall, slender and white, with a light, sparse crown
- conifer: stacked, slightly crooked cones
- maple: a short multi-stem Japanese maple with flat red and orange layers
- pine: a niwaki-style garden pine, with horizontal branches ending in flat pads
"""
import math

import kit
import style


def build(name, rng):
    species = SPECIES[kit.variant_index(name) % len(SPECIES)]
    parts, trunk_h = species(rng)
    collision = kit.collision_box((0.5, 0.5, trunk_h), (0, 0, trunk_h / 2), name)
    return kit.join(parts, name), collision


def _trunk(rng, height, radius, mat, lean=0.08):
    tilt = (rng.uniform(-lean, lean), rng.uniform(-lean, lean), 0.0)
    trunk = kit.cone(radius, radius * 0.6, height, (0, 0, height / 2), mat, rot=tilt)
    tip = (math.sin(tilt[1]) * height, -math.sin(tilt[0]) * height, height)
    return trunk, tip


def _branch(rng, origin, length, radius, mat, elevation):
    """A limb leaving origin at a random heading; returns the limb and its tip."""
    heading = rng.uniform(0, math.tau)
    direction = (math.cos(heading) * math.cos(elevation), math.sin(heading) * math.cos(elevation), math.sin(elevation))
    tip = tuple(o + d * length for o, d in zip(origin, direction))
    return kit.strut(origin, tip, radius, radius * 0.5, mat, segments=6), tip


def broadleaf(rng):
    bark = style.pick(rng, "bark")
    trunk_h = rng.uniform(2.8, 3.8)
    trunk, top = _trunk(rng, trunk_h, rng.uniform(0.2, 0.28), bark)
    parts = [trunk]
    tips = [top]
    for _ in range(rng.randint(2, 4)):
        limb, tip = _branch(rng, (top[0], top[1], top[2] - 0.6), rng.uniform(1.2, 2.0), 0.12, bark, rng.uniform(0.6, 1.0))
        parts.append(limb)
        tips.append(tip)
    for tip in tips:
        for _ in range(2):
            offset = (rng.uniform(-0.6, 0.6), rng.uniform(-0.6, 0.6), rng.uniform(0.2, 0.9))
            loc = tuple(t + o for t, o in zip(tip, offset))
            parts.append(kit.blob(rng.uniform(0.9, 1.4), loc, style.pick(rng, "leaf"), rng))
    return parts, trunk_h


def birch(rng):
    trunk_h = rng.uniform(5.0, 6.5)
    trunk, top = _trunk(rng, trunk_h, rng.uniform(0.12, 0.16), style.material("birch"), lean=0.12)
    parts = [trunk]
    for i in range(rng.randint(4, 6)):
        z = trunk_h * rng.uniform(0.45, 1.0)
        frac = z / trunk_h
        loc = (top[0] * frac + rng.uniform(-0.7, 0.7), top[1] * frac + rng.uniform(-0.7, 0.7), z + 0.4)
        parts.append(kit.blob(rng.uniform(0.6, 0.9), loc, style.material("leaf", 3), rng, scale=(1, 1, 1.4)))
    return parts, trunk_h


def conifer(rng):
    trunk_h = rng.uniform(1.2, 1.8)
    height = rng.uniform(6.0, 8.5)
    trunk, _ = _trunk(rng, trunk_h + 1.0, 0.2, style.material("bark"), lean=0.03)
    parts = [trunk]
    tiers = rng.randint(4, 5)
    tier_h = (height - trunk_h) / tiers * 1.6
    for i in range(tiers):
        frac = i / tiers
        z = trunk_h + frac * (height - trunk_h - tier_h / 2) + tier_h / 2
        radius = (1.0 - frac * 0.75) * rng.uniform(1.7, 2.1)
        loc = (rng.uniform(-0.12, 0.12), rng.uniform(-0.12, 0.12), z)
        tilt = (rng.uniform(-0.06, 0.06), rng.uniform(-0.06, 0.06), rng.uniform(0, math.tau))
        parts.append(kit.cone(radius, 0.05, tier_h, loc, style.pick(rng, "conifer"), rot=tilt, segments=9))
    return parts, trunk_h


def maple(rng):
    bark = style.material("bark", 1)
    parts = []
    tips = []
    for _ in range(rng.randint(2, 3)):
        limb, tip = _branch(rng, (0, 0, 0.1), rng.uniform(2.0, 2.8), 0.12, bark, rng.uniform(1.0, 1.3))
        parts.append(limb)
        tips.append(tip)
    for tip in tips:
        for _ in range(2):
            loc = (tip[0] + rng.uniform(-0.8, 0.8), tip[1] + rng.uniform(-0.8, 0.8), tip[2] + rng.uniform(0.0, 0.5))
            parts.append(kit.blob(rng.uniform(1.0, 1.4), loc, style.pick(rng, "maple"), rng, scale=(1.2, 1.2, 0.6)))
    return parts, 2.0


def pine(rng):
    bark = style.material("bark")
    trunk_h = rng.uniform(2.5, 3.5)
    trunk, top = _trunk(rng, trunk_h, 0.2, bark, lean=0.18)
    parts = [trunk, kit.blob(0.9, (top[0], top[1], top[2] + 0.3), style.material("conifer"), rng, scale=(1.3, 1.3, 0.45))]
    for i in range(rng.randint(3, 4)):
        z = trunk_h * (0.45 + 0.15 * i)
        frac = z / trunk_h
        origin = (top[0] * frac, top[1] * frac, z)
        limb, tip = _branch(rng, origin, rng.uniform(1.0, 1.7), 0.08, bark, rng.uniform(0.0, 0.35))
        parts.append(limb)
        parts.append(kit.blob(rng.uniform(0.7, 1.0), (tip[0], tip[1], tip[2] + 0.15), style.pick(rng, "conifer"), rng, scale=(1.4, 1.4, 0.4)))
    return parts, trunk_h


SPECIES = [broadleaf, birch, conifer, maple, pine]
