"""Keep the top share of a subject's height and cut the rest away (tools interpreter: numpy, scipy, Pillow).

python crop_image.py INPUT.png OUTPUT.png --config CONFIG.json --report REPORT.json

Config keys (all required, no defaults; see docs/head_pipeline.md):
  background  a background settings object, `capture.background` of a pipeline file (pipeline/background_spec.py);
              it says which pixels are subject, so the cut is measured on the subject, not on the canvas
  keep_share  above 0 up to 1: the share of the subject's own height kept, measured from its top row. It is
              a share of the subject, not a pixel count, so it follows how high or low the subject sits

The image keeps its width; rows below the cut go. A cut through the subject leaves it touching the bottom
edge (the next matte stage must allow border contact). An image with no subject is an error, never copied
through. Exits 2 on bad input or config.
"""
import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import background_spec
import normaliser_common as common
import subject_mask

TOOL = "crop_image"


def background(value):
    try:
        background_spec.parse(value)
    except background_spec.BackgroundError as exc:
        raise ValueError(str(exc))


def keep_share(value):
    if type(value) not in (int, float) or not 0 < value <= 1:
        raise ValueError("must be a number above 0 and at most 1")


SCHEMA = {"background": background, "keep_share": keep_share}


def crop(image, config):
    """Return (cropped PIL image, report body)."""
    subject = subject_mask.separate(image, config["background"]).subject
    rows = np.nonzero(subject.any(axis=1))[0]
    if not len(rows):
        raise common.NormaliserError(f"{TOOL}: no subject found (the whole image reads as background)")
    top, bottom = int(rows.min()), int(rows.max())
    cut = min(image.height, int(top + config["keep_share"] * (bottom - top)))
    return image.crop((0, 0, image.width, cut)), {"input_size": [image.width, image.height], "subject_rows": [top, bottom],
                                                 "kept_rows": [0, cut], "output_size": [image.width, cut]}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    config, config_sha = common.load_config(args.config, SCHEMA, TOOL)
    common.require_file(args.input, TOOL, "input image")
    try:
        image = Image.open(args.input)
        image.load()
    except (OSError, ValueError) as exc:
        raise common.NormaliserError(f"{TOOL}: cannot read image {args.input}: {exc}")
    if image.mode not in ("RGB", "RGBA"):
        raise common.NormaliserError(f"{TOOL}: image {args.input} is mode {image.mode}; only RGB and RGBA are accepted")
    out, report = crop(image, config)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    out.save(args.output)
    report.update({"tool": TOOL, "config": config, "config_sha256": config_sha})
    common.write_report(args.report, report)
    return 0


if __name__ == "__main__":
    sys.exit(common.run(TOOL, main))
