# SPDX-License-Identifier: MIT OR GPL-3.0-or-later
"""Contact sheets: one rendered image of every variant in a family, for review by eye."""
import bpy
from mathutils import Euler, Vector

import kit

SKY = (0.55, 0.68, 0.85, 1.0)  # pale blue, so dark and light assets both read
GROUND = (0.35, 0.35, 0.33, 1.0)  # mid grey, neutral against any palette
SUN_ENERGY = 3.5
SUN_ANGLE = (0.8, 0.2, -0.6)  # from front-left and above, so faces shade differently
VIEW = (-0.45, -1.0, 0.8)  # three-quarter view from the asset's front (Blender -Y)
SIZE = (1600, 900)


def contact_sheet(objs, path: str, columns: int = 4) -> None:
    """Lays the objects out in a grid sized to the largest one and renders them, child
    objects (such as turbine rotors) included."""
    scene = bpy.context.scene
    columns = min(columns, len(objs))
    largest = max(max(obj.dimensions.x, obj.dimensions.y, obj.dimensions.z) for obj in objs)
    spacing = largest * 1.4 + 0.5  # margins scale with the asset, so a cup frames as well as a house
    visible = set(objs)
    for obj in objs:
        visible.update(obj.children_recursive)
    for obj in scene.objects:
        obj.hide_render = obj not in visible
    for i, obj in enumerate(objs):
        obj.location = ((i % columns) * spacing, (i // columns) * spacing, 0.0)

    rows = (len(objs) + columns - 1) // columns
    center = Vector(((columns - 1) * spacing / 2, (rows - 1) * spacing / 2, spacing / 6))
    ground = bpy.data.materials.new("preview_ground")
    ground.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = GROUND
    kit.box((columns * spacing * 3, rows * spacing * 3, 0.2), (center.x, center.y, -0.1), ground)

    world = bpy.data.worlds.new("preview_sky")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = SKY
    scene.world = world

    sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", type="SUN"))
    sun.data.energy = SUN_ENERGY
    sun.rotation_euler = Euler(SUN_ANGLE)
    scene.collection.objects.link(sun)

    cam = bpy.data.objects.new("camera", bpy.data.cameras.new("camera"))
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = max(columns, rows) * spacing * 1.15
    direction = Vector(VIEW).normalized()
    cam.location = center + direction * spacing * 10
    cam.rotation_euler = (-direction).to_track_quat("-Z", "Y").to_euler()
    cam.data.clip_end = spacing * 30
    scene.collection.objects.link(cam)
    scene.camera = cam

    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x, scene.render.resolution_y = SIZE
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
