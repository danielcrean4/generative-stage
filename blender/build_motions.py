# SPDX-License-Identifier: MIT OR GPL-3.0-or-later
"""Builds motion families into clip JSON files and checks every clip. Plain Python, no Blender.

    python3 blender/build_motions.py --motions <dir> [--motions <dir> ...] \\
        --manifest <file.json> --out <dir> [rig/clip ...]

A motion family is a module <family>.py in a motions folder with
    CLIPS:    {clip name: make(rig, params, rng) -> motion.curves.Clip}
    DEFAULTS: {clip name: {param: value}}
    EVENTS:   {clip name: [event names the clip must have]}   (optional)
It only shapes motion through the rig's roles, so it works on any rig that has them.

The manifest names the rigs (paths relative to the manifest) and which clips to make for each:
    {"rigs": {"biped": "rigs/biped.json"},
     "clips": [{"rig": "biped", "family": "locomotion_biped", "clips": ["idle", "walk"],
                "params": {"walk": {"stride": 0.4}}}]}

Each clip is seeded by "rig/clip", so a rebuild gives byte-identical files. Outputs:
    <out>/<rig>/<clip>.json
    <out>/build.json        what made these files, and every check's result
Exits non-zero if any clip fails a check.
"""
import argparse
import importlib
import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from motion import checks, rig as rigs  # noqa: E402  (needs the path above)

TRIPLE = re.compile(r"\[\s*([-\d.e]+),\s*([-\d.e]+),\s*([-\d.e]+)\s*\]")  # one [x, y, z] per line


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TRIPLE.sub(r"[\1, \2, \3]", json.dumps(data, indent=1)) + "\n")


def build(manifest_path: Path, motion_dirs: list[Path], out: Path, only: list[str]) -> bool:
    for d in motion_dirs:
        sys.path.insert(0, str(d.resolve()))
    manifest = json.loads(manifest_path.read_text())
    loaded = {name: rigs.load(manifest_path.parent / rel) for name, rel in manifest["rigs"].items()}
    results, ok = [], True
    for entry in manifest["clips"]:
        family = importlib.import_module(entry["family"])
        rig = loaded[entry["rig"]]
        for clip_name in entry["clips"]:
            key = f"{rig.name}/{clip_name}"
            if only and key not in only:
                continue
            params = dict(family.DEFAULTS.get(clip_name, {}))
            overrides = entry.get("params", {}).get(clip_name, {})
            unknown = sorted(set(overrides) - set(params))
            if unknown:
                raise SystemExit(f"{key}: {entry['family']} has no parameters {unknown}")
            params.update(overrides)
            clip = family.CLIPS[clip_name](rig, params, random.Random(key))
            clip.name = clip_name
            problems = checks.check(clip, getattr(family, "EVENTS", {}).get(clip_name, []))
            write_json(out / rig.name / f"{clip_name}.json", clip.to_dict())
            results.append({"clip": key, "family": entry["family"], "params": params, "problems": problems})
            print(f"{'OK  ' if not problems else 'FAIL'} {key}" + "".join(f"\n     {p}" for p in problems))
            ok = ok and not problems
    write_json(out / "build.json", {"manifest": manifest_path.name, "clips": results})
    return ok


def main() -> None:
    parser = argparse.ArgumentParser(prog="blender/build_motions.py")
    parser.add_argument("--motions", action="append", required=True, type=Path, help="folder of motion families (repeatable)")
    parser.add_argument("--manifest", required=True, type=Path, help="JSON: rigs and the clips to make")
    parser.add_argument("--out", required=True, type=Path, help="output folder")
    parser.add_argument("clip", nargs="*", help="rig/clip names to build (default: all)")
    args = parser.parse_args()
    if not build(args.manifest, args.motions, args.out, args.clip):
        sys.exit(1)


if __name__ == "__main__":
    main()
