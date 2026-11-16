"""A dummy image adapter: the worked example of docs/adapters.md. No model; the Python standard library only.

    python3 -I dummy_image.py --prompt TEXT --seed N --width W --height H --output FILE.png

It does what an image adapter must do and nothing else: it writes an RGB PNG of the asked size to --output (a flat
colour taken from the prompt and the seed, so the same call gives the same file), writes `identity.json` beside it
(the identity it reports), prints the optional timing line, and exits 0. Any problem is one line on stderr and exit 1.
Replace the body of `make` with a call to your model and keep the rest.
"""

import argparse
import hashlib
import json
import struct
import sys
import time
import zlib
from pathlib import Path

NAME, VERSION = "dummy-image", 1


def png(width, height, rgb):
    """An 8-bit RGB PNG of one colour."""

    def chunk(kind, body):
        return (
            struct.pack(">I", len(body))
            + kind
            + body
            + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
        )

    row = b"\0" + bytes(rgb) * width
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(row * height, 6))
        + chunk(b"IEND", b"")
    )


def make(prompt, seed, width, height):
    """The picture as PNG bytes. A real adapter loads its model here and draws PROMPT with SEED."""
    digest = hashlib.sha256(f"{prompt}\0{seed}".encode()).digest()
    return png(width, height, [60 + digest[i] % 140 for i in range(3)])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--height", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if not (16 <= args.width <= 4096 and 16 <= args.height <= 4096):
        print(f"dummy-image: size {args.width}x{args.height} is outside 16..4096", file=sys.stderr)
        return 1
    started = time.monotonic()
    loaded = time.monotonic()  # a real adapter loads its weights between these two lines
    args.output.write_bytes(make(args.prompt, args.seed, args.width, args.height))
    done = time.monotonic()
    (args.output.parent / "identity.json").write_text(
        json.dumps({"name": NAME, "version": VERSION}) + "\n"
    )
    print(f"load {loaded - started:.2f}s, generate {done - loaded:.2f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
