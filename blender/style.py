# SPDX-License-Identifier: MIT OR GPL-3.0-or-later
"""Blender materials from the active palette. Families paint with these and never pick colours.

The runner calls use() with a loaded palette before building. The API is material, pick and
MENDED, so a family written against it ports between projects unchanged.
"""
import random

import bpy

import palette as palette_file

_active: palette_file.Palette | None = None

# Chance of each optional mended/upcycled detail (patch panels, bolted repairs), from the
# palette's "mended". 0 = pristine, 1 = everything patched.
MENDED = 0.0


def use(palette: palette_file.Palette) -> None:
    global _active, MENDED
    _active = palette
    MENDED = palette.mended


def material(key: str, index: int = 0) -> bpy.types.Material:
    """The shared material for slot key[index], created on first use."""
    assert _active is not None, "style.use(palette) must run before building"
    name = f"{key}_{index}"  # the slot name travels with the .glb, so engines can re-skin by it
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
        bsdf = mat.node_tree.nodes["Principled BSDF"]
        bsdf.inputs["Base Color"].default_value = (*palette_file.to_linear(_active.colour(key, index)), 1.0)
        bsdf.inputs["Roughness"].default_value = _active.roughness.get(key, palette_file.DEFAULT_ROUGHNESS)
        bsdf.inputs["Metallic"].default_value = _active.metallic.get(key, 0.0)
    return mat


def pick(rng: random.Random, key: str) -> bpy.types.Material:
    """A random material from one palette slot."""
    assert _active is not None, "style.use(palette) must run before building"
    return material(key, rng.randrange(len(_active.colours[key])))
