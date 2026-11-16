"""Stack the review sheets of a seed batch into one labelled contact sheet (tools interpreter: Pillow).

python batch_sheet.py BATCH.json OUT.png --root OUT_ROOT --config CONFIG.json

BATCH.json is the file pipeline/pipeline_batch.py writes: one row per seed, each with `seed`, `status` (`generated`,
`review`, `failed` or `error`), `verdict` (pass, review, fail or null), `reasons`, `review_sheet` (a path relative
to OUT_ROOT, or null when the seed died before a sheet existed) and `error`. The output has a title line, then
for each seed a label line (the seed and its verdict, in the verdict's colour from the config) and that seed's
review sheet under it. A seed with no sheet gets its label and the reason in place of a picture, so a dead seed
is never missing from the picking sheet. CONFIG is any JSON file with a `review_sheet` block (look: fonts,
colours, gaps; validated by review_sheet.parse, no defaults here). Exit codes: 0 written, 2 usage or config error.
"""
import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
import normaliser_common as common
import review_sheet

TOOL = "batch_sheet"
LABEL_OF_STATUS = {"generated": "pass", "review": "review", "failed": "fail", "error": "fail"}  # status -> verdict colour name


def label(row):
    """The label line of one seed: the seed and its outcome in words."""
    outcome = (row["verdict"] or "no verdict").upper() if row["status"] != "error" else "ERROR"
    text = f"seed {row['seed']}   {outcome}"
    reasons = row["error"] if row["status"] == "error" else "; ".join(row["reasons"] or [])
    return f"{text}   {reasons}" if reasons else text


def build(batch, root, config):
    """The stacked sheet as a PIL image."""
    pad, gap = config["padding"], config["gap"]
    font = ImageFont.load_default(size=config["font_size"])
    line = config["line_height"]
    colours = config["verdict_colours"]
    blocks = []  # (label text, colour, picture or None)
    for row in batch["rows"]:
        sheet = root / row["review_sheet"] if row["review_sheet"] else None
        picture = Image.open(sheet).convert("RGB") if sheet and sheet.is_file() else None
        blocks.append((label(row), tuple(colours[LABEL_OF_STATUS[row["status"]]]), picture))
    title = f"{batch['subject']} / {batch['style']}   seeds {', '.join(str(r['seed']) for r in batch['rows'])}"
    width = 2 * pad + max([int(font.getlength(title))] + [picture.width for _, _, picture in blocks if picture is not None]
                          + [int(font.getlength(text)) for text, _, _ in blocks])
    height = 2 * pad + line + sum(gap + line + (picture.height if picture is not None else 0) for _, _, picture in blocks)
    canvas = Image.new("RGB", (width, height), tuple(config["sheet_background"]))
    draw = ImageDraw.Draw(canvas)
    y = pad
    draw.text((pad, y), title, fill=tuple(config["text"]), font=font)
    y += line
    for text, colour, picture in blocks:
        y += gap
        draw.text((pad, y), text, fill=colour, font=font)
        y += line
        if picture is not None:
            canvas.paste(picture, (pad, y))
            y += picture.height
    return canvas


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("batch", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    try:
        raw = json.loads(args.config.read_bytes())
        if not isinstance(raw, dict) or "review_sheet" not in raw:
            raise review_sheet.ConfigError(f"{args.config}: missing key review_sheet")
        config = review_sheet.parse(raw["review_sheet"], args.config)
        common.require_file(args.batch, TOOL, "batch file")
        batch = json.loads(args.batch.read_text())
        if not batch.get("rows"):
            raise common.NormaliserError(f"{TOOL}: {args.batch} has no rows")
        sheet = build(batch, args.root, config)
    except (review_sheet.ConfigError, common.NormaliserError, OSError, ValueError, KeyError) as exc:
        print(f"{TOOL}: {exc}", file=sys.stderr)
        return common.EXIT_BAD_INPUT
    args.out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
