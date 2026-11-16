# SPDX-License-Identifier: MIT OR GPL-3.0-or-later
"""Shrubs and flower beds you can walk through (no collision).

Types cycle with the variant index: a rounded shrub cluster, a flowering shrub, and a
clipped hedge that is a little uneven, as hand-clipped hedges are.
"""
import kit
import style


def build(name, rng):
    make = TYPES[kit.variant_index(name) % len(TYPES)]
    return kit.join(make(rng), name), None


def shrub(rng):
    return [
        kit.blob(rng.uniform(0.45, 0.8), (rng.uniform(-0.5, 0.5), rng.uniform(-0.5, 0.5), rng.uniform(0.35, 0.6)), style.pick(rng, "leaf"), rng)
        for _ in range(rng.randint(3, 5))
    ]


def flowering(rng):
    parts = shrub(rng)
    flower = style.pick(rng, "flowers")
    for _ in range(rng.randint(10, 16)):
        loc = (rng.uniform(-0.8, 0.8), rng.uniform(-0.8, 0.8), rng.uniform(0.6, 1.1))
        parts.append(kit.box((0.12, 0.12, 0.12), loc, flower, rot=(rng.uniform(0, 1), rng.uniform(0, 1), 0)))
    return parts


def hedge(rng):
    count = rng.randint(3, 5)
    return [
        kit.blob(0.5, ((i - (count - 1) / 2) * 0.65, rng.uniform(-0.05, 0.05), 0.5), style.material("leaf", 2), rng, scale=(1.2, 0.9, 1.1), jitter=0.12)
        for i in range(count)
    ]


TYPES = [shrub, flowering, hedge]
