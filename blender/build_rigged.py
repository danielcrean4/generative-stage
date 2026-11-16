# SPDX-License-Identifier: MIT OR GPL-3.0-or-later
"""Builds one rigged model with its animation clips into a single .glb.

    python3 build_motions.py --motions motions --manifest examples/motion_manifest.json --out /tmp/clips
    blender --background --factory-startup --python build_rigged.py -- \\
        --rig examples/rigs/biped.json --clips /tmp/clips/biped --clip idle --clip walk --clip run \\
        --out examples/rigged

The body is plain boxes and tapered limbs, one per joint, each tied to its joint with full weight,
so no skinning is guessed. Clips are the JSON files build_motions.py wrote; their joint rotations
(Godot's YXZ Euler order, glTF axes) are converted to Blender's axes and keyed on an armature whose
bones start with the same axes as the rig profile. Outputs:
    <out>/<rig>.glb     mesh, skeleton and one animation per clip
    <out>/build.json    what made it (Blender version, clips, how)
"""
import argparse
import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))

import kit  # noqa: E402  (needs the path above)
from motion import rig as rigs  # noqa: E402
from rigging import blender, build_armature, export_rigged, key_clip, world_positions  # noqa: E402

LIMB = {"upper": 0.055, "lower": 0.045}  # limb radius at the top and bottom of a segment, in metres
COLOURS = {"l": (0.25, 0.5, 0.9), "r": (0.95, 0.55, 0.2), "": (0.8, 0.78, 0.72), "head": (0.93, 0.82, 0.7)}


def material(key: str) -> bpy.types.Material:
    mat = bpy.data.materials.get(f"rigged_{key or 'body'}")
    if mat is None:
        mat = bpy.data.materials.new(f"rigged_{key or 'body'}")
        mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (*COLOURS[key], 1.0)
        mat.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.7
    return mat


def side_of(name: str) -> str:
    return name[-1] if name[-2:] in ("_l", "_r") else ""


def body_parts(rig: rigs.Rig, world: dict) -> list[tuple[str, bpy.types.Object]]:
    """(joint, object) pairs: a limb from each joint to its first child, a head and a pelvis."""
    parts = []
    children: dict[str, list[str]] = {}
    for name in [*rig.joints, *rig.sites]:
        parent = rig.joints[name].parent if name in rig.joints else rig.sites[name].parent
        if parent:
            children.setdefault(parent, []).append(name)
    for name in rig.joints:
        side = side_of(name)
        if name == "root":
            top = Vector(blender(world["root"])) + Vector((0, 0, 0.5))
            parts.append((name, kit.box((0.34, 0.2, 0.14), top, material(""))))
        elif name == "head":
            centre = blender(rigs.add(world[name], (0, 0.13, 0)))
            parts.append((name, kit.box((0.22, 0.22, 0.24), centre, material("head"))))
        elif children.get(name):
            end = children[name][0]
            radius = 0.09 if name == "body" else LIMB["upper"]
            parts.append((name, kit.strut(blender(world[name]), blender(world[end]), radius, LIMB["lower"] if name != "body" else 0.12, material(side))))
    return parts


def skin(parts, arm: bpy.types.Object, name: str) -> bpy.types.Object:
    for joint, obj in parts:
        group = obj.vertex_groups.new(name=joint)
        group.add([v.index for v in obj.data.vertices], 1.0, "REPLACE")
    mesh = kit.join([obj for _, obj in parts], name)
    mesh.parent = arm
    modifier = mesh.modifiers.new("Armature", "ARMATURE")
    modifier.object = arm
    return mesh


def main() -> None:
    parser = argparse.ArgumentParser(prog="build_rigged.py")
    parser.add_argument("--rig", required=True)
    parser.add_argument("--clips", required=True, help="folder of <clip>.json from build_motions.py")
    parser.add_argument("--clip", action="append", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])

    rig = rigs.load(args.rig)
    world = world_positions(rig)
    kit.reset()
    arm = build_armature(rig, world)
    mesh = skin(body_parts(rig, world), arm, rig.name)
    for clip_name in args.clip:
        clip = json.loads((Path(args.clips) / f"{clip_name}.json").read_text())
        clip["length_frames"] = round(clip["length"] * clip["fps"])
        key_clip(arm, rig, clip)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    export_rigged((arm, mesh), str(out / f"{rig.name}.glb"), animations=True)
    (out / "build.json").write_text(json.dumps({
        "model": f"{rig.name}.glb",
        "blender": bpy.app.version_string,
        "rig": Path(args.rig).name,
        "clips": args.clip,
        "how": "Body built from boxes and tapered limbs by build_rigged.py, one piece per joint at full weight. "
               "Clips made by build_motions.py from the procedural motion families, keyed on the armature. No model or download involved.",
    }, indent=1) + "\n")
    print(f"BUILT {rig.name}.glb with {len(args.clip)} clips")


main()
