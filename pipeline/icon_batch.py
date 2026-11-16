"""One-call local icon delivery. No downloads, neural retries or silent overwrites.

    python3 -I icon_batch.py (--jobs-json JSON | --jobs FILE) [--adapter ID] [--validate-only]

Each job is {prompt, output (an absolute .png path), seed?}. The picture comes from an image adapter (adapter_config.py):
the one named by --adapter, else the machine config's default image adapter. Working files go under the machine
setting icon_dir.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import adapter_config
import adapter_run
import gpu_session
import machine
import provenance

SUFFIX = ', single isolated whole object, centered, generous margins, readable game inventory icon, no text or logos, no cast shadow, flat pure bright magenta #ff00ff background'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(raw, output):
    image = Image.open(raw).convert('RGBA')
    pixels = []
    for r, g, b, a in (image.get_flattened_data() if hasattr(image, 'get_flattened_data') else image.getdata()):
        key = min(r, b) - g
        alpha = 0 if key >= 100 else round(a * (100-key)/55) if key > 45 else a
        pixels.append((r, g, b, alpha))
    image.putdata(pixels)
    bounds = image.getbbox()
    if not bounds:
        raise ValueError('Empty icon after background removal')
    image = image.crop(bounds)
    image.thumbnail((224, 224), Image.Resampling.LANCZOS)
    canvas = Image.new('RGBA', (256, 256))
    canvas.alpha_composite(image, ((256-image.width)//2, (256-image.height)//2))
    canvas.save(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--jobs-json')
    source.add_argument('--jobs', type=Path)
    parser.add_argument('--validate-only', action='store_true')
    parser.add_argument('--adapter', help='the id of an image adapter (default: the machine config default)')
    args = parser.parse_args()
    jobs = json.loads(args.jobs_json if args.jobs_json is not None else args.jobs.read_text())
    if not isinstance(jobs, list) or not jobs:
        parser.error('Expected a nonempty JSON list')
    seen = set()
    for index, job in enumerate(jobs):
        if not isinstance(job, dict) or not isinstance(job.get('prompt'), str) or not job['prompt'].strip():
            parser.error('Every job needs a nonempty prompt')
        if set(job) - {'prompt', 'output', 'seed'}:
            parser.error('A job holds only prompt, output and seed; the adapter is chosen with --adapter')
        path = Path(job.get('output', ''))
        if not path.is_absolute() or path.suffix.lower() != '.png':
            parser.error('Every output must be an absolute PNG path')
        path = path.resolve()
        if path in seen:
            parser.error('Duplicate output path: '+str(path))
        seen.add(path)
        job['output'] = str(path)
        job.setdefault('seed', index+1)
        if type(job['seed']) is not int or not 0 <= job['seed'] < 2**32:
            parser.error('Seed must be an integer between0 and2^32-1')
    if args.validate_only:
        print(json.dumps({'validated': len(jobs), 'outputs': [j['output'] for j in jobs]}))
        return 0
    try:
        ARTIFACTS = machine.path('icon_dir')
        entry = adapter_config.from_machine().pick(args.adapter, 'image')
        identity = adapter_config.identity(entry)
    except (machine.MachineError, adapter_config.AdapterError) as exc:
        parser.error(str(exc))
    results = []
    gpu = gpu_session.GpuSession(lambda message: print(message, file=sys.stderr), 1800)
    for job in jobs:
        output = Path(job['output'])
        record_path = output.with_suffix('.source.json')
        started = time.monotonic()
        result = {**job, 'status': 'failed'}
        try:
            if output.exists() or record_path.exists():
                previous = json.loads(record_path.read_text()) if record_path.exists() else {}
                if output.is_file() and previous.get('prompt') == job['prompt'] and previous.get('seed') == job['seed'] and previous.get('output_sha256') == digest(output):
                    result['status'] = 'cached'
                    results.append(result)
                    continue
                raise ValueError('Existing output/provenance differs; choose a new path')
            output.parent.mkdir(parents=True, exist_ok=True)
            ARTIFACTS.mkdir(parents=True, exist_ok=True)
            attempt = Path(tempfile.mkdtemp(prefix='icon-', dir=ARTIFACTS))
            raw = attempt/'raw.png'
            log = attempt/'generation.log'
            resolved = job['prompt']+SUFFIX
            values = {'prompt': resolved, 'negative': '', 'seed': job['seed'], 'width': 512, 'height': 512,
                      'output': raw, 'out_dir': attempt}
            adapter_run.run(entry, values, attempt, gpu, log_name=log.name)
            temporary = attempt/'icon.png'
            prepare(raw, temporary)
            record = {**job, 'resolved_prompt': resolved, 'adapter': entry.id, 'model': identity,
                      'model_reported': adapter_run.reported(attempt), 'model_label': entry.model.get('name'), 'generated_at_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'script_sha256': digest(Path(__file__)), 'raw': str(raw), 'raw_sha256': digest(raw), 'output_sha256': digest(temporary), 'log': str(log), 'seconds': round(time.monotonic()-started, 2)}
            provenance.atomic_json(attempt/'provenance.json', record)
            if output.exists() or record_path.exists():
                raise ValueError('Output appeared during generation; refusing overwrite')
            shutil.copy2(temporary, output)
            provenance.atomic_json(record_path, record)
            result.update(status='generated', seconds=record['seconds'])
        except Exception as exc:
            result['error'] = str(exc)
        results.append(result)
        print(json.dumps(result), file=sys.stderr, flush=True)
    gpu.close()
    print(json.dumps({'results': results, 'failed': sum(r['status']=='failed' for r in results)}))
    return int(any(r['status']=='failed' for r in results))


if __name__ == '__main__':
    raise SystemExit(main())
