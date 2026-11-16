"""Build the review sheet of a finished mesh (tools interpreter: numpy, trimesh, PIL).

python review_sheet.py FINISH_DIR IMAGE OUT.png --config CONFIG.json

FINISH_DIR is a mesh_finish output folder. The sheet (docs/gate_v2.md, "Review sheet") has the concept
image first, then the front, side, top and back views of the final mesh (decimate/mesh.glb), and under
them the verdict, every measure with its limit and margin (broken limits marked), the reasons, and
pieces and faces before -> after. mesh_finish.py writes it for every verdict as gate/review-sheet.png.

CONFIG is a finish config; only its `review_sheet` block and the contract's axes are read here. The
block holds every look and layout value (none has a default in code):
  render           the mesh_render style: size, supersample, margin, shading, background, surface, ambient, light
  gap, padding     pixels between tiles and around the sheet
  font_size, line_height   pixels (the font is Pillow's bundled one)
  sheet_background, text   colours [r, g, b]
  verdict_colours  {"pass": rgb, "review": rgb, "fail": rgb}, also used to mark each measure's outcome
parse() below is the one place that validates the block; mesh_finish.parse calls it.
Exit codes: 0 sheet written, 2 usage or config error.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mesh_io
import mesh_render
import normaliser_common as common
import normalize_mesh

TOOL = "review_sheet"
OUTCOMES = ("pass", "review", "fail")
BLOCK_SCHEMA = {"render": None, "gap": common.non_negative_int, "padding": common.non_negative_int,
                "font_size": common.positive_int, "line_height": common.positive_int,
                "sheet_background": common.rgb, "text": common.rgb, "verdict_colours": None}
TILES = ("concept",) + mesh_render.VIEWS
COLUMN_GAP_CHARS = 2    # column spacing in the measures table, in widths of the letter "n"


class ConfigError(ValueError):
    """The review_sheet block is missing a key or holds an invalid value (the message names file and key)."""


def parse(raw, source):
    """Validate the decoded `review_sheet` block; returns it. ConfigError names SOURCE and the key."""
    if not isinstance(raw, dict):
        raise ConfigError(f"{source}: review_sheet must be an object")
    for key in BLOCK_SCHEMA:
        if key not in raw:
            raise ConfigError(f"{source}: missing key review_sheet.{key}")
    for key in raw:
        if key not in BLOCK_SCHEMA:
            raise ConfigError(f"{source}: unknown key review_sheet.{key}")
    for key, check in BLOCK_SCHEMA.items():
        if check is None:
            continue
        try:
            check(raw[key])
        except ValueError as exc:
            raise ConfigError(f"{source}: review_sheet.{key} {exc}")
    try:
        mesh_render.check_style(raw["render"])
    except ValueError as exc:
        raise ConfigError(f"{source}: review_sheet.render {exc}")
    colours = raw["verdict_colours"]
    if not isinstance(colours, dict) or set(colours) != set(OUTCOMES):
        raise ConfigError(f"{source}: review_sheet.verdict_colours must hold exactly {', '.join(OUTCOMES)}")
    for name in OUTCOMES:
        try:
            common.rgb(colours[name])
        except ValueError as exc:
            raise ConfigError(f"{source}: review_sheet.verdict_colours.{name} {exc}")
    return raw


def _tile(image_array, size, background):
    tile = Image.new("RGB", (size, size), tuple(background))
    tile.paste(Image.fromarray(image_array), (0, 0))
    return tile


def _concept(path, size, background):
    """The concept image fitted into a square tile, aspect kept."""
    image = Image.open(path).convert("RGB")
    image.thumbnail((size, size))
    tile = Image.new("RGB", (size, size), tuple(background))
    tile.paste(image, ((size - image.width) // 2, (size - image.height) // 2))
    return tile


def _wrap(text, font, width):
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if line and font.getlength(trial) > width:
            lines.append(line)
            line = word
        else:
            line = trial
    return lines + [line] if line else lines


def _measure_rows(measures):
    """Rows of (name, value text, limit text, margin text, outcome), sorted by name (the saved report is sorted too)."""
    rows = []
    for name, m in sorted(measures.items()):
        key = m["limit_key"]
        sign = ">=" if key.startswith("min_") else "<="
        rows.append((name, f"{m['value']}", f"{sign} {key} {m['limit']}", f"{m['margin']:+.4f}", m["outcome"]))
    return rows


def build(image_path, mesh_path, finish, report, axes, config):
    """The sheet as a PIL image.

    FINISH is the finish.json dict, REPORT the gate's mesh-validation.json dict (None when the chain
    stopped early), MESH_PATH the final mesh (None then too), AXES = (up_axis, front_axis).
    """
    style, pad, gap = config["render"], config["padding"], config["gap"]
    size, colours, text = style["size"], config["verdict_colours"], tuple(config["text"])
    font = ImageFont.load_default(size=config["font_size"])
    tiles = [_concept(image_path, size, style["background"])]
    if mesh_path is None:
        tiles += [Image.new("RGB", (size, size), tuple(style["background"])) for _ in mesh_render.VIEWS]
    else:
        mesh = mesh_io.load_mesh(mesh_path, TOOL)
        vertices, faces = np.asarray(mesh.vertices, float), np.asarray(mesh.faces)
        scale = mesh_render.fit(vertices, size, style["margin"])
        for view in mesh_render.VIEWS:
            picture, _ = mesh_render.render(vertices, faces, view, *axes, style, mesh_io.vertex_colors(mesh), scale)
            tiles.append(_tile(picture, size, style["background"]))
    width = 2 * pad + len(tiles) * size + (len(tiles) - 1) * gap
    label_h = config["line_height"]
    # Text lines: (string, colour, x offset or None for column rows).
    lines = [(f"{finish['verdict'].upper()}", tuple(colours[finish["verdict"]]))]
    if report:
        cam = report["camera"]
        lines[0] = (f"{finish['verdict'].upper()}   profile {report['profile']}   camera yaw {cam['yaw']:g} elevation {cam['elevation']:g}",
                    tuple(colours[finish["verdict"]]))
    rows = _measure_rows(report["measures"]) if report else []
    spacing = COLUMN_GAP_CHARS * font.getlength("n")
    widths = [max(font.getlength(r[i]) for r in rows) if rows else 0 for i in range(4)]
    reasons = []
    for reason in finish["reasons"]:
        reasons += _wrap("- " + reason, font, width - 2 * pad)
    before, after = finish["before"], finish["after"]
    if before and after:
        counts = f"pieces {before['pieces']} -> {after['pieces']}   faces {before['faces']} -> {after['faces']}"
    elif after:  # the gate stage run alone: it sees only the shipped mesh
        counts = f"pieces {after['pieces']}   faces {after['faces']}"
    else:
        counts = "pieces and faces: not available, the chain stopped early"
    height = (2 * pad + size + label_h + gap + label_h * (1 + len(rows) + 1 + len(reasons) + 1))
    sheet = Image.new("RGB", (width, height), tuple(config["sheet_background"]))
    draw = ImageDraw.Draw(sheet)
    for i, (tile, name) in enumerate(zip(tiles, TILES)):
        x = pad + i * (size + gap)
        sheet.paste(tile, (x, pad))
        draw.text((x, pad + size), name, fill=text, font=font)
    y = pad + size + label_h + gap
    draw.text((pad, y), lines[0][0], fill=lines[0][1], font=font)
    y += label_h
    for name, value, limit, margin, outcome in rows:
        colour = tuple(colours[outcome])
        x = pad
        for cell, w in zip((name, value, limit, margin), widths):
            draw.text((x, y), cell, fill=colour if outcome != "pass" else text, font=font)
            x += w + spacing
        draw.text((x, y), outcome.upper() if outcome != "pass" else outcome, fill=colour, font=font)
        y += label_h
    y += label_h
    for line in reasons:
        draw.text((pad, y), line, fill=text, font=font)
        y += label_h
    draw.text((pad, y), counts, fill=text, font=font)
    return sheet


def from_finish_dir(finish_dir, image_path, axes, config):
    """Read FINISH_DIR (finish.json and the gate report) and build its sheet."""
    finish_dir = Path(finish_dir)
    finish = json.loads((finish_dir / "finish.json").read_text())
    outputs = finish["outputs"]
    report = json.loads((finish_dir / outputs["gate_report"]).read_text()) if outputs and "gate_report" in outputs else None
    mesh = finish_dir / outputs["mesh"] if outputs and "mesh" in outputs else None
    return build(image_path, mesh, finish, report, axes, config)


def load_config(path):
    """(review_sheet block, (up_axis, front_axis)) from a finish config file; ConfigError names file and key."""
    try:
        raw = json.loads(Path(path).read_bytes())
    except (OSError, ValueError) as exc:
        raise ConfigError(f"{path}: cannot read config: {exc}")
    if not isinstance(raw, dict) or "review_sheet" not in raw:
        raise ConfigError(f"{path}: missing key config.review_sheet")
    contract = raw.get("contract")
    axes = []
    for key in ("up_axis", "front_axis"):
        try:
            normalize_mesh.signed_axis(contract[key])
        except (TypeError, KeyError, ValueError) as exc:
            raise ConfigError(f"{path}: contract.{key} must be a signed axis such as \"+y\": {exc}")
        axes.append(contract[key])
    return parse(raw["review_sheet"], path), tuple(axes)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("finish_dir", type=Path)
    parser.add_argument("image", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    try:
        config, axes = load_config(args.config)
        common.require_file(args.image, TOOL, "concept image")
        common.require_file(args.finish_dir / "finish.json", TOOL, "finish.json")
        sheet = from_finish_dir(args.finish_dir, args.image, axes, config)
    except (ConfigError, common.NormaliserError) as exc:
        print(f"{TOOL}: {exc}", file=sys.stderr)
        return common.EXIT_BAD_INPUT
    args.out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
