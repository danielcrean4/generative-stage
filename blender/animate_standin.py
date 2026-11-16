# SPDX-License-Identifier: MIT OR GPL-3.0-or-later
"""The stand-in animator: makes the named procedural clips for a rigged .glb and keys them on it (no model).
Headless only:

    blender --background --factory-startup --python-exit-code 1 --python animate_standin.py -- \\
        --mesh rigged.glb --rig rig.json --clips idle,walk --manifest motion_manifest.json --motions DIR \\
        --output animated.glb --report clips.json

The clips are made for the fitted profile in rig.json (so planted feet land where its legs reach) by the motion
families the manifest lists for a rig of that name, with the manifest's parameters, seeded by "rig/clip" as
build_motions.py does. Each clip's checks (limits, loop, events, floor, slide) are recorded, not enforced. After
keying, every bone's posed head is compared with the profile's forward kinematics at a few frames; a mismatch is an
error, so a clip that would play wrongly never leaves this script. Outputs:
    animated.glb    the rigged mesh with one animation per clip
    clips.json      per clip: length, frames, loop, speed, events and check problems; Blender version
"""
import argparse
import importlib
import json
import random
import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))

import kit  # noqa: E402  (needs the path above)
from motion import checks, rig as rigs  # noqa: E402
from rigging import blender, export_rigged, key_clip  # noqa: E402

TOLERANCE = 0.005  # metres a posed bone head may differ from the profile's forward kinematics
SAMPLES = 4        # frames compared per clip


def families_for(manifest: dict, rig_name: str) -> dict[str, tuple[str, dict]]:
    """{clip: (family, parameter overrides)} the manifest offers a rig called RIG_NAME."""
    offered: dict[str, tuple[str, dict]] = {}
    for entry in manifest["clips"]:
        if entry["rig"] == rig_name:
            for clip in entry["clips"]:
                offered.setdefault(clip, (entry["family"], entry.get("params", {}).get(clip, {})))
    return offered


def make_clip(rig: rigs.Rig, name: str, family_name: str, overrides: dict):
    family = importlib.import_module(family_name)
    params = dict(family.DEFAULTS.get(name, {}))
    unknown = sorted(set(overrides) - set(params))
    if unknown:
        raise SystemExit(f"{rig.name}/{name}: {family_name} has no parameters {unknown}")
    params.update(overrides)
    clip = family.CLIPS[name](rig, params, random.Random(f"{rig.name}/{name}"))
    clip.name = name
    return clip, checks.check(clip, getattr(family, "EVENTS", {}).get(name, []))


def verify(arm: bpy.types.Object, rig: rigs.Rig, clip, action: bpy.types.Action) -> None:
    """Every keyed bone's head at a few frames matches the profile's forward kinematics, or SystemExit."""
    root = next(name for name, joint in rig.joints.items() if joint.parent is None)
    shift = arm.matrix_world @ arm.data.bones[root].head_local - blender(rig.joints[root].offset)  # the profile's ground
    arm.animation_data.action = action
    frames = len(clip.times())
    for frame in sorted({0, frames // 3, (2 * frames) // 3, frames - 1})[:SAMPLES]:
        bpy.context.scene.frame_set(frame + 1)
        bpy.context.view_layer.update()
        expected = rigs.forward(rig, *clip.pose(frame))
        for name in rig.joints:
            posed = arm.matrix_world @ arm.pose.bones[name].head
            gap = (posed - shift - blender(expected[name][0])).length
            if gap > TOLERANCE:
                raise SystemExit(f"clip {clip.name}: bone {name} at frame {frame} is {gap:.4f} m from where the clip "
                                 "puts it; the armature does not match the rig profile")
    arm.animation_data.action = None


def main() -> None:
    parser = argparse.ArgumentParser(prog="animate_standin.py")
    for name in ("mesh", "rig", "clips", "manifest", "motions", "output", "report"):
        parser.add_argument(f"--{name}", required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    sys.path.insert(0, str(Path(args.motions).resolve()))

    rig = rigs.load(args.rig)
    offered = families_for(json.loads(Path(args.manifest).read_text()), rig.name)
    names = [name for name in args.clips.split(",") if name]
    missing = [name for name in names if name not in offered]
    if not names or missing:
        raise SystemExit(f"no clip {', '.join(missing) or '(none named)'} for a rig called '{rig.name}' "
                         f"(offered: {', '.join(sorted(offered))})")

    kit.reset()
    bpy.ops.import_scene.gltf(filepath=args.mesh)
    arms = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
    if len(arms) != 1:
        raise SystemExit(f"{args.mesh}: expected one armature, found {len(arms)}")
    arm = arms[0]
    absent = sorted(set(rig.joints) - set(arm.pose.bones.keys()))
    if absent:
        raise SystemExit(f"{args.mesh}: the armature has no bones {absent} that the rig profile names")
    for action in list(bpy.data.actions):  # anything the file brought with it is replaced by the named clips
        bpy.data.actions.remove(action)

    report = {"rig": rig.name, "blender": bpy.app.version_string, "clips": []}
    for name in names:
        family, overrides = offered[name]
        clip, problems = make_clip(rig, name, family, overrides)
        data = clip.to_dict()
        data["length_frames"] = len(clip.times()) - 1
        action = key_clip(arm, rig, data)
        verify(arm, rig, clip, action)
        report["clips"].append({"name": name, "family": family, "length": data["length"], "fps": data["fps"],
                                "frames": data["length_frames"] + 1, "loop": data["loop"], "speed": data["speed"],
                                "events": data["events"], "problems": problems})
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    export_rigged((arm, *meshes), args.output, animations=True)
    Path(args.report).write_text(json.dumps(report, indent=1) + "\n")
    print(f"ANIMATED {len(names)} clips: {', '.join(names)}")


main()
