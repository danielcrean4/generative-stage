"""Read a binary glTF (.glb) with the Python standard library: its JSON, its binary chunk and any accessor's values.

    document, binary = load(path)
    values = accessor(document, binary, index)     a list of tuples (or of numbers for SCALAR)
    data = pack(document, binary)                  the .glb bytes again (tests use it to write mutants)

Only what the rig gate needs: one buffer held in the file's own binary chunk, no sparse accessors, no data URIs.
Anything else is GlbError naming what is missing.
"""
import json
import struct
from pathlib import Path

COMPONENTS = {5120: "b", 5121: "B", 5122: "h", 5123: "H", 5125: "I", 5126: "f"}
WIDTH = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT2": 4, "MAT3": 9, "MAT4": 16}
NORMALISED = {5121: 255.0, 5123: 65535.0}


class GlbError(ValueError):
    """The file is not a .glb this reader handles; the message says why."""


def parse(data):
    """(document, binary chunk) of the .glb bytes DATA."""
    if len(data) < 20 or data[:4] != b"glTF":
        raise GlbError("not a binary glTF file (no 'glTF' header)")
    _, version, total = struct.unpack("<4sII", data[:12])
    if version != 2 or total > len(data):
        raise GlbError(f"glTF version {version}, length {total} of {len(data)} bytes: not a whole glTF 2.0 file")
    size, kind = struct.unpack("<I4s", data[12:20])
    if kind != b"JSON":
        raise GlbError("the first chunk is not JSON")
    document = json.loads(data[20:20 + size])
    binary = b""
    at = 20 + size
    if at + 8 <= total:
        size, kind = struct.unpack("<I4s", data[at:at + 8])
        if kind == b"BIN\0":
            binary = data[at + 8:at + 8 + size]
    return document, binary


def load(path):
    return parse(Path(path).read_bytes())


def accessor(document, binary, index):
    """The values of accessor INDEX: a list of tuples, or of numbers for a SCALAR. Normalised integers (weights)
    come back as floats from 0 to 1."""
    meta = document["accessors"][index]
    if "sparse" in meta or "bufferView" not in meta:
        raise GlbError(f"accessor {index}: sparse or bufferless accessors are not read")
    view = document["bufferViews"][meta["bufferView"]]
    if view.get("buffer", 0) != 0 or document["buffers"][0].get("uri"):
        raise GlbError(f"accessor {index}: data outside the file's binary chunk is not read")
    code, width, count = COMPONENTS[meta["componentType"]], WIDTH[meta["type"]], meta["count"]
    item = struct.calcsize("<" + code * width)
    stride = view.get("byteStride") or item
    start = view.get("byteOffset", 0) + meta.get("byteOffset", 0)
    if start + stride * (count - 1) + item > len(binary):
        raise GlbError(f"accessor {index}: runs past the end of the binary chunk")
    scale = NORMALISED.get(meta["componentType"]) if meta.get("normalized") else None
    values = []
    for i in range(count):
        one = struct.unpack_from("<" + code * width, binary, start + i * stride)
        if scale:
            one = tuple(v / scale for v in one)
        values.append(one[0] if width == 1 else one)
    return values


def pack(document, binary):
    """The .glb bytes of DOCUMENT and BINARY (padded as the format asks)."""
    text = json.dumps(document, separators=(",", ":")).encode()
    text += b" " * (-len(text) % 4)
    body = binary + b"\0" * (-len(binary) % 4)
    total = 12 + 8 + len(text) + (8 + len(body) if body else 0)
    out = struct.pack("<4sII", b"glTF", 2, total) + struct.pack("<I4s", len(text), b"JSON") + text
    return out + (struct.pack("<I4s", len(body), b"BIN\0") + body if body else b"")
