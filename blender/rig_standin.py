# SPDX-License-Identifier: MIT OR GPL-3.0-or-later
"""The stand-in rigger: fits a rig profile to a mesh and weights it, classically (no model). Headless only:

    blender --background --factory-startup --python-exit-code 1 --python rig_standin.py -- \\
        --mesh IN.glb --profile rigs/biped.json --output rigged.glb --rig-out rig.json --report rig-report.json

The mesh's pieces are joined into one, any skin it had is dropped, and motion/fit.py places the profile's joints by
the mesh's bounds, pulls any joint that falls outside the body back inside (Blender's BVH answers "inside?"), and
gives every vertex the weights of its nearest bone segments. The armature is built like build_rigged.py's, so the
procedural clips key on it directly. Outputs:
    rigged.glb        the mesh, its armature and skin; no animation
    rig.json          the fitted rig profile (motion/rig.py's format), ground at y = 0: what the motion stage makes
                      clips for
    rig-report.json   how it was fitted: scales, joints pulled inside, vertex count, Blender version
"""
import argparse
import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, str(Path(__file__).resolve().parent))

import kit  # noqa: E402  (needs the path above)
from motion import fit, rig as rigs  # noqa: E402
from rigging import blender, build_armature, export_rigged, gltf  # noqa: E402

RAYS = (Vector((1.0, 0.013, 0.007)), Vector((-0.011, 1.0, 0.017)), Vector((0.019, -0.009, 1.0)))  # off-axis: no edge hits


def load_mesh(path: str) -> bpy.types.Object:
    """The .glb's meshes joined into one object with transforms applied, skin and armatures removed."""
    bpy.ops.import_scene.gltf(filepath=path)
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if not meshes:
        raise SystemExit(f"{path}: no mesh in the file")
    for obj in meshes:
        placed = obj.matrix_world.copy()
        obj.parent = None
        obj.matrix_world = placed
    for obj in list(bpy.context.scene.objects):
        if obj.type != "MESH":
            bpy.data.objects.remove(obj, do_unlink=True)
    mesh = kit.join(meshes, "body") if len(meshes) > 1 else meshes[0]
    mesh.name = "body"
    for modifier in list(mesh.modifiers):
        mesh.modifiers.remove(modifier)
    mesh.vertex_groups.clear()
    with bpy.context.temp_override(active_object=mesh, selected_editable_objects=[mesh], selected_objects=[mesh]):
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    return mesh


def inside_test(mesh: bpy.types.Object):
    """(inside(point), nearest(point)) on MESH, points in glTF axes; inside = odd hits on most of three rays."""
    tree = BVHTree.FromObject(mesh, bpy.context.evaluated_depsgraph_get())

    def hits(origin: Vector, direction: Vector) -> int:
        count, start = 0, origin
        direction = direction.normalized()
        while count < 10000:
            location, _, _, _ = tree.ray_cast(start, direction)
            if location is None:
                return count
            count += 1
            start = location + direction * 1e-5
        return count

    def inside(point) -> bool:
        origin = blender(point)
        return sum(hits(origin, ray) % 2 for ray in RAYS) >= 2

    def nearest(point):
        location, normal, _, _ = tree.find_nearest(blender(point))
        return gltf(location), gltf(normal)

    return inside, nearest


def main() -> None:
    parser = argparse.ArgumentParser(prog="rig_standin.py")
    for name in ("mesh", "profile", "output", "rig-out", "report"):
        parser.add_argument(f"--{name}", required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])

    rig = rigs.load(args.profile)
    kit.reset()
    mesh = load_mesh(args.mesh)
    points = [gltf(v.co) for v in mesh.data.vertices]
    world, scales = fit.fit(rig, points)
    inside, nearest = inside_test(mesh)
    moved = fit.pull_inside(world, rig, scales["height"], inside, nearest)
    fitted = fit.profile(rig, world, scales["ground"])
    Path(args.rig_out).write_text(json.dumps(fitted, indent=1) + "\n")
    fitted_rig = rigs.load(args.rig_out)

    arm = build_armature(fitted_rig, world)
    by_vertex = fit.weights(points, fit.segments(fitted_rig, world, scales["vertical"]))
    groups = {name: mesh.vertex_groups.new(name=name) for name in fitted_rig.joints}
    for index, weights in enumerate(by_vertex):
        for name, weight in weights.items():
            groups[name].add([index], weight, "REPLACE")
    mesh.parent = arm
    mesh.modifiers.new("Armature", "ARMATURE").object = arm
    export_rigged((arm, mesh), args.output, animations=False)

    outside = [name for name in fit.deforming(fitted_rig) if not inside(world[name])]
    Path(args.report).write_text(json.dumps({
        "method": "profile fitted to the mesh bounds; nearest-bone-segment weights",
        "profile": Path(args.profile).name, "blender": bpy.app.version_string,
        "vertices": len(points), "scales": {k: round(v, 6) for k, v in scales.items()},
        "pulled_inside": moved, "still_outside": outside,
    }, indent=1) + "\n")
    print(f"RIGGED {len(points)} vertices, {len(fitted_rig.joints)} joints, pulled inside: {moved or 'none'}")


main()
