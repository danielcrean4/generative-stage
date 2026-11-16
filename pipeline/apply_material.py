"""Apply supplied PBR maps to a static GLB as a separate review candidate.

No inference or cache: outputs are immutable, and source materials are replaced only
with an explicit flag. The resulting GLB is not automatically game-ready.
"""
import argparse
import hashlib
import json
import struct
import subprocess
import sys
import time
import zlib
from pathlib import Path

MAPS = ('basecolor', 'normal', 'roughness', 'metallic')
SCRIPT = Path(__file__).resolve().parent.parent / 'blender' / 'apply_pbr.py'
sys.path.insert(0, str(Path(__file__).resolve().parent))
import host


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def png_size(path):
    """Validate PNG chunks and exact decoded scanlines before creating output."""
    with path.open('rb') as stream:
        if stream.read(8) != b'\x89PNG\r\n\x1a\n':
            raise ValueError(f'invalid PNG signature: {path}')
        size = None
        inflater = zlib.decompressobj()
        seen_data = False
        seen_palette = False
        decoded = 0
        expected = 0
        filter_offsets = []
        filter_index = 0
        while True:
            head = stream.read(8)
            if len(head) != 8:
                raise ValueError(f'truncated PNG chunk: {path}')
            length, kind = struct.unpack('>I4s', head)
            if length > 128 * 1024 * 1024:
                raise ValueError(f'PNG chunk too large: {path}')
            if size is None and kind != b'IHDR':
                raise ValueError(f'PNG must begin with IHDR: {path}')
            if kind == b'IHDR' and length != 13:
                raise ValueError(f'invalid PNG header length: {path}')
            crc = zlib.crc32(kind)
            remaining = length
            header = b''
            while remaining:
                block = stream.read(min(remaining, 65536))
                if not block:
                    raise ValueError(f'truncated PNG data: {path}')
                remaining -= len(block)
                crc = zlib.crc32(block, crc)
                if kind == b'IHDR':
                    header += block
                if kind == b'IDAT':
                    if size is None:
                        raise ValueError(f'PNG image data precedes header: {path}')
                    seen_data = True
                    try:
                        pending = block
                        while pending:
                            chunk = inflater.decompress(pending, 65536)
                            while filter_index < len(filter_offsets) and filter_offsets[filter_index] < decoded + len(chunk):
                                offset = filter_offsets[filter_index] - decoded
                                if offset < 0 or chunk[offset] > 4:
                                    raise ValueError(f'invalid PNG scanline filter: {path}')
                                filter_index += 1
                            decoded += len(chunk)
                            if decoded > expected:
                                raise ValueError(f'PNG decoded data exceeds expected scanlines: {path}')
                            pending = inflater.unconsumed_tail
                    except zlib.error as exc:
                        raise ValueError(f'invalid PNG compressed data: {path}') from exc
            stored = stream.read(4)
            if len(stored) != 4 or (crc & 0xffffffff) != struct.unpack('>I', stored)[0]:
                raise ValueError(f'invalid PNG chunk checksum: {path}')
            if kind == b'IHDR':
                if size is not None or length != 13:
                    raise ValueError(f'invalid PNG header: {path}')
                width, height, bits, color, compression, filtering, interlace = struct.unpack('>IIBBBBB', header)
                allowed = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8), 4: (8, 16), 6: (8, 16)}
                channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
                if not (1 <= width <= 8192 and 1 <= height <= 8192) or color not in allowed or bits not in allowed[color] or compression != 0 or filtering != 0 or interlace not in (0, 1):
                    raise ValueError(f'invalid PNG dimensions or IHDR format: {path}')
                size = [width, height]
                passes = [(0, 0, 1, 1)] if interlace == 0 else [(0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4), (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2)]
                for x, y, dx, dy in passes:
                    w = max(0, (width - x + dx - 1) // dx)
                    h = max(0, (height - y + dy - 1) // dy)
                    if not w or not h:
                        continue
                    stride = 1 + (w * channels[color] * bits + 7) // 8
                    for _ in range(h):
                        filter_offsets.append(expected)
                        expected += stride
            elif kind == b'PLTE':
                if seen_data or length < 3 or length > 768 or length % 3:
                    raise ValueError(f'invalid PNG palette: {path}')
                seen_palette = True
            elif kind == b'IEND':
                if length or not seen_data or not inflater.eof or inflater.unused_data or decoded != expected or filter_index != len(filter_offsets) or (color == 3 and not seen_palette) or stream.read(1):
                    raise ValueError(f'incomplete PNG: {path}')
                return size


def validate(mesh_arg, maps_arg, out_arg, replace):
    if not replace:
        raise ValueError('--replace-materials is required; source material bindings will be replaced in the output copy')
    mesh, maps, out = (Path(value).expanduser() for value in (mesh_arg, maps_arg, out_arg))
    if not all(p.is_absolute() for p in (mesh, maps, out)):
        raise ValueError('mesh, maps and out must be absolute paths')
    mesh, maps, out = (p.resolve() for p in (mesh, maps, out))
    if not mesh.is_file() or mesh.suffix.lower() != '.glb':
        raise ValueError('mesh must be an existing GLB')
    with mesh.open('rb') as stream:
        header = stream.read(20)
        if len(header) != 20 or header[:4] != b'glTF':
            raise ValueError('mesh is not a binary glTF file')
        version, total, json_size, chunk_type = struct.unpack_from('<IIII', header, 4)
        if version != 2 or total != mesh.stat().st_size or chunk_type != 0x4e4f534a or json_size > 64 * 1024 * 1024:
            raise ValueError('mesh has an invalid GLB header')
        try:
            gltf = json.loads(stream.read(json_size))
        except (UnicodeDecodeError, ValueError) as exc:
            raise ValueError('mesh has invalid GLB JSON') from exc
        if not isinstance(gltf, dict):
            raise ValueError('mesh GLB JSON must be an object')
        for key in ('meshes', 'buffers', 'images', 'skins', 'animations'):
            items = gltf.get(key, [])
            if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
                raise ValueError(f'invalid GLB {key} list')
        for item in gltf.get('meshes', []):
            primitives = item.get('primitives', [])
            if not isinstance(primitives, list) or any(not isinstance(prim, dict) for prim in primitives):
                raise ValueError('invalid GLB primitives list')
        if gltf.get('skins') or gltf.get('animations') or any(prim.get('targets') for item in gltf.get('meshes', []) for prim in item.get('primitives', [])):
            raise ValueError('skinned, animated, or morph-target GLBs are not supported')
        for item in gltf.get('buffers', []) + gltf.get('images', []):
            uri = item.get('uri')
            if uri is not None and (not isinstance(uri, str) or not uri.startswith('data:')):
                raise ValueError('external or invalid GLB resources are not supported')
    if not maps.is_dir():
        raise ValueError('maps must be an existing directory')
    if out.exists() or out in (Path('/'), Path.home(), Path(__file__).resolve().parents[1]):
        raise ValueError('out must be a new dedicated directory')
    paths = {key: maps / (key + '.png') for key in MAPS}
    if any(not p.is_file() for p in paths.values()):
        raise ValueError('maps directory must contain basecolor, normal, roughness and metallic PNGs')
    height = maps / 'height.png'
    if height.exists():
        if not height.is_file():
            raise ValueError('height.png must be a file if supplied')
        paths['height'] = height
    if any(out == p or out in p.parents for p in [mesh, *paths.values()]):
        raise ValueError('inputs must be outside the output directory')
    sizes = {name: png_size(path) for name, path in paths.items()}
    if len({tuple(value) for value in sizes.values()}) != 1:
        raise ValueError('all supplied map dimensions must match')
    return mesh, paths, out, sizes


def embedded_material_report(path):
    """Inspect the binary glTF's JSON for embedded textures and required channels."""
    with path.open('rb') as stream:
        header = stream.read(20)
        if len(header) < 20 or header[:4] != b'glTF':
            raise ValueError('output is not a GLB')
        json_size, kind = struct.unpack_from('<II', header, 12)
        if kind != 0x4e4f534a or json_size > 64 * 1024 * 1024:
            raise ValueError('output has invalid GLB JSON chunk')
        data = json.loads(stream.read(json_size))
    images = data.get('images', [])
    if not images or any('bufferView' not in image or 'uri' in image for image in images):
        raise ValueError('output images are not embedded in the GLB')
    materials = data.get('materials', [])
    if not materials or any(not all(k in mat.get('pbrMetallicRoughness', {}) for k in ('baseColorTexture', 'metallicRoughnessTexture')) or 'normalTexture' not in mat for mat in materials):
        raise ValueError('output lacks required PBR texture channels')
    meshes = data.get('meshes', [])
    if not meshes or any('TEXCOORD_0' not in prim.get('attributes', {}) for m in meshes for prim in m.get('primitives', [])):
        raise ValueError('output lacks UV coordinates')
    return {'embedded_images': len(images), 'materials': len(materials), 'meshes': len(meshes)}


def run(mesh_arg, maps_arg, out_arg, replace=False, timeout=300):
    mesh, paths, out, sizes = validate(mesh_arg, maps_arg, out_arg, replace)
    # Hash inputs before creating any output; never mutate source files.
    recipe = {'mesh': {'path': str(mesh), 'sha256': sha256(mesh)},
              'maps': {key: {'path': str(path), 'sha256': sha256(path), 'size': sizes[key]} for key, path in paths.items()},
              'replace_materials': True, 'height_applied': False, 'tool_sha256': sha256(Path(__file__)),
              'blender_script_sha256': sha256(SCRIPT)}
    out.mkdir(parents=True, exist_ok=False)
    record = {'status': 'running', 'recipe': recipe, 'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    try:
        command = ['blender', '--background', '--factory-startup', '--python-exit-code', '1', '--python', str(SCRIPT), '--', str(mesh), str(out), json.dumps({key: str(value) for key, value in paths.items()})]
        with (out / 'blender.log').open('w') as log:
            completed = subprocess.run(host.sandboxed(command, 'deny'), stdout=log, stderr=subprocess.STDOUT, timeout=timeout, check=False)
        if completed.returncode:
            raise RuntimeError(f'Blender exited {completed.returncode}; see {out / "blender.log"}')
        candidate = out / 'material.glb'
        record['evidence'] = json.loads((out / 'material-evidence.json').read_text())
        record['output_validation'] = embedded_material_report(candidate)
        record['output_sha256'] = sha256(candidate)
        record['status'] = 'candidate'
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        record['status'] = 'failed'
        record['error'] = str(exc)
        raise
    finally:
        record['finished_utc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        (out / 'attempt.json').write_text(json.dumps(record, indent=2) + '\n')
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mesh', required=True)
    parser.add_argument('--maps', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--replace-materials', action='store_true')
    args = parser.parse_args()
    try:
        result = run(args.mesh, args.maps, args.out, args.replace_materials)
        print(json.dumps({'status': result['status'], 'output_sha256': result['output_sha256']}))
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
