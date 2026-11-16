"""What a person or an agent may choose from: the pipelines a job can run and the adapters this computer has.

Both lists are read-only views. An adapter is shown by id, kind and description, with whether it is the default of its
kind and whether this host can run it; its command, environment, folders and weights are never part of a view
(docs/adapters.md, "Trust rule"). The loaders are the pipeline's own (`pipeline/adapter_config.py`,
`pipeline/pipeline_file.py`); this module only picks what to show.
"""

import sys
from pathlib import Path
from typing import Any

from authoring import generation_file
from authoring.offered import PIPELINE_DIR, adapter_kind
from core.errors import BadProjectFiles

sys.path.insert(0, str(PIPELINE_DIR))
import adapter_config  # noqa: E402
import host  # noqa: E402


def _machine_adapters() -> Any:
    try:
        return adapter_config.from_machine()
    except adapter_config.AdapterError as error:
        raise BadProjectFiles(str(error), "bad_machine_config") from error


def machine_adapters() -> dict[str, Any]:
    """The adapter entries of the machine config by id (the stand-ins when it has none)."""
    entries: dict[str, Any] = _machine_adapters().entries
    return entries


def adapters_view() -> list[dict[str, Any]]:
    """Every configured adapter: id, kind, description, default, and the reasons this host cannot run it (if any)."""
    found = _machine_adapters()
    rows = []
    for entry in sorted(found.entries.values(), key=lambda e: (e.kind, e.id)):
        unmet = host.unmet(entry.needs())
        rows.append(
            {
                "id": entry.id,
                "kind": entry.kind,
                "description": entry.description,
                "default": found.defaults.get(entry.kind) == entry.id,
                "runnable": not unmet,
                "unmet": unmet,
            }
        )
    return rows


def pipelines_view(
    project_root: Path | None, entity_kind: str | None = None
) -> list[dict[str, Any]]:
    """Every pipeline a job can ask for in the project at PROJECT_ROOT, or by the tool's defaults when it is None (those
    serving ENTITY_KIND when given, by the project's generation.json or the tool's defaults): id, name, kind, the entity kinds it serves by default (null: any), its stages
    with the adapter kind each model stage runs, and the choices it declares with their defaults."""
    rows = []
    for offer in generation_file.offered_for(project_root, entity_kind):
        pipeline = offer.pipeline
        stages = [
            {"id": s.id, "label": s.label, "tool": s.tool, "adapter_kind": adapter_kind(s.tool)}
            for s in pipeline.stages
        ]
        rows.append(
            {
                "id": offer.id,
                "name": pipeline.name,
                "kind": pipeline.kind,
                "entity_kinds": list(offer.entity_kinds) if offer.entity_kinds else None,
                "stages": stages,
                "choices": {name: dict(spec) for name, spec in pipeline.choices.items()},
            }
        )
    return rows
