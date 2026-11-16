# SPDX-License-Identifier: MIT OR GPL-3.0-or-later
"""Trusted Blender worker for applying explicit maps to static GLBs; run headless only."""
import json
import sys
from pathlib import Path

import bpy


def main():
    source, output, raw_maps = sys.argv[sys.argv.index('--') + 1:]
    maps = json.loads(raw_maps)
    out = Path(output)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=source)
    objects = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']
    if not objects:
        raise ValueError('GLB has no mesh objects')
    if (any(obj.type == 'ARMATURE' or obj.animation_data for obj in bpy.context.scene.objects)
            or bpy.data.actions
            or any(obj.data.shape_keys or obj.vertex_groups or any(mod.type == 'ARMATURE' for mod in obj.modifiers) for obj in objects)):
        raise ValueError('skinned, animated, or shape-keyed GLBs are not supported')
    warnings = []
    if len(objects) > 1:
        warnings.append('Multiple meshes share one material and may overlap in UV space.')
    uv_by_object = {}
    for obj in objects:
        if obj.data.uv_layers:
            uv_by_object[obj.name] = 'preserved'
            continue
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.uv.smart_project(angle_limit=1.151917, island_margin=0.02)
        bpy.ops.object.mode_set(mode='OBJECT')
        if not obj.data.uv_layers:
            raise ValueError(f'UV creation failed: {obj.name}')
        uv_by_object[obj.name] = 'blender_smart_project_angle_66_margin_0.02'
        warnings.append(f'{obj.name}: generated UVs may contain seams or distortion.')
    material = bpy.data.materials.new('AppliedPBR')
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    principled = nodes.get('Principled BSDF')
    if principled is None:
        raise ValueError('Blender default Principled BSDF missing')
    for name in ('basecolor', 'normal', 'roughness', 'metallic'):
        image = bpy.data.images.load(maps[name], check_existing=False)
        if image.size[0] < 1 or image.size[1] < 1:
            raise ValueError(f'Invalid image: {name}')
        image.colorspace_settings.name = 'sRGB' if name == 'basecolor' else 'Non-Color'
        if name == 'basecolor' and image.depth == 32:
            warnings.append('Base-color alpha was not applied; output is opaque.')
        node = nodes.new('ShaderNodeTexImage')
        node.name = f'Map_{name}'
        node.image = image
        if name == 'normal':
            normal = nodes.new('ShaderNodeNormalMap')
            links.new(node.outputs['Color'], normal.inputs['Color'])
            links.new(normal.outputs['Normal'], principled.inputs['Normal'])
        else:
            target = {'basecolor': 'Base Color', 'roughness': 'Roughness', 'metallic': 'Metallic'}[name]
            links.new(node.outputs['Color'], principled.inputs[target])
    if 'height' in maps:
        warnings.append('Height map recorded but not applied as displacement or bump.')
    for obj in objects:
        obj.data.materials.clear()
        obj.data.materials.append(material)
        for face in obj.data.polygons:
            face.material_index = 0
    bpy.ops.export_scene.gltf(filepath=str(out / 'material.glb'), export_format='GLB', export_yup=True,
                              export_skins=False, export_animations=False)
    evidence = {'blender_version': bpy.app.version_string, 'mesh_count': len(objects), 'uv_by_object': uv_by_object,
                'node_connections': ['basecolor->Base Color (sRGB)', 'normal->Normal Map->Normal (Non-Color)',
                                     'roughness->Roughness (Non-Color)', 'metallic->Metallic (Non-Color)'],
                'material_replacement': 'explicit', 'warnings': warnings, 'game_ready': False}
    (out / 'material-evidence.json').write_text(json.dumps(evidence, indent=2) + '\n')
    print('APPLIED_PBR', json.dumps(evidence))


if __name__ == '__main__':
    main()
