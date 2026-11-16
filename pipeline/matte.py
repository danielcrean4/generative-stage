"""Subject matte: RGB(A) image in, RGBA PNG and matte.json out (tools interpreter).

python matte.py IMAGE --out DIR [--method border-flood] [--tolerance N | --background FILE.json] [--allow-border]
--tolerance N is the near_white background with that channel level. --background FILE.json holds a
background settings object (pipeline/background_spec.py; `capture.background` of a pipeline file); with
chroma_key the matte.png alpha is the soft alpha and the colours are despilled, with no extra erosion.
Always writes matte.json first; exits 1 with a one-line reason when a check fails.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).resolve().parent))
import background_spec
import gate_settings
import subject_mask

EXIT_CHECK_FAILED = 1
EXIT_USAGE = 2
MAX_ALPHA = 255


def border_flood(image, args):
    """Separation by args.background; near_white also erodes the subject by one pixel (the fringe)."""
    separation = subject_mask.separate(image, args.background)
    if args.background["method"] == background_spec.NEAR_WHITE:
        subject = subject_mask.erode_subject(separation.subject)
        return subject_mask.Separation(subject, subject.astype(np.float32), separation.rgb)
    return separation


METHODS = {"border-flood": border_flood}  # a later method is one more entry


def analyse(subject, args):
    """Measures and failure reasons for a subject mask."""
    height, width = subject.shape
    count = int(subject.sum())
    report = {"image_size": [width, height], "subject_bbox": None, "subject_share": count / (width * height),
              "component_count": 0, "largest_component_share": 0.0, "border_contact": [], "reasons": []}
    if not count:
        report["reasons"].append("no subject found")
        return report
    ys, xs = np.nonzero(subject)
    report["subject_bbox"] = [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]
    labels, report["component_count"] = ndimage.label(subject)
    report["largest_component_share"] = float(np.bincount(labels[subject]).max() / count)
    edges = {"top": subject[0], "bottom": subject[-1], "left": subject[:, 0], "right": subject[:, -1]}
    report["border_contact"] = [name for name, strip in edges.items() if strip.any()]
    reasons = report["reasons"]
    if report["largest_component_share"] < args.min_largest_share:
        reasons.append(f"largest subject component holds {report['largest_component_share']:.3f} of the subject, "
                       f"below {args.min_largest_share}")
    if not args.min_coverage <= report["subject_share"] <= args.max_coverage:
        reasons.append(f"subject covers {report['subject_share']:.3f} of the frame, outside "
                       f"{args.min_coverage}..{args.max_coverage}")
    if report["border_contact"] and not args.allow_border:
        reasons.append("subject touches the image border (" + ", ".join(report["border_contact"]) + ")")
    return report


def main():
    d = gate_settings.MATTE_DEFAULTS
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("image", type=Path)
    parser.add_argument("--out", type=Path, required=True, help="directory for matte.png and matte.json")
    parser.add_argument("--method", choices=sorted(METHODS), default="border-flood")
    how = parser.add_mutually_exclusive_group()
    how.add_argument("--tolerance", type=int, default=d["tolerance"], help="near_white channel level")
    how.add_argument("--background", type=Path, help="JSON background settings object (near_white or chroma_key)")
    parser.add_argument("--min-largest-share", type=float, default=d["min_largest_share"])
    parser.add_argument("--min-coverage", type=float, default=d["min_coverage"])
    parser.add_argument("--max-coverage", type=float, default=d["max_coverage"])
    parser.add_argument("--allow-border", action="store_true")
    args = parser.parse_args()
    try:
        gate_settings.matte_settings({"tolerance": args.tolerance, "min_largest_share": args.min_largest_share,
                                      "min_coverage": args.min_coverage, "max_coverage": args.max_coverage})
        if args.background:
            try:
                args.background = background_spec.parse(json.loads(args.background.read_text()))
            except background_spec.BackgroundError as exc:
                raise ValueError(f"background {args.background}: {exc}")
        else:
            args.background = background_spec.near_white(args.tolerance)
        data = args.image.read_bytes()
        image = Image.open(args.image)  # kept as it is: a real alpha (the tidied image has one) decides the subject, see subject_mask.separate
        image.load()
    except (ValueError, OSError) as exc:
        print(f"matte: {exc}", file=sys.stderr)
        return EXIT_USAGE
    separation = METHODS[args.method](image, args)
    subject = separation.subject
    report = {"method": args.method, "background": args.background, "input_sha256": hashlib.sha256(data).hexdigest(),
              **analyse(subject, args)}
    if args.background["method"] == background_spec.NEAR_WHITE:
        report["tolerance"] = args.background["tolerance"]
    report["passed"] = not report["reasons"]
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "matte.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    alpha = np.rint(separation.alpha * MAX_ALPHA).astype(np.uint8)
    Image.fromarray(np.dstack([separation.rgb, alpha]), "RGBA").save(args.out / "matte.png")
    if report["reasons"]:
        print("matte failed: " + "; ".join(report["reasons"]), file=sys.stderr)
        return EXIT_CHECK_FAILED
    return 0


if __name__ == "__main__":
    sys.exit(main())
