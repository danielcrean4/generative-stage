# SPDX-License-Identifier: MIT OR GPL-3.0-or-later
"""Palette files: named colour slots that every generated asset is painted from.

Pure Python (no Blender), so it can be loaded and checked anywhere. A palette is JSON:

    {
      "colours":   {"leaf": [[0.30, 0.50, 0.22], ...], ...},   # sRGB, 0..1, as a colour picker shows
      "roughness": {"glass": 0.1},                             # per slot; default DEFAULT_ROUGHNESS
      "metallic":  {"metal": 0.8},                             # per slot; default 0
      "mended":    0.4                                         # chance of optional repair details
    }

Swapping the palette file restyles every family without touching its code.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_ROUGHNESS = 0.85  # matte, like painted plaster or wood

RGB = tuple[float, float, float]


@dataclass(frozen=True)
class Palette:
    colours: dict[str, list[RGB]]
    roughness: dict[str, float] = field(default_factory=dict)
    metallic: dict[str, float] = field(default_factory=dict)
    mended: float = 0.0
    sha256: str = ""

    def colour(self, key: str, index: int = 0) -> RGB:
        return self.colours[key][index]


def load(path: str | Path) -> Palette:
    """Reads and checks a palette file. Raises ValueError naming the first problem."""
    raw = Path(path).read_bytes()
    data = json.loads(raw)
    colours = data.get("colours")
    if not isinstance(colours, dict) or not colours:
        raise ValueError(f"{path}: 'colours' must be a non-empty object")
    parsed: dict[str, list[RGB]] = {}
    for key, entries in colours.items():
        if not isinstance(entries, list) or not entries:
            raise ValueError(f"{path}: colours.{key} must be a non-empty list")
        parsed[key] = [_rgb(path, key, entry) for entry in entries]
    for table in ("roughness", "metallic"):
        for key, value in data.get(table, {}).items():
            if key not in parsed:
                raise ValueError(f"{path}: {table}.{key} names no colour slot")
            _unit(path, f"{table}.{key}", value)
    mended = data.get("mended", 0.0)
    _unit(path, "mended", mended)
    return Palette(
        colours=parsed,
        roughness=dict(data.get("roughness", {})),
        metallic=dict(data.get("metallic", {})),
        mended=float(mended),
        sha256=hashlib.sha256(raw).hexdigest(),
    )


def to_linear(rgb: RGB) -> RGB:
    """sRGB (what a colour picker shows) to the linear values Blender's shaders take."""
    r, g, b = (c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb)
    return (r, g, b)


def _rgb(path: str | Path, key: str, entry: object) -> RGB:
    if not (isinstance(entry, list) and len(entry) == 3):
        raise ValueError(f"{path}: colours.{key} entries must be [r, g, b]")
    for c in entry:
        _unit(path, f"colours.{key}", c)
    return (float(entry[0]), float(entry[1]), float(entry[2]))


def _unit(path: str | Path, where: str, value: object) -> None:
    if not isinstance(value, (int, float)) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{path}: {where} must be a number from 0 to 1")
