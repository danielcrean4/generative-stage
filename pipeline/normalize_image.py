"""Crop an image to its subject and place it on a square canvas (tools interpreter: numpy, scipy, Pillow).

python normalize_image.py INPUT.png OUTPUT.png --config CONFIG.json --report REPORT.json

Config keys (all required, no defaults; see docs/normalisers.md):
  background_tolerance  EITHER this: 0..255, channel level at or above which border-connected pixels are
                        background (the near_white method; an image with real alpha uses its alpha instead)
  background            OR this: a background settings object, `capture.background` of a pipeline file
                        (pipeline/background_spec.py); with chroma_key the output alpha is the soft alpha
                        and the colours are despilled. Exactly one of the two keys.
  canvas_size           whole number of pixels, the output is canvas_size x canvas_size
  margin                whole pixels of empty border on every side; 2 * margin must be below canvas_size
  output_mode           "rgba" (alpha from the mask) or "flat" (subject over background_color)
  background_color      [r, g, b]; the flat background, and the colour under alpha 0 in rgba mode

The subject is scaled, keeping aspect, so its longer side fills the canvas minus the margins, then
centred. Edges are hard (the mask is thresholded), which keeps a rerun on the output stable.
Exits 2 on bad input or config.
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

TOOL = "normalize_image"
MASK_THRESHOLD = 127  # resampled mask values above this are subject
MAX_ALPHA = 255


def background(value):
    try:
        background_spec.parse(value)
    except background_spec.BackgroundError as exc:
        raise ValueError(str(exc))


EITHER = (("background_tolerance", "background"),)
SCHEMA = {"background_tolerance": common.channel, "background": background, "canvas_size": common.positive_int,
          "margin": common.non_negative_int, "output_mode": common.one_of("rgba", "flat"),
          "background_color": common.rgb}


def validate_geometry(config):
    if 2 * config["margin"] >= config["canvas_size"]:
        raise common.NormaliserError(f"{TOOL}: margin {config['margin']} leaves no room in canvas_size {config['canvas_size']}")


def background_of(config):
    """The background settings object a config asks for (the older tolerance key means near_white)."""
    if "background" in config:
        return background_spec.parse(config["background"])
    return background_spec.near_white(config["background_tolerance"])


def normalize(image, config):
    """Return (output PIL image, report body) for an RGB or RGBA PIL image."""
    separation = subject_mask.separate(image, background_of(config))
    rgb, subject = separation.rgb, separation.subject
    soft = config["output_mode"] == "rgba" and "background" in config and \
        config["background"]["method"] == background_spec.CHROMA_KEY
    if not subject.any():
        raise common.NormaliserError(f"{TOOL}: no subject found (the whole image reads as background)")
    ys, xs = np.nonzero(subject)
    y0, y1, x0, x1 = int(ys.min()), int(ys.max()) + 1, int(xs.min()), int(xs.max()) + 1
    height, width = subject.shape
    touched = bool(y0 == 0 or x0 == 0 or y1 == height or x1 == width)
    size, room = config["canvas_size"], config["canvas_size"] - 2 * config["margin"]
    scale = room / max(y1 - y0, x1 - x0)
    new_w, new_h = max(1, round((x1 - x0) * scale)), max(1, round((y1 - y0) * scale))
    crop_rgb = Image.fromarray(rgb[y0:y1, x0:x1])
    crop_mask = Image.fromarray(np.rint(separation.alpha[y0:y1, x0:x1] * MAX_ALPHA).astype(np.uint8) if soft
                                else subject[y0:y1, x0:x1].astype(np.uint8) * MAX_ALPHA)
    if (new_w, new_h) != crop_rgb.size:
        crop_rgb = crop_rgb.resize((new_w, new_h), Image.LANCZOS)
        crop_mask = crop_mask.resize((new_w, new_h), Image.LANCZOS)
    placed_alpha = np.asarray(crop_mask)
    placed = placed_alpha > MASK_THRESHOLD
    left, top = (size - new_w) // 2, (size - new_h) // 2
    canvas = np.empty((size, size, 3), np.uint8)
    canvas[:] = config["background_color"]
    mask = np.zeros((size, size), bool)
    mask[top:top + new_h, left:left + new_w] = placed
    window = canvas[top:top + new_h, left:left + new_w]
    visible = (placed_alpha > 0) if soft else placed  # soft edges keep their partly see-through pixels
    window[visible] = np.asarray(crop_rgb)[visible]
    if config["output_mode"] == "rgba":
        alpha = np.zeros((size, size), np.uint8)
        alpha[top:top + new_h, left:left + new_w] = placed_alpha if soft else placed.astype(np.uint8) * MAX_ALPHA
        out = Image.fromarray(np.dstack([canvas, alpha]), "RGBA")
    else:
        out = Image.fromarray(canvas, "RGB")
    report = {"input_size": [width, height], "subject_bbox": {"left": x0, "top": y0, "right": x1, "bottom": y1},
              "coverage": round(float(subject.mean()), 6), "scale": round(float(scale), 6),
              "touched_border": touched,
              "placed_bbox": {"left": left, "top": top, "right": left + new_w, "bottom": top + new_h},
              "output_coverage": round(float(mask.mean()), 6), "output_mode": config["output_mode"]}
    return out, report


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    config, config_sha = common.load_config(args.config, SCHEMA, TOOL, EITHER)
    validate_geometry(config)
    common.require_file(args.input, TOOL, "input image")
    try:
        image = Image.open(args.input)
        image.load()
    except (OSError, ValueError) as exc:
        raise common.NormaliserError(f"{TOOL}: cannot read image {args.input}: {exc}")
    if image.mode not in ("RGB", "RGBA"):
        raise common.NormaliserError(f"{TOOL}: image {args.input} is mode {image.mode}; only RGB and RGBA are accepted")
    out, report = normalize(image, config)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    out.save(args.output)
    report.update({"tool": TOOL, "config": config, "config_sha256": config_sha})
    common.write_report(args.report, report)
    return 0


if __name__ == "__main__":
    sys.exit(common.run(TOOL, main))
