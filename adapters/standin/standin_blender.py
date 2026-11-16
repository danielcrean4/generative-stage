"""The rig and motion stand-ins: no model, CPU only; each runs one script in background Blender (Python standard
library here, `blender` on PATH; the entries require the host's `blender` capability).

    python3 -I standin_blender.py rig    --mesh IN.glb --profile RIG.json --output rigged.glb --out-dir DIR
    python3 -I standin_blender.py motion --mesh rigged.glb --rig rig.json --clips idle,walk \\
        --manifest MANIFEST.json --motions DIR --output animated.glb --out-dir DIR

rig     fits the rig profile to the mesh and weights it (blender/rig_standin.py): writes `rigged.glb`, the fitted
        profile `rig.json` and `rig-report.json` into DIR
motion  makes the named procedural clips for the fitted profile and keys them on the rigged mesh
        (blender/animate_standin.py): writes `animated.glb` and `clips.json` into DIR

Both write `identity.json` beside the output: the stand-in's name and version, the Blender version, and the sha256 of
the scripts that ran. Without Blender they stop with a sentence that says so (exit 2).

The runner's reuse key hashes this file, the profile and the manifest (the entries' fixed arguments), not the Blender
scripts it runs: bump VERSION when a change to those scripts or to a motion family should stop old outputs being reused.
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

VERSION = 1
REPO = Path(__file__).resolve().parents[2]
BLENDER_DIR = REPO / "blender"
SCRIPTS = {"rig": BLENDER_DIR / "rig_standin.py", "motion": BLENDER_DIR / "animate_standin.py"}
HELPERS = ("rigging.py", "kit.py", "motion/rig.py", "motion/fit.py", "motion/curves.py", "motion/ik.py",
           "motion/checks.py")  # the scripts' own imports, hashed into the reported identity
TIMEOUT = 600


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def blender_version(program):
    result = subprocess.run([program, "--version"], capture_output=True, text=True, timeout=60, check=False)
    first = (result.stdout or "").splitlines()[:1]
    return first[0].strip() if first else "unknown"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    modes = parser.add_subparsers(dest="mode", required=True)
    for name in SCRIPTS:
        mode = modes.add_parser(name)
        mode.add_argument("--mesh", type=Path, required=True)
        mode.add_argument("--output", type=Path, required=True)
        mode.add_argument("--out-dir", type=Path, required=True)
        if name == "rig":
            mode.add_argument("--profile", type=Path, required=True)
        else:
            for key in ("rig", "manifest", "motions"):
                mode.add_argument(f"--{key}", type=Path, required=True)
            mode.add_argument("--clips", required=True)
    args = parser.parse_args(argv)
    program = shutil.which("blender")
    if program is None:
        print("the rig and motion stand-ins need Blender: install it and put `blender` on PATH "
              "(https://www.blender.org); nothing was made", file=sys.stderr)
        return 2
    args.out_dir.mkdir(parents=True, exist_ok=True)
    if args.mode == "rig":
        extra = ["--mesh", args.mesh, "--profile", args.profile, "--output", args.output,
                 "--rig-out", args.out_dir / "rig.json", "--report", args.out_dir / "rig-report.json"]
    else:
        extra = ["--mesh", args.mesh, "--rig", args.rig, "--clips", args.clips, "--manifest", args.manifest,
                 "--motions", args.motions, "--output", args.output, "--report", args.out_dir / "clips.json"]
    command = [program, "--background", "--factory-startup", "--python-exit-code", "1",
               "--python", SCRIPTS[args.mode], "--", *extra]
    result = subprocess.run([str(part) for part in command], timeout=TIMEOUT, check=False)
    if result.returncode or not args.output.is_file():
        print(f"Blender's {args.mode} stand-in failed (exit {result.returncode}); its log is above", file=sys.stderr)
        return 1
    scripts = {name: digest(BLENDER_DIR / name) for name in (SCRIPTS[args.mode].name, *HELPERS)}
    if args.mode == "motion":  # the families that made the clips
        scripts.update({f"motions/{path.name}": digest(path) for path in sorted(args.motions.glob("*.py"))})
    identity = {"name": "standin", "version": VERSION, "mode": args.mode, "model": None,
                "blender": blender_version(program), "scripts_sha256": scripts}
    (args.output.parent / "identity.json").write_text(json.dumps(identity, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
