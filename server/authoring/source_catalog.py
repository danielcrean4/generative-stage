"""The shared sources a prompt is made from: the style packs, motifs and contracts in the data folders of the offered
pipelines (authoring/offered.json), each with a page id.

These files live in this tool's repository (`pipeline/pipelines/...`), not in a project, so they are read here and never
written: a source page shows where its file is, and an edit is a change to the repository. A source's id is
`<set>.<name>`: the set is its data folder's name (`prop`, `head`), because two sets can each have a style or motif of
the same name with different words. A contract has no name of its own and is `<set>.contract`.

A run records the hash of every source it read (`attempt.json`, `sources`). `link_for` and `refs_of` join those hashes to
the sources now on disk and say when the file has changed since the run, so a page never claims an old run read today's
words.
"""

import json
import sys
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from authoring.offered import PIPELINE_DIR, REPO, OfferedError, offers

sys.path.insert(0, str(PIPELINE_DIR))
import pipeline_resolve  # noqa: E402

TYPES = ("style", "motif", "contract")
CONTRACT_NAME = "contract"
CONTRACT_NOTE = "A contract holds axes and sizes for the mesh stages; it adds no words to a prompt."


@dataclass(frozen=True)
class Source:
    type: str
    set: str
    name: str
    path: Path
    sha256: str  # of the file's bytes
    flattened_sha256: str | None  # style only: of the pack after `extends` is applied
    body: dict[str, Any]  # the file as read
    extends: tuple[str, ...]  # style only: the ids of the packs it extends, nearest first
    prompt: dict[str, Any] | None  # style only: the flattened `prompt` block
    origins: dict[str, str]  # style only: dotted key -> name of the pack that set it

    @property
    def id(self) -> str:
        return f"{self.set}.{self.name}"

    @property
    def location(self) -> str:
        return self.path.relative_to(REPO).as_posix()


def _style(set_name: str, folder: Any) -> Source:
    style = pipeline_resolve.load_style(folder)
    own = style.chain[-1]
    parents = tuple(i for i, _, _ in reversed(style.chain[:-1]))
    return Source(
        "style",
        set_name,
        style.id,
        own[1],
        own[2],
        style.flat_sha256,
        _body(own[1]),
        parents,
        style.flat.get("prompt"),
        {key: origin["id"] for key, origin in style.origins.items()},
    )


def _body(path: Any) -> dict[str, Any]:
    body: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return body


def _plain(type_: str, set_name: str, name: str, loaded: Any) -> Source:
    return Source(
        type_, set_name, name, loaded.path, loaded.sha256, None, loaded.body, (), None, {}
    )


@cache
def catalog() -> dict[tuple[str, str], Source]:
    """Every source of every offered data folder by (type, id). Read once; a wrong file raises OfferedError."""
    found: dict[tuple[str, str], Source] = {}
    folders: dict[str, Path] = {}
    for offer in offers().values():
        if folders.setdefault(offer.data.name, offer.data) != offer.data:
            raise OfferedError(f"two data folders are both called {offer.data.name!r}")
    for set_name, data in folders.items():
        sources: list[Source] = []
        try:
            for folder in sorted((data / "styles").glob("*/style.json")):
                sources.append(_style(set_name, folder.parent))
            for file in sorted((data / "motifs").glob("*.json")):
                loaded = pipeline_resolve.load_motif(file)
                sources.append(_plain("motif", set_name, loaded.body["id"], loaded))
            contract = pipeline_resolve.load_contract(data / "contract.json")
            sources.append(_plain("contract", set_name, CONTRACT_NAME, contract))
        except ValueError as error:  # pipeline_file.PipelineError is a ValueError
            raise OfferedError(f"{data}: {error}") from error
        for source in sources:
            found[(source.type, source.id)] = source
    return found


def get(type_: str, source_id: str) -> Source | None:
    return catalog().get((type_, source_id))


def _uses(source: Source) -> list[dict[str, str]]:
    """The offered pipelines that can read the source: those on its data folder that offer the motif or style (or, for a
    style, a pack that extends it), and every one on the folder for a contract."""
    rows = []
    for offer in offers().values():
        if offer.data.name != source.set:
            continue
        options = offer.pipeline.choices.get(source.type, {}).get("options", [])
        if source.type == "contract":
            used = True
        elif source.type == "motif":
            used = source.name in options
        else:
            used = any(
                source.name == pack.name or source.name in pack.extends
                for pack in (get("style", f"{source.set}.{o}") for o in options)
                if pack is not None
            )
        if used:
            rows.append({"id": offer.id, "name": offer.pipeline.name})
    return rows


def view(source: Source) -> dict[str, Any]:
    """What a source page shows, without who read it: the file, its words, where it lives and the pipelines that use it."""
    texts: list[dict[str, Any]] = []
    if source.type == "style" and source.prompt:
        for kind, template in (source.prompt.get("templates") or {}).items():
            key = f"prompt.templates.{kind}"
            texts.append(
                {
                    "label": f"Template for {kind}",
                    "key": key,
                    "text": template,
                    "from": f"{source.set}.{source.origins[key]}",
                }
            )
        if "negative" in source.prompt:
            texts.append(
                {
                    "label": "Negative prompt",
                    "key": "prompt.negative",
                    "text": source.prompt["negative"],
                    "from": f"{source.set}.{source.origins['prompt.negative']}",
                }
            )
    elif source.type == "motif":
        texts.append(
            {"label": "Motif words", "key": "text", "text": source.body["text"], "from": source.id}
        )
    return {
        "type": source.type,
        "id": source.id,
        "name": source.name,
        "set": source.set,
        "location": source.location,
        "editable": False,
        "sha256": source.sha256,
        "content": source.body,
        "extends": [{"id": f"{source.set}.{p}", "name": p} for p in source.extends],
        "texts": texts,
        "note": CONTRACT_NOTE if source.type == "contract" else None,
        "pipelines": _uses(source),
    }


def listing() -> list[dict[str, Any]]:
    """Every source, for the Sources index: type, id, name, set, and the pipelines that use it."""
    return [
        {
            "type": s.type,
            "id": s.id,
            "name": s.name,
            "set": s.set,
            "pipelines": [p["id"] for p in _uses(s)],
        }
        for s in sorted(catalog().values(), key=lambda s: (TYPES.index(s.type), s.set, s.name))
    ]


def _find(
    type_: str, set_name: str | None, name: str, sha: str | None, flat: bool
) -> Source | None:
    """The source a run read: by set and name when the run's pipeline is known, else the one whose hash matches."""
    if set_name is not None:
        return get(type_, f"{set_name}.{name}")
    for source in catalog().values():
        if source.type == type_ and (source.flattened_sha256 if flat else source.sha256) == sha:
            return source
    return None


def link_for(source: dict[str, Any], set_name: str | None) -> dict[str, Any] | None:
    """The source page for one source of a prompt part (`{kind, id, sha256}`): `{type, id, changed}`, or None when the
    part's source is not a shared file (the subject, the pipeline's own words, the glue between parts)."""
    kind = {"style_pack": "style", "motif": "motif"}.get(str(source.get("kind")))
    name, sha = source.get("id"), source.get("sha256")
    if kind is None or not isinstance(name, str):
        return None
    found = _find(kind, set_name, name, sha, flat=False)
    if found is None:
        return None
    return {"type": kind, "id": found.id, "changed": found.sha256 != sha}


def refs_of(sources: dict[str, Any] | None, set_name: str | None) -> list[dict[str, Any]]:
    """The shared sources a run's `sources` record names, in the order a person reads them: style, motif, contract and the
    pipeline's capture words. Each is `{type, id, name, changed}`; `id` is None when the file is no longer on disk or has no
    page (the pipeline)."""
    if not isinstance(sources, dict):
        return []
    refs: list[dict[str, Any]] = []
    style = sources.get("style")
    if isinstance(style, dict) and isinstance(style.get("id"), str):
        found = _find("style", set_name, style["id"], style.get("flattened_sha256"), flat=True)
        refs.append(_ref("style", style["id"], found, style.get("flattened_sha256")))
    motif = sources.get("motif")
    if isinstance(motif, dict) and isinstance(motif.get("id"), str):
        found = _find("motif", set_name, motif["id"], motif.get("sha256"), flat=False)
        refs.append(_ref("motif", motif["id"], found, motif.get("sha256")))
    contract = sources.get("contract")
    if isinstance(contract, dict):
        sha = contract.get("sha256")
        found = _find("contract", set_name, CONTRACT_NAME, sha, flat=False)
        refs.append(_ref("contract", CONTRACT_NAME, found, sha))
    pipeline = sources.get("pipeline")
    if isinstance(pipeline, dict) and isinstance(pipeline.get("id"), str):
        refs.append({"type": "pipeline", "id": None, "name": pipeline["id"], "changed": False})
    return refs


def _ref(type_: str, name: str, found: Source | None, sha: str | None) -> dict[str, Any]:
    if found is None:
        return {"type": type_, "id": None, "name": name, "changed": False}
    now = found.flattened_sha256 if type_ == "style" else found.sha256
    return {"type": type_, "id": found.id, "name": found.name, "changed": now != sha}
