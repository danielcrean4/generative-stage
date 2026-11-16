"""A project's exports folder: bundles written by the server, one folder per distinct content.

    <project folder>/exports/<export id>/manifest.json, assets/...

The export id is the first 16 hex digits of the manifest's sha256, so exporting the same state
with the same selection twice gives the same id and writes nothing new. Bundles are written into a
temporary folder beside the final one and renamed into place, so a half-written bundle is never
listed.
"""

import hashlib
import json
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from core.errors import NotFound
from core.world import World
from export.bundle import (
    MANIFEST,
    Selection,
    manifest_text,
    plan_bundle,
    since_from_manifest,
    write_bundle,
    write_zip,
)

FOLDER = "exports"
EXPORT_ID = re.compile(r"[0-9a-f]{16}")


def exports_root(world: World) -> Path:
    return world.project.root / FOLDER


def _folder(world: World, export_id: str) -> Path:
    folder = exports_root(world) / export_id
    if not EXPORT_ID.fullmatch(export_id) or not (folder / MANIFEST).is_file():
        raise NotFound(f"no export {export_id!r}", "export_not_found")
    return folder


def summary(export_id: str, manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": export_id,
        "selection": manifest["selection"],
        "entities": len(manifest["entities"]),
        "links": len(manifest["links"]),
        "assets": sum(len(e["assets"]) for e in manifest["entities"]),
        "removed": manifest.get("removed"),
    }


def manifest_of(world: World, export_id: str) -> dict[str, Any]:
    folder = _folder(world, export_id)
    return json.loads((folder / MANIFEST).read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def list_exports(world: World) -> list[dict[str, Any]]:
    root = exports_root(world)
    if not root.is_dir():
        return []
    found = [p.name for p in root.iterdir() if EXPORT_ID.fullmatch(p.name)]
    return [summary(name, manifest_of(world, name)) for name in sorted(found)]


def create_export(
    world: World,
    runs_root: Path,
    kinds: tuple[str, ...] = (),
    tags: tuple[str, ...] = (),
    since: str | None = None,
) -> dict[str, Any]:
    """Write a bundle for the selection (since = an earlier export's id) and return its summary."""
    previous = since_from_manifest(manifest_of(world, since)) if since is not None else None
    plan = plan_bundle(world, runs_root, Selection(kinds, tags, previous))
    export_id = hashlib.sha256(manifest_text(plan.manifest).encode("utf-8")).hexdigest()[:16]
    root = exports_root(world)
    final = root / export_id
    if not (final / MANIFEST).is_file():
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root, prefix=".writing-") as scratch:
            written = write_bundle(plan, Path(scratch) / "bundle")
            if final.exists():  # an earlier attempt left a folder without a manifest
                shutil.rmtree(final)
            written.rename(final)
    return summary(export_id, plan.manifest)


def zip_bytes(world: World, export_id: str) -> bytes:
    folder = _folder(world, export_id)
    with tempfile.TemporaryDirectory() as scratch:
        return write_zip(folder, Path(scratch) / "bundle.zip").read_bytes()
