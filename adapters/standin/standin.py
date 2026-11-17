"""The stand-in adapter: no model, CPU only, the Python standard library only, the same output for the same input.

    python3 -I standin.py image  --prompt TEXT --seed N --width W --height H --output FILE.png
    python3 -I standin.py mesh   --image FILE.png --seed N --output FILE.glb
    python3 -I standin.py text   --prompt TEXT --seed N --output FILE.txt
    python3 -I standin.py review --image FILE.png --prompt BRIEF --seed N --output FILE.json

Each writes what a real adapter of its kind writes, shaped the same way, plus `identity.json` beside the output (the
model identity it reports):

    image   an RGB PNG of the asked size: a procedural drawing of the subject the prompt's words point to (a stringed
            instrument, a lantern, a book, a standing figure, a vessel, or a cut gem for anything else), centred on
            plain white, its proportions and palette varied by the seed and the prompt (standin_subjects.py)
    mesh    a closed solid raised from the image's silhouette and coloured from its pixels, as a binary glTF (.glb) with
            normals and vertex colours (standin_solid.py)
    text    a few plain lines that name the prompt and seed
    review  {"id", "score", "findings", "uncertainty"}, the shape of a local picture review; the score is from the
            image's hash, so it says nothing about the picture

Nothing is learned or downloaded: the pictures are drawn by code. The output tells a person straight away that no model
ran. The pipeline's later stages (tidy, matte, mesh clean-up, decimation, the shape gate) accept it, so a whole pipeline
runs on a computer with no model installed.
"""
import argparse
import hashlib
import json
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I does not add the script's folder
import standin_solid  # noqa: E402
import standin_subjects as subjects  # noqa: E402
from standin_paint import Canvas, dice  # noqa: E402

VERSION = 2


def seeded(*parts):
    """A stable 32-byte digest of PARTS (text or bytes)."""
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part if isinstance(part, bytes) else str(part).encode())
        digest.update(b"\0")
    return digest.digest()


def png(width, height, rows):
    """An 8-bit RGB PNG from ROWS (one bytes object of width*3 per row)."""
    def chunk(name, body):
        return struct.pack(">I", len(body)) + name + body + struct.pack(">I", zlib.crc32(name + body) & 0xFFFFFFFF)
    raw = b"".join(b"\0" + row for row in rows)
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")


def image(prompt, seed, width, height):
    """PNG bytes: a procedural drawing of the subject the prompt's words point to, centred on plain white."""
    canvas = Canvas(width, height)
    subjects.draw(canvas, subjects.family_for(prompt), dice(seeded("image", prompt, seed)))
    return png(width, height, canvas.rows())


def glb(points, normals, triangles, colours):
    """A binary glTF 2.0 file: one mesh, one primitive (positions, normals, vertex colours, uint32 indices). COLOURS is
    one (r, g, b) in 0..255 for the whole mesh, or one (r, g, b) in 0..1 per vertex."""
    vertex = b"".join(struct.pack("<3f", *p) for p in points)
    normal = b"".join(struct.pack("<3f", *n) for n in normals)
    if colours and isinstance(colours[0], (int, float)):  # one 0..255 colour for every vertex
        colours = [tuple(c / 255 for c in colours)] * len(points)
    tint = b"".join(struct.pack("<4f", *c, 1.0) for c in colours)
    index = b"".join(struct.pack("<3I", *t) for t in triangles)
    blobs, views, offset = [vertex, normal, tint, index], [], 0
    for blob in blobs:
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(blob)})
        offset += len(blob)
    count = len(points)
    lows = [min(p[i] for p in points) for i in range(3)]
    highs = [max(p[i] for p in points) for i in range(3)]
    document = {
        "asset": {"version": "2.0", "generator": f"generative-stage standin {VERSION}"},
        "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0, "name": "standin"}],
        "meshes": [{"name": "standin", "primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1, "COLOR_0": 2},
                                                       "indices": 3, "mode": 4}]}],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": count, "type": "VEC3", "min": lows, "max": highs},
            {"bufferView": 1, "componentType": 5126, "count": count, "type": "VEC3"},
            {"bufferView": 2, "componentType": 5126, "count": count, "type": "VEC4"},
            {"bufferView": 3, "componentType": 5125, "count": len(triangles) * 3, "type": "SCALAR"}],
        "bufferViews": views,
        "buffers": [{"byteLength": offset}],
    }
    text = json.dumps(document, separators=(",", ":")).encode()
    text += b" " * (-len(text) % 4)
    body = b"".join(blobs)
    body += b"\0" * (-len(body) % 4)
    total = 12 + 8 + len(text) + 8 + len(body)
    return (struct.pack("<4sII", b"glTF", 2, total) + struct.pack("<I4s", len(text), b"JSON") + text
            + struct.pack("<I4s", len(body), b"BIN\0") + body)


def mesh(image_bytes, seed):
    points, normals, triangles, colours = standin_solid.build(image_bytes)
    return glb(points, normals, triangles, colours)


def text(prompt, seed):
    return f"Stand-in text (no model ran).\nPrompt: {prompt}\nSeed: {seed}\n"


def review(image_bytes, ident, brief, seed):
    digest = seeded("review", image_bytes, brief, seed)
    return {"id": ident, "score": 1 + digest[0] % 5,
            "findings": [{"severity": "low", "evidence": "Stand-in review: no model looked at this image."}],
            "uncertainty": "The score comes from the image's hash, not from looking at it."}


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else data.encode())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    modes = parser.add_subparsers(dest="mode", required=True)
    for name in ("image", "mesh", "text", "review"):
        mode = modes.add_parser(name)
        mode.add_argument("--seed", type=int, required=True)
        mode.add_argument("--output", type=Path, required=True)
        if name in ("image", "text", "review"):
            mode.add_argument("--prompt", required=True)
        if name in ("mesh", "review"):
            mode.add_argument("--image", type=Path, required=True)
        if name == "image":
            mode.add_argument("--width", type=int, required=True)
            mode.add_argument("--height", type=int, required=True)
    args = parser.parse_args(argv)
    if args.mode == "image":
        if not (1 <= args.width <= 4096 and 1 <= args.height <= 4096):
            parser.error("width and height must be 1 to 4096")
        write(args.output, image(args.prompt, args.seed, args.width, args.height))
    elif args.mode == "mesh":
        write(args.output, mesh(args.image.read_bytes(), args.seed))
    elif args.mode == "text":
        write(args.output, text(args.prompt, args.seed))
    else:
        write(args.output, json.dumps(review(args.image.read_bytes(), args.image.stem, args.prompt, args.seed),
                                      indent=2) + "\n")
    identity = {"name": "standin", "version": VERSION, "mode": args.mode, "model": None}
    write(args.output.parent / "identity.json", json.dumps(identity, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
