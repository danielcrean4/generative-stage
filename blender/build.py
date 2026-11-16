# SPDX-License-Identifier: MIT OR GPL-3.0-or-later
"""Builds asset families into .glb files plus a contact sheet each.

    blender --background --factory-startup --python blender/build.py -- \\
        --families <dir> --manifest <file.json> --palette <file.json> --out <dir> [family ...]

A family is a module <family>.py in the families folder with build(name, rng), returning
(visual_object, collision_object or None for things you walk through). It paints only with
style.material / style.pick and builds with kit. The manifest says how many variants each
family gets: {"tree": {"variants": 15}}. With no family names, everything in it is built.

Variants are seeded by name ("tree_03"), so a rebuild gives the same geometry. Outputs:
    <out>/<family>/<family>_NN.glb
    <out>/<family>/build.json         what made these files (palette hash, Blender version)
    <out>/previews/<family>.png       the contact sheet
"""
import argparse
import importlib
import json
import os
import random
import sys

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import kit  # noqa: E402  (needs the path above)
import palette  # noqa: E402
import preview  # noqa: E402
import style  # noqa: E402


def build_family(family: str, variants: int, out: str, palette_path: str, pal: palette.Palette) -> None:
    module = importlib.import_module(family)
    out_dir = os.path.join(out, family)
    os.makedirs(out_dir, exist_ok=True)
    for stale in (f for f in os.listdir(out_dir) if f.endswith(".glb")):
        os.remove(os.path.join(out_dir, stale))

    kit.reset()
    style.use(pal)
    visuals = []
    for i in range(variants):
        name = f"{family}_{i:02d}"
        visual, collision = module.build(name, random.Random(name))
        to_export = []
        for root in (visual, collision):
            if root:
                to_export.append(root)
                to_export.extend(root.children_recursive)
        kit.export_glb(to_export, os.path.join(out_dir, f"{name}.glb"))
        visuals.append(visual)

    record = {
        "family": family,
        "variants": variants,
        "palette": os.path.basename(palette_path),
        "palette_sha256": pal.sha256,
        "blender": bpy.app.version_string,
    }
    with open(os.path.join(out_dir, "build.json"), "w") as f:
        json.dump(record, f, indent=2)
        f.write("\n")

    preview_dir = os.path.join(out, "previews")
    os.makedirs(preview_dir, exist_ok=True)
    preview.contact_sheet(visuals, os.path.join(preview_dir, f"{family}.png"))
    print(f"BUILT {family}: {variants} variants")


def main() -> None:
    parser = argparse.ArgumentParser(prog="blender/build.py")
    parser.add_argument("--families", required=True, help="folder of family modules")
    parser.add_argument("--manifest", required=True, help="JSON: family -> {variants}")
    parser.add_argument("--palette", required=True, help="palette JSON (see blender/palette.py)")
    parser.add_argument("--out", required=True, help="output folder")
    parser.add_argument("family", nargs="*", help="families to build (default: all in the manifest)")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])

    sys.path.insert(0, os.path.abspath(args.families))
    pal = palette.load(args.palette)
    with open(args.manifest) as f:
        manifest = json.load(f)
    unknown = [name for name in args.family if name not in manifest]
    if unknown:
        sys.exit(f"not in {args.manifest}: {', '.join(unknown)}")
    for family in args.family or manifest:
        build_family(family, manifest[family]["variants"], os.path.abspath(args.out), args.palette, pal)


main()
