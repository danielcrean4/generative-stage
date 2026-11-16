# SPDX-License-Identifier: MIT OR GPL-3.0-or-later
"""Geometry and export helpers shared by every asset family.

All parts are built in world space (objects stay at the origin), so joining them
never has to bake transforms. Blender is Z-up; the glTF export converts to Godot's
Y-up, and Blender -Y becomes Godot +Z (an asset's "front").
"""
import bpy
import bmesh
from mathutils import Euler, Matrix, Vector


def reset() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def variant_index(name: str) -> int:
    """The NN in "family_NN", for families that cycle through sub-types by index."""
    return int(name.rsplit("_", 1)[1])


def box(size, loc, mat, rot=(0.0, 0.0, 0.0)) -> bpy.types.Object:
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bm.transform(Matrix.Translation(loc) @ Euler(rot).to_matrix().to_4x4() @ Matrix.Diagonal((*size, 1.0)))
    return _link("box", bm, mat)


def cylinder(radius: float, height: float, loc, mat, segments: int = 12) -> bpy.types.Object:
    return cone(radius, radius, height, loc, mat, segments=segments)


def cone(bottom: float, top: float, height: float, loc, mat, rot=(0.0, 0.0, 0.0), segments: int = 12) -> bpy.types.Object:
    """A tapered cylinder centred on loc; rot tilts it around its centre."""
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=segments, radius1=bottom, radius2=top, depth=height)
    bm.transform(Matrix.Translation(loc) @ Euler(rot).to_matrix().to_4x4())
    return _link("cone", bm, mat)


def strut(start, end, bottom: float, top: float, mat, segments: int = 8) -> bpy.types.Object:
    """A tapered limb from start to end (legs, branches, braces)."""
    s, e = Vector(start), Vector(end)
    axis = e - s
    rot = axis.to_track_quat("Z", "Y").to_euler()
    return cone(bottom, top, axis.length, (s + e) / 2, mat, rot=tuple(rot), segments=segments)


def blob(radius: float, loc, mat, rng, scale=(1.0, 1.0, 1.0), jitter: float = 0.18) -> bpy.types.Object:
    """A lumpy, irregular sphere: each vertex is pushed in or out at random."""
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=2, radius=radius)
    for v in bm.verts:
        v.co *= 1.0 + rng.uniform(-jitter, jitter)
    bm.transform(Matrix.Translation(loc) @ Matrix.Diagonal((*scale, 1.0)))
    return _link("blob", bm, mat)


def poly(verts, faces, mat, thickness: float = 0.0) -> bpy.types.Object:
    """A custom mesh; with thickness, an open surface is solidified into a shell."""
    bm = bmesh.new()
    bm_verts = [bm.verts.new(v) for v in verts]
    for face in faces:
        bm.faces.new([bm_verts[i] for i in face])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    if thickness:
        bmesh.ops.solidify(bm, geom=bm.faces[:], thickness=thickness)
    return _link("poly", bm, mat)


def join(objs, name: str) -> bpy.types.Object:
    target = objs[0]
    with bpy.context.temp_override(active_object=target, selected_editable_objects=objs, selected_objects=objs):
        bpy.ops.object.join()
    target.name = name
    target.data.name = name
    return target


def collision_box(size, loc, name: str) -> bpy.types.Object:
    """An invisible box collider. The -convcolonly suffix tells Godot's importer to turn it
    into a StaticBody3D with a convex shape and drop the mesh."""
    obj = box(size, loc, None)
    obj.name = f"{name}-convcolonly"
    return obj


def export_glb(objs, path: str) -> None:
    for obj in bpy.context.scene.objects:
        obj.select_set(obj in objs)
    bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", use_selection=True, export_yup=True, export_apply=True)


def _link(name: str, bm, mat) -> bpy.types.Object:
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    if mat is not None:
        mesh.materials.append(mat)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj
