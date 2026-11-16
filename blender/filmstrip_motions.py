# SPDX-License-Identifier: MIT OR GPL-3.0-or-later
"""Filmstrips: one picture per rig with a row per clip and eight poses along each row, drawn
as stick figures from the rig profile, for review by eye.

    blender --background --factory-startup --python blender/filmstrip_motions.py -- \\
        --clips <dir> --manifest <file.json> --out <dir>

Reads the clips build_motions.py wrote (<clips>/<rig>/<clip>.json) and writes <out>/<rig>.png.
The figure's left side is blue and its right orange, so mirrored mistakes stand out.
"""
import argparse
import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))

import kit  # noqa: E402  (needs the path above)
import preview  # noqa: E402
from motion import curves, rig as rigs  # noqa: E402

POSES = 8  # samples along each clip, first frame to last
THICKNESS = 0.022  # strut radius, in metres
SPACING = 1.1  # metres between poses and between rows
LABEL_SIZE = 0.22
VIEW = (-1.0, -0.25, 0.12)  # from the figure's left, a little in front and above: time runs left to right
COLOURS = {"l": (0.2, 0.45, 0.95, 1.0), "r": (0.95, 0.5, 0.15, 1.0), "": (0.85, 0.85, 0.82, 1.0)}


def material(side: str) -> bpy.types.Material:
    name = f"filmstrip_{side or 'centre'}"
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
        mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = COLOURS[side]
    return mat


def side_of(name: str) -> str:
    return name[-1] if name[-2:] in ("_l", "_r") else ""


def blender(v: rigs.Vec) -> tuple[float, float, float]:
    """glTF/Godot (Y up, +Z forward) to Blender (Z up, -Y forward)."""
    return (v[0], -v[2], v[1])


def figure(rig: rigs.Rig, world: dict, name: str) -> bpy.types.Object:
    struts = []
    roots = {j.name for j in rig.joints.values() if j.parent is None}  # a reference point on the ground, not a limb
    links = [(j.parent, j.name) for j in rig.joints.values() if j.parent and j.parent not in roots]
    links += [(s.parent, s.name) for s in rig.sites.values() if s.parent not in roots]
    for parent, child in links:
        a, b = world[parent][0], world[child][0]
        if max(abs(x - y) for x, y in zip(a, b)) > 1e-4:
            struts.append(kit.strut(blender(a), blender(b), THICKNESS, THICKNESS * 0.8, material(side_of(child)), segments=6))
    return kit.join(struts, name)


def filmstrip(rig: rigs.Rig, clips: list[curves.Clip], path: Path) -> None:
    """Lays the poses out on a wall (columns along Blender -Y, rows down Z) and renders it
    almost side-on, so legs and arms read clearly."""
    scene = bpy.context.scene
    for obj in list(scene.objects):
        bpy.data.objects.remove(obj)
    for row, clip in enumerate(clips):
        frames = len(clip.times()) - 1
        z = -row * SPACING
        for col in range(POSES):
            frame = round(col * frames / (POSES - 1))
            fig = figure(rig, rigs.forward(rig, *clip.pose(frame)), f"{clip.name}_{col}")
            fig.location = (0.0, -col * SPACING, z)
            kit.box((0.6, 0.6, 0.01), (0.0, -col * SPACING, z - 0.005), material(""))  # the floor
        label = bpy.data.objects.new(f"label_{clip.name}", bpy.data.curves.new(clip.name, type="FONT"))
        label.data.body = clip.name
        label.data.size = LABEL_SIZE
        label.location = (0.0, SPACING * 1.6, z + 0.25)
        label.rotation_euler = (1.5708, 0.0, -1.5708)  # stand the text up, facing the camera
        label.data.materials.append(material(""))
        scene.collection.objects.link(label)

    world = bpy.data.worlds.new("filmstrip_sky")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = preview.SKY
    scene.world = world
    sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", type="SUN"))
    sun.data.energy = preview.SUN_ENERGY
    sun.rotation_euler = (0.9, 0.3, 1.2)
    scene.collection.objects.link(sun)

    width = (POSES + 1) * SPACING
    height = len(clips) * SPACING
    centre = Vector((0.0, -(POSES - 2) * SPACING / 2, -(len(clips) - 1) * SPACING / 2 + 0.4))
    cam = bpy.data.objects.new("camera", bpy.data.cameras.new("camera"))
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = max(width, height * 16 / 9) * 1.05
    view = Vector(VIEW).normalized()
    cam.location = centre + view * 20.0
    cam.rotation_euler = (-view).to_track_quat("-Z", "Y").to_euler()
    cam.data.clip_end = 60.0
    scene.collection.objects.link(cam)
    scene.camera = cam
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x, scene.render.resolution_y = preview.SIZE
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


def main() -> None:
    parser = argparse.ArgumentParser(prog="blender/filmstrip_motions.py")
    parser.add_argument("--clips", required=True, type=Path, help="folder build_motions.py wrote")
    parser.add_argument("--manifest", required=True, type=Path, help="the manifest it was built from")
    parser.add_argument("--out", required=True, type=Path, help="folder for the pictures")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    manifest = json.loads(args.manifest.read_text())
    args.out.mkdir(parents=True, exist_ok=True)
    for name, rel in manifest["rigs"].items():
        rig = rigs.load(args.manifest.parent / rel)
        order = [c for entry in manifest["clips"] if entry["rig"] == name for c in entry["clips"]]
        files = [args.clips / name / f"{c}.json" for c in order]
        clips = [curves.from_dict(json.loads(f.read_text()), rig) for f in files if f.exists()]
        if clips:
            filmstrip(rig, clips, args.out / f"{name}.png")
            print(f"FILMSTRIP {name}: {', '.join(c.name for c in clips)}")


main()
