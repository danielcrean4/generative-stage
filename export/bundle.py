"""Write a project's entities, links and chosen assets as an export bundle (docs/export_bundle.md).

    bundle/manifest.json                         what the bundle holds (manifest.schema.json)
    bundle/assets/<kind>/<entity id>/<slot><ext> each chosen asset, copied byte for byte

The same project state and selection always give the same bytes: no export time is written,
entities, links and keys are sorted, and the zip has a fixed entry order and fixed timestamps.
Every manifest is checked against the shipped schema before anything is written.
"""

import hashlib
import json
import shutil
import zipfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from core.errors import Conflict, Invalid
from core.world import World
from export.provenance import Provenance, read_provenance

# The format id written into every manifest.
FORMAT = "generative-stage-bundle"
FORMAT_VERSION = 1
MANIFEST = "manifest.json"
ASSETS = "assets"
SCHEMA_FILE = Path(__file__).parent / "manifest.schema.json"
MEDIA_TYPES = {
    ".glb": "model/gltf-binary",
    ".gltf": "model/gltf+json",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".json": "application/json",
}
ZIP_TIME = (1980, 1, 1, 0, 0, 0)  # the earliest a zip can hold; the same for every entry


@dataclass(frozen=True)
class Selection:
    """Which entities go in. Empty `kinds` or `tags` means no filter; `since` (entity id to
    revision, read from an earlier manifest) keeps only new entities and changed revisions."""

    kinds: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    since: Mapping[str, int] | None = None

    def describe(self) -> dict[str, Any]:
        return {
            "kinds": sorted(self.kinds),
            "tags": sorted(self.tags),
            "since": dict(sorted(self.since.items())) if self.since is not None else None,
        }


@dataclass(frozen=True)
class Plan:
    """A manifest and the files to copy into the bundle: bundle path -> source file."""

    manifest: dict[str, Any]
    files: Mapping[str, Path] = field(default_factory=dict)


def since_from_manifest(manifest: object) -> dict[str, int]:
    """The entity revisions an earlier bundle held, for a changed-since export."""
    validate_manifest(manifest)
    assert isinstance(manifest, dict)
    return {entity["id"]: entity["revision"] for entity in manifest["entities"]}


def validate_manifest(manifest: object) -> None:
    """Raise Invalid naming the first place the manifest breaks the shipped schema."""
    schema = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema).iter_errors(manifest), key=lambda e: list(e.absolute_path)
    )
    if errors:
        error = errors[0]
        pointer = "".join(f"/{part}" for part in error.absolute_path) or "/"
        raise Invalid(f"manifest {pointer}: {error.message}", "bad_manifest", pointer)


def _tags(world: World, entity: Mapping[str, Any]) -> list[str]:
    kind = world.catalogue.kinds.get(entity["kind"])
    if kind is None or kind.tags_field is None:
        return []
    value = entity["data"].get(kind.tags_field, [])
    return [str(tag) for tag in value] if isinstance(value, list) else []


def _selected(world: World, selection: Selection) -> list[dict[str, Any]]:
    for kind in selection.kinds:
        if kind not in world.catalogue.kinds:
            known = ", ".join(world.catalogue.kinds)
            raise Invalid(f"/kinds: no kind {kind!r} (kinds: {known})", "unknown_kind", "/kinds")
    chosen = []
    for entity in world.list_entities():
        if selection.kinds and entity["kind"] not in selection.kinds:
            continue
        if selection.tags and not set(selection.tags) & set(_tags(world, entity)):
            continue
        if selection.since is not None and selection.since.get(entity["id"]) == entity["revision"]:
            continue
        chosen.append(entity)
    return sorted(chosen, key=lambda e: e["id"])


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _asset(kind: str, entity_id: str, slot: str, found: Provenance) -> tuple[str, dict[str, Any]]:
    suffix = found.file.suffix.lower()
    path = f"{ASSETS}/{kind}/{entity_id}/{slot}{suffix}"
    return path, {
        "path": path,
        "media_type": MEDIA_TYPES.get(suffix, "application/octet-stream"),
        "sha256": _sha256(found.file),
        "bytes": found.file.stat().st_size,
        "provenance": found.record,
    }


def _links(world: World, exported: Iterable[str]) -> list[dict[str, Any]]:
    """Links touching an exported entity whose two ends are both live (not archived)."""
    links: dict[str, dict[str, Any]] = {}
    for entity_id in exported:
        for link in world.links(entity_id, "both"):
            links[link["id"]] = {key: link[key] for key in ("id", "type", "source", "target")}
    return [links[key] for key in sorted(links)]


EVERYTHING = Selection()


def plan_bundle(world: World, runs_root: Path, selection: Selection = EVERYTHING) -> Plan:
    """Work out the manifest and the asset files, without writing anything."""
    entities = _selected(world, selection)
    files: dict[str, Path] = {}
    exported = []
    for entity in entities:
        assets: dict[str, Any] = {}
        for slot, choice in sorted(world.chosen(entity["id"]).items()):
            found = read_provenance(runs_root, choice)
            path, asset = _asset(entity["kind"], entity["id"], slot, found)
            files[path] = found.file
            assets[slot] = asset
        exported.append(
            {
                "id": entity["id"],
                "kind": entity["kind"],
                "revision": entity["revision"],
                "title": entity["title"],
                "data": entity["data"],
                "assets": assets,
            }
        )
    kinds = []
    for kind in sorted(world.catalogue.kinds.values(), key=lambda k: k.id):
        described = kind.describe()
        described.pop("schema_file")
        described.pop("parameters")  # derived from the schema, which the bundle carries
        described.pop("family")  # how the app groups kinds; the bundle's shape stays as it was
        described.pop("form")
        kinds.append(described)
    manifest: dict[str, Any] = {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "project": {"slug": world.project.slug, "name": world.project.name},
        "selection": selection.describe(),
        "kinds": kinds,
        "link_types": sorted(world.link_types(), key=lambda t: t["id"]),
        "entities": exported,
        "links": _links(world, (e["id"] for e in entities)),
    }
    if selection.since is not None:
        live = {entity["id"] for entity in world.list_entities()}
        manifest["removed"] = sorted(set(selection.since) - live)
    validate_manifest(manifest)
    return Plan(manifest, files)


def manifest_text(manifest: Mapping[str, Any]) -> str:
    return json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_bundle(plan: Plan, out: Path) -> Path:
    """Write the bundle folder `out`, which must be missing or empty. Returns `out`."""
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise Conflict(f"{out} exists and is not an empty folder", "folder_not_empty", "/out")
    out.mkdir(parents=True, exist_ok=True)
    for relative, source in sorted(plan.files.items()):
        target = out / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    (out / MANIFEST).write_text(manifest_text(plan.manifest), encoding="utf-8")
    return out


def write_zip(folder: Path, target: Path) -> Path:
    """Zip a bundle folder: entries sorted, fixed timestamps and permissions, so it is stable."""
    names = sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            info = zipfile.ZipInfo(name, date_time=ZIP_TIME)
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, (folder / name).read_bytes())
    return target
