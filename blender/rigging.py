# SPDX-License-Identifier: MIT OR GPL-3.0-or-later
"""Armatures and clips in Blender, shared by build_rigged.py, rig_standin.py and animate_standin.py.

Rig profiles and clips use glTF axes (Y up, +Z forward); Blender is Z up. A clip's joint rotation is an Euler angle in
the joint's parent frame, which at rest is lined up with the world. `key_clip` turns that into each pose bone's own
rest frame, so it keys correctly on any armature whose bones carry the profile's joint names, whatever way its bones
point (one built here, or one read back from a .glb).
"""
import bpy
from mathutils import Matrix, Vector

from motion import rig as rigs

BONE_LENGTH = 0.05

# glTF (Y up, +Z forward) to Blender (Z up, -Y forward): a quarter turn about X.
TO_BLENDER = Matrix(((1, 0, 0), (0, 0, -1), (0, 1, 0)))
FROM_BLENDER = TO_BLENDER.transposed()


def blender(v) -> Vector:
    return TO_BLENDER @ Vector(v)


def gltf(v) -> tuple[float, float, float]:
    out = FROM_BLENDER @ Vector(v)
    return (out.x, out.y, out.z)


def world_positions(rig: rigs.Rig) -> dict[str, tuple[float, float, float]]:
    """Rest position of every joint and site in glTF axes (rest rotations are all identity)."""
    world: dict[str, tuple[float, float, float]] = {}
    for name in [*rig.joints, *rig.sites]:
        parent = rig.joints[name].parent if name in rig.joints else rig.sites[name].parent
        world[name] = rigs.add(world[parent], rig.offset(name)) if parent else rig.offset(name)
    return world


def build_armature(rig: rigs.Rig, world: dict) -> bpy.types.Object:
    """An armature with one short bone per joint at its rest position, all lined up with the world axes."""
    arm_data = bpy.data.armatures.new(rig.name)
    arm = bpy.data.objects.new(rig.name, arm_data)
    bpy.context.scene.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    for name, joint in rig.joints.items():
        bone = arm_data.edit_bones.new(name)
        bone.head = blender(world[name])
        bone.tail = bone.head + Vector((0, BONE_LENGTH, 0))  # Blender +Y, roll 0: axes match the world's
        bone.roll = 0.0
        if joint.parent:
            bone.parent = arm_data.edit_bones[joint.parent]
    bpy.ops.object.mode_set(mode="OBJECT")
    return arm


def to_blender_quaternion(euler_gltf, rest=None):
    """A clip rotation (YXZ Euler, glTF axes) as a pose bone quaternion; REST is the bone's rest rotation in
    armature space (Blender axes), identity for bones built by build_armature."""
    turn = TO_BLENDER @ Matrix(rigs.euler(tuple(euler_gltf))) @ FROM_BLENDER
    if rest is not None:
        turn = rest.transposed() @ turn @ rest
    return turn.to_quaternion()


def key_clip(arm: bpy.types.Object, rig: rigs.Rig, clip: dict) -> bpy.types.Action:
    """Keys CLIP (a clip dict from build_motions.py, with `length_frames`) as its own action, then leaves the
    armature at rest with no action assigned, so the next clip starts clean."""
    action = bpy.data.actions.new(clip["name"])
    action.use_fake_user = True
    arm.animation_data_create().action = action
    bpy.context.scene.render.fps = clip["fps"]
    for joint, track in clip["tracks"].items():
        bone = arm.pose.bones[joint]
        bone.rotation_mode = "QUATERNION"
        rest = bone.bone.matrix_local.to_3x3()
        offset = rig.joints[joint].offset
        for i in range(clip["length_frames"] + 1):
            if "rotation" in track:
                bone.rotation_quaternion = to_blender_quaternion(track["rotation"][i], rest)
                bone.keyframe_insert("rotation_quaternion", frame=i + 1)
            if "position" in track:
                move = TO_BLENDER @ Vector([p - r for p, r in zip(track["position"][i], offset, strict=True)])
                bone.location = rest.transposed() @ move
                bone.keyframe_insert("location", frame=i + 1)
    for bone in arm.pose.bones:
        bone.rotation_quaternion = (1, 0, 0, 0)
        bone.location = (0, 0, 0)
    arm.animation_data.action = None
    return action


def export_rigged(objects, path: str, animations: bool) -> None:
    """OBJECTS (an armature and its meshes) as one .glb with skins, and every action when ANIMATIONS."""
    for obj in bpy.context.scene.objects:
        obj.select_set(obj in objects)
    bpy.ops.export_scene.gltf(
        filepath=path, export_format="GLB", use_selection=True, export_yup=True, export_apply=False,
        export_animations=animations, export_animation_mode="ACTIONS", export_skins=True,
    )
