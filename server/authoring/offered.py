"""The pipelines a job can ask for by id, as data (offered.json), and what each one needs to run.

An entry names a pipeline file, the data folder that holds its look (`motifs/<id>.json`, `styles/<id>/`, `contract.json`),
the review sheet's look when the pipeline has a shape gate, and the entity kinds it serves (all kinds when omitted).
Paths are relative to `pipeline/pipelines/`. Which style and motif a run may use, its seeds and its number of
candidates are the choices the pipeline file declares (docs/pipeline_files.md, "Choices"); a request names a choice and
a value, and the paths below are made here from ids that passed that check, never from request text.
"""

import json
import sys
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
PIPELINE_DIR = REPO / "pipeline"
PIPELINES = PIPELINE_DIR / "pipelines"
OFFERED_FILE = Path(__file__).with_name("offered.json")

sys.path.insert(0, str(PIPELINE_DIR))
import pipeline_file  # noqa: E402


def adapter_kind(tool: str) -> str | None:
    """The adapter kind a pipeline tool runs, or None for a tool that runs no model."""
    kind: str | None = pipeline_file.TOOLS[tool].kind
    return kind


@dataclass(frozen=True)
class Offer:
    id: str
    file: Path
    data: Path
    sheet: Path | None
    entity_kinds: tuple[str, ...] | None  # None: any kind
    pipeline: Any  # pipeline_file.Pipeline

    def serves(self, entity_kind: str) -> bool:
        return self.entity_kinds is None or entity_kind in self.entity_kinds

    def style(self, style_id: str) -> Path:
        return self.data / "styles" / style_id

    def motif(self, motif_id: str) -> Path:
        return self.data / "motifs" / f"{motif_id}.json"

    @property
    def contract(self) -> Path:
        return self.data / "contract.json"

    def adapter_kinds(self) -> list[str]:
        """The adapter kinds the pipeline's model stages run, in stage order, each once."""
        kinds = [adapter_kind(s.tool) for s in self.pipeline.stages]
        return list(dict.fromkeys(k for k in kinds if k))

    def choose(self, given: dict[str, Any]) -> dict[str, Any]:
        """The values of the pipeline's choices for a run: GIVEN checked against its declaration, defaults for the rest.
        Raises ValueError("NAME: problem")."""
        values: dict[str, Any] = pipeline_file.resolve_choices(self.pipeline, given)
        return values

    def missing_files(self) -> list[str]:
        """Every file this offer needs that is not there (a style or motif the pipeline file offers, the contract, the sheet)."""
        needed = [self.contract]
        if self.sheet:
            needed.append(self.sheet)
        for name, spec in self.pipeline.choices.items():
            if name == "style":
                needed += [self.style(o) / "style.json" for o in spec["options"]]
            elif name == "motif":
                needed += [self.motif(o) for o in spec["options"]]
        return [str(p) for p in needed if not p.is_file()]


class OfferedError(RuntimeError):
    """offered.json or a file it names is wrong; the message names the entry."""


@cache
def offers() -> dict[str, Offer]:
    """Every offered pipeline by id. Read once; a wrong entry raises OfferedError naming it."""
    raw = json.loads(OFFERED_FILE.read_text(encoding="utf-8"))
    found: dict[str, Offer] = {}
    for entry in raw["pipelines"]:
        where = f"{OFFERED_FILE.name}: pipeline {entry.get('id')!r}"
        try:
            pipeline = pipeline_file.load(PIPELINES / entry["file"])
        except pipeline_file.PipelineError as error:
            raise OfferedError(f"{where}: {error}") from error
        if pipeline.id != entry["id"]:
            raise OfferedError(f"{where}: the pipeline file is called {pipeline.id!r}")
        offer = Offer(
            entry["id"],
            PIPELINES / entry["file"],
            PIPELINES / entry["data"],
            PIPELINES / entry["sheet"] if entry.get("sheet") else None,
            tuple(entry["entity_kinds"]) if entry.get("entity_kinds") else None,
            pipeline,
        )
        if entry["id"] in found:
            raise OfferedError(f"{where}: listed twice")
        missing = offer.missing_files()
        if missing:
            raise OfferedError(f"{where}: missing {', '.join(missing)}")
        found[offer.id] = offer
    return found
