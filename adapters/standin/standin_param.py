"""The stand-in render and measure adapters for parametric kinds: no model, standard library only, deterministic.

    python3 -I standin_param.py render  --row ROW.json --schema KIND.schema.json --output still.png
    python3 -I standin_param.py measure --row ROW.json --image still.png --output measure.json

render draws a 256 x 256 picture that shows the row's parameters, not a thing: one vertical bar per numeric parameter
(taller for a larger value inside its range) in the row's colour (grey when it has none), and one small square per
select or switch along the bottom. measure reads the picture back and writes {"numbers": {...}} where the numbers are
`ink_width_px`, `ink_height_px` (the box round everything not white), `ink_ratio` (the share of pixels that are not
white) and `bars` (how many bars). A game's own scripts follow the same command shape (docs/parametric.md).
"""
import argparse
import json
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from core import parameters  # noqa: E402

SIZE = 256
WHITE = (255, 255, 255)
GROUND = 230
BAR_WIDTH, BAR_GAP, BAR_LEFT, BAR_MIN, BAR_SPAN = 28, 8, 8, 20, 180
PIP = 12


def _png(pixels):
    raw = b"".join(b"\0" + bytes(c for px in row for c in px) for row in pixels)
    def chunk(tag, body):
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", SIZE, SIZE, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def _read(path):
    data = Path(path).read_bytes()
    pos, idat = 8, b""
    while pos < len(data):
        length, tag = struct.unpack(">I4s", data[pos:pos + 8])
        if tag == b"IHDR":
            width, height, depth, colour = struct.unpack(">IIBB", data[pos + 8:pos + 18])
        if tag == b"IDAT":
            idat += data[pos + 8:pos + 8 + length]
        pos += 12 + length
    if depth != 8 or colour not in (2, 6):
        raise ValueError("the stand-in measure reads 8-bit RGB or RGBA pictures")
    step, raw = (3 if colour == 2 else 4), zlib.decompress(idat)
    stride, rows, previous = width * step, [], bytearray(width * step)
    for y in range(height):
        base = y * (stride + 1)
        filt, line = raw[base], bytearray(raw[base + 1:base + 1 + stride])
        for i in range(stride):
            a = line[i - step] if i >= step else 0
            b, c = previous[i], (previous[i - step] if i >= step else 0)
            if filt == 1: line[i] = (line[i] + a) & 255
            elif filt == 2: line[i] = (line[i] + b) & 255
            elif filt == 3: line[i] = (line[i] + (a + b) // 2) & 255
            elif filt == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        rows.append([tuple(line[x * step:x * step + 3]) for x in range(width)])
        previous = line
    return rows


def render(row, schema):
    model = parameters.model(schema)
    pixels = [[WHITE] * SIZE for _ in range(SIZE)]
    fields = [f for f in parameters.active(model, row) if f["name"] in row]  # an optional field may be left out
    colour = next((row[f["name"]] for f in fields if f["type"] == "colour"), "#808080")
    rgb = tuple(int(colour[i:i + 2], 16) for i in (1, 3, 5))
    x = BAR_LEFT
    for f in (f for f in fields if f["type"] in ("number", "integer")):
        if x + BAR_WIDTH > SIZE:
            break
        share = (row[f["name"]] - f["min"]) / ((f["max"] - f["min"]) or 1)
        for y in range(GROUND - BAR_MIN - round(BAR_SPAN * share), GROUND):
            for px in range(x, x + BAR_WIDTH):
                pixels[y][px] = rgb
        x += BAR_WIDTH + BAR_GAP
    x = BAR_LEFT
    for f in (f for f in fields if f["type"] in ("enum", "boolean")):
        if x + PIP > SIZE:
            break
        index = f["values"].index(row[f["name"]]) / max(len(f["values"]) - 1, 1) if f["type"] == "enum" else float(row[f["name"]])
        shade = round(200 - 160 * index)
        for y in range(GROUND + 14, GROUND + 14 + PIP):
            for px in range(x, x + PIP):
                pixels[y][px] = (shade, shade, shade)
        x += PIP + 6
    return _png(pixels)


def measure(row, image):
    pixels = _read(image)
    xs, ys, ink = [], [], 0
    for y, line in enumerate(pixels):
        for x, px in enumerate(line):
            if px != WHITE:
                ink += 1
                xs.append(x)
                ys.append(y)
    numbers = {"ink_width_px": (max(xs) - min(xs) + 1) if xs else 0, "ink_height_px": (max(ys) - min(ys) + 1) if ys else 0,
               "ink_ratio": round(ink / (len(pixels) * len(pixels[0])), 6)}
    return {"numbers": numbers}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("render", "measure"))
    parser.add_argument("--row", type=Path, required=True)
    parser.add_argument("--schema", type=Path)
    parser.add_argument("--image", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    row = json.loads(args.row.read_text())
    if args.command == "render":
        if args.schema is None:
            parser.error("render needs --schema")
        args.output.write_bytes(render(row, json.loads(args.schema.read_text())))
    else:
        if args.image is None:
            parser.error("measure needs --image")
        args.output.write_text(json.dumps(measure(row, args.image), indent=1) + "\n")
    (args.output.parent / "identity.json").write_text(json.dumps({"name": "standin-param", "version": 1}) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
