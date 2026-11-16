"""Which pipelines serve which kinds of record in a project: the project's `generation.json`, with the tool's defaults when
the file is absent (authoring/offered.json, `entity_kinds`).

    {"version": 1, "serves": {"<record kind>": ["<pipeline id>", ...]}}

A kind listed under `serves` is served by exactly the pipelines listed, in that order, in place of the tool's defaults for that
kind; a kind not listed keeps the defaults. So a game's own kinds (any kind the project defines) can offer the concept and icon
pipelines, or a custom one, without touching the tool. A pipeline id must be one the tool offers; a wrong file is
refused with `generation.json: key 'serves.<kind>': <problem>` and the project's Generate panel says so.
"""

import json
from pathlib import Path
from typing import Any

from authoring.offered import Offer, offers
from core.errors import BadProjectFiles

FILE = "generation.json"


def _fail(root: Path, key: str, problem: str) -> BadProjectFiles:
    return BadProjectFiles(f"{root / FILE}: key '{key}': {problem}", "bad_generation_file")


def serves(root: Path) -> dict[str, tuple[str, ...]]:
    """The record kinds the project says pipelines serve, each with its pipeline ids; empty when there is no file."""
    file = root / FILE
    if not file.is_file():
        return {}
    try:
        raw: Any = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise BadProjectFiles(
            f"{file}: cannot read as JSON ({error})", "bad_generation_file"
        ) from error
    if not isinstance(raw, dict) or set(raw) - {"version", "serves"}:
        raise _fail(root, "", "expected an object with the keys version and serves")
    if raw.get("version") != 1:
        raise _fail(root, "version", "expected 1")
    given = raw.get("serves", {})
    if not isinstance(given, dict):
        raise _fail(root, "serves", "expected an object of record kind -> list of pipeline ids")
    found: dict[str, tuple[str, ...]] = {}
    for kind, ids in given.items():
        key = f"serves.{kind}"
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
            raise _fail(root, key, "expected a list of pipeline ids")
        unknown = [i for i in ids if i not in offers()]
        if unknown:
            raise _fail(
                root,
                key,
                f"no pipeline {unknown[0]!r} (the tool offers: {', '.join(sorted(offers()))})",
            )
        found[kind] = tuple(dict.fromkeys(ids))
    return found


def offered_for(root: Path | None, kind: str | None) -> list[Offer]:
    """The pipelines that serve KIND in the project at ROOT (all of them when KIND is None), in the project's order for a
    kind it lists, else the tool's. With no ROOT, the tool's defaults."""
    chosen = serves(root) if root is not None else {}
    if kind is not None and kind in chosen:
        return [offers()[i] for i in chosen[kind]]
    return [o for o in offers().values() if kind is None or o.serves(kind)]
