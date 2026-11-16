"""Prepare traceable reference crops from a data-only component layout.

Crops retain the background and any overlapping parts; they are reference images,
not segmented objects or automatic image-to-3D inputs.
"""
import argparse
import hashlib
import json
import math
import os
import re
import tempfile
from pathlib import Path

from PIL import Image


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def prepare(spec_path, output):
    spec_path = spec_path.resolve()
    output = output.resolve()
    spec = json.loads(spec_path.read_text())
    if (not isinstance(spec, dict) or set(spec) != {'version', 'source', 'components'}
            or type(spec['version']) is not int or spec['version'] != 1):
        raise ValueError('expected version 1, source and components')
    source = Path(spec['source'])
    if not source.is_absolute() or not source.is_file():
        raise ValueError('source must be an absolute existing image')
    source = source.resolve()
    items = spec['components']
    if not isinstance(items, list) or not 1 <= len(items) <= 100:
        raise ValueError('components must contain 1 to 100 items')
    if output.exists() or not output.parent.is_dir():
        raise ValueError('output must be a new directory with an existing parent')
    source_hash, spec_hash = digest(source), digest(spec_path)
    names = set()
    with Image.open(source) as image:
        width, height = image.size
        if width * height > 67_108_864:
            raise ValueError('source image is too large')
        image.load()
        rects = []
        for item in items:
            if not isinstance(item, dict) or set(item) != {'id', 'box'}:
                raise ValueError('each component needs id and box')
            name, box = item['id'], item['box']
            if not isinstance(name, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,47}', name) or name.casefold() in names:
                raise ValueError('component IDs must be unique safe names, ignoring case')
            if (not isinstance(box, list) or len(box) != 4 or
                any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in box) or
                box[0] >= box[2] or box[1] >= box[3]):
                raise ValueError('box must be normalized [left, top, right, bottom]')
            bounds = [math.floor(box[0]*width), math.floor(box[1]*height),
                      math.ceil(box[2]*width), math.ceil(box[3]*height)]
            names.add(name.casefold())
            rects.append((name, box, bounds))
        with tempfile.TemporaryDirectory(prefix='.component-crops-', dir=output.parent) as temp:
            stage = Path(temp) / 'result'
            stage.mkdir()
            records = []
            for name, box, bounds in rects:
                dest = stage / (name + '.png')
                image.crop(bounds).save(dest, format='PNG')
                records.append({'id': name, 'box': box, 'pixel_box': bounds,
                                'file': dest.name, 'sha256': digest(dest)})
            if digest(source) != source_hash or digest(spec_path) != spec_hash:
                raise ValueError('source or specification changed during processing')
            manifest = {'version': 1, 'source': str(source), 'source_sha256': source_hash,
                        'spec_sha256': spec_hash, 'source_size': [width, height],
                        'kind': 'reference_crops_not_segmentation', 'components': records}
            (stage / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
            # mkdir fails if another process creates the destination meanwhile.
            # Publish the manifest last, so a partial directory cannot look complete.
            output.mkdir()
            for name, _, _ in rects:
                os.rename(stage / (name + '.png'), output / (name + '.png'))
            os.rename(stage / 'manifest.json', output / 'manifest.json')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('spec', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    try:
        result = prepare(args.spec, args.output)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.exit(1, f'{exc}\n')
    print(json.dumps({'output': str(args.output.resolve()), 'components': len(result['components'])}))


if __name__ == '__main__':
    main()
