"""Lay an export bundle out as files a Godot project can load. Standard library only.

    python3 godot_import.py <bundle folder or .zip> <target folder inside a Godot project> [--res-prefix res://world]

Writes models/<kind>/<id>.glb, images/<kind>/<id>.png (other slots add _<slot>) and index.json.
Every copied file is checked against the sha256 the manifest records; a mismatch stops the import.
"""

import argparse
import hashlib
import json
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

FORMATS = (
    "generative-stage-bundle",
    "dramatis-fabrica-bundle",
)  # the bundle's id now and before the rename
FORMAT_VERSION = 1
FOLDERS = {"model/gltf-binary": ("models", ".glb"), "image/png": ("images", ".png")}
OTHER = ("files", "")


class ImportProblem(Exception):
    """The bundle cannot be laid out; the message says why."""


def _manifest(bundle: Path) -> dict[str, Any]:
    try:
        manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ImportProblem(f"{bundle}: no readable manifest.json ({error})") from error
    if manifest.get("format") not in FORMATS or manifest.get("format_version") != FORMAT_VERSION:
        raise ImportProblem(f"{bundle}: not a version {FORMAT_VERSION} {FORMATS[0]}")
    return manifest  # type: ignore[no-any-return]


def _inside(bundle: Path, relative: str) -> Path:
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts:
        raise ImportProblem(f"asset path {relative!r} leaves the bundle")
    return bundle.joinpath(*path.parts)


def target_name(kind: str, entity_id: str, slot: str, media_type: str, source: str) -> str:
    """Where one asset goes, relative to the target folder."""
    folder, suffix = FOLDERS.get(media_type, OTHER)
    suffix = suffix or PurePosixPath(source).suffix
    name = entity_id if slot == "main" else f"{entity_id}_{slot}"
    return f"{folder}/{kind}/{name}{suffix}"


def plan(
    manifest: dict[str, Any], res_prefix: str
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """The index.json document and, per target path, the asset entry it copies."""
    copies: dict[str, dict[str, Any]] = {}
    entities = []
    for entity in manifest["entities"]:
        files = {}
        for slot, asset in sorted(entity["assets"].items()):
            name = target_name(
                entity["kind"], entity["id"], slot, asset["media_type"], asset["path"]
            )
            copies[name] = asset
            files[slot] = f"{res_prefix.rstrip('/')}/{name}"
        entities.append(
            {
                "id": entity["id"],
                "kind": entity["kind"],
                "title": entity["title"],
                "revision": entity["revision"],
                "data": entity["data"],
                "files": files,
            }
        )
    index = {
        "project": manifest["project"],
        "entities": sorted(entities, key=lambda e: (e["kind"], e["id"])),
        "links": manifest["links"],
    }
    return index, copies


def import_bundle(bundle: Path, target: Path, res_prefix: str = "res://") -> dict[str, Any]:
    """Copy a bundle folder's assets into `target` (missing or empty) and write index.json."""
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise ImportProblem(f"{target} exists and is not an empty folder")
    index, copies = plan(_manifest(bundle), res_prefix)
    for name, asset in sorted(copies.items()):
        data = _inside(bundle, asset["path"]).read_bytes()
        if hashlib.sha256(data).hexdigest() != asset["sha256"]:
            raise ImportProblem(f"{asset['path']}: its sha256 does not match the manifest")
        out = target / name
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
    target.mkdir(parents=True, exist_ok=True)
    text = json.dumps(index, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    (target / "index.json").write_text(text, encoding="utf-8")
    return index


def import_any(source: Path, target: Path, res_prefix: str = "res://") -> dict[str, Any]:
    """A bundle folder, or a zip of one."""
    if source.is_dir():
        return import_bundle(source, target, res_prefix)
    with tempfile.TemporaryDirectory() as unpacked, zipfile.ZipFile(source) as archive:
        for name in archive.namelist():
            _inside(Path(unpacked), name)  # refuses entries that would leave the folder
        archive.extractall(unpacked)
        return import_bundle(Path(unpacked), target, res_prefix)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lay an export bundle out for a Godot project")
    parser.add_argument("bundle", type=Path, help="a bundle folder or .zip")
    parser.add_argument(
        "target", type=Path, help="a missing or empty folder inside the Godot project"
    )
    parser.add_argument("--res-prefix", default="res://", help="the target folder as a res:// path")
    args = parser.parse_args(argv)
    try:
        index = import_any(args.bundle, args.target, args.res_prefix)
    except ImportProblem as problem:
        print(f"godot_import: {problem}", file=sys.stderr)
        return 1
    print(f"Laid out {len(index['entities'])} entities in {args.target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
