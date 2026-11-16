"""A pipeline-runner style run for the trace and statistics tests.

Two attempts. The first finished: concept, tidy (reused from an earlier run) and shape, whose gate
asked for a review. The second stopped inside its `shape` stage with an error.
"""

import json
from pathlib import Path
from typing import Any

RUN = "run-trace"
FIRST = "20261105T100000Z-aaaa0001"
SECOND = "20261106T090000Z-bbbb0002"
PROMPT = "a brass key on a white background, soft light"
PARTS = [
    {
        "text": "a brass key",
        "source": {"kind": "subject", "id": "brass_key"},
        "start": 0,
        "end": 11,
    },
    {
        "text": " on a white background",
        "source": {"kind": "style_pack", "id": "plain"},
        "start": 11,
        "end": 33,
    },
    {"text": ", soft light", "source": {"kind": "pipeline", "id": "prop"}, "start": 33, "end": 45},
]
NEGATIVE_PARTS = [
    {
        "text": "blurry",
        "source": {"kind": "style_pack", "id": "plain", "key": "prompt.negative"},
        "start": 0,
        "end": 6,
    }
]


def _json(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc))


def _file(path: Path, data: bytes = b"\x89PNG") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _plan() -> list[dict[str, Any]]:
    return [
        {
            "id": "concept",
            "label": "Concept image",
            "tool": "concept",
            "params": {"width": 512},
            "reads": {"style.prompt": {"negative": "blurry"}},
            "prompt": PROMPT,
        },
        {"id": "tidy", "label": "Tidy", "tool": "tidy", "params": {}, "reads": {}},
        {"id": "shape", "label": "Shape", "tool": "mesh", "params": {}, "reads": {}},
    ]


def _entry(stage: str, seconds: float, **extra: Any) -> dict[str, Any]:
    return {
        "stage": stage,
        "tool": stage,
        "key": f"key-{stage}",
        "seed": 7,
        "model": {"adapter_id": "stand-in", "adapter_version": "1", "weights_sha256": "ab12"},
        "outputs": {},
        "timing": {"seconds": seconds},
        "reused_from": None,
        "reused": False,
        "folder": stage,
        **extra,
    }


def make_run(runs_root: Path) -> Path:
    run = runs_root / RUN
    first = run / "attempts" / FIRST
    _json(
        first / "attempt.json",
        {
            "attempt": FIRST,
            "run_id": RUN,
            "status": "review",
            "started_utc": "2026-11-05T10:00:00Z",
            "finished_utc": "2026-11-05T10:03:00Z",
            "wall_seconds": 180.0,
            "seed": 7,
            "resolved_job": {"stages": _plan()},
            "sources": {"style": {"id": "plain", "sha256": "cd34"}},
            "stages": {
                "concept": _entry("concept", 60.0, prompt=PROMPT),
                "tidy": _entry("tidy", 0.0, reused=True, reused_from="attempts/earlier/tidy"),
                "shape": _entry(
                    "shape", 120.0, gate={"verdict": "review", "reasons": ["thin"], "measures": {}}
                ),
            },
            "tries": [],
        },
    )
    _json(
        first / "concept" / "stage.json",
        {
            "prompt": PROMPT,
            "negative": "blurry",
            "prompt_parts": PARTS,
            "negative_parts": NEGATIVE_PARTS,
            "inputs": {"seed_image": {"from": "supplied", "sha256": "ef56"}},
        },
    )
    _file(first / "concept" / "image.png")
    _json(first / "concept" / "image-validation.json", {"verdict": "pass", "width": 512})
    _file(first / "tidy" / "image.png")
    _file(first / "shape" / "mesh.glb", b"glTF")
    _json(
        first / "shape" / "mesh-validation.json",
        {
            "verdict": "review",
            "reasons": ["thin"],
            "measures": {"faces": 900, "iou": {"front": 0.55}},
            "thresholds": {"iou": 0.6},
        },
    )

    second = run / "attempts" / SECOND
    _json(
        second / "attempt.json",
        {
            "attempt": SECOND,
            "run_id": RUN,
            "status": "failed",
            "error": "shape: the mesh tool ran out of memory",
            "started_utc": "2026-11-06T09:00:00Z",
            "finished_utc": "2026-11-06T09:01:30Z",
            "wall_seconds": 90.0,
            "seed": 8,
            "resolved_job": {"stages": _plan()},
            "stages": {"concept": _entry("concept", 45.0), "tidy": _entry("tidy", 10.0)},
        },
    )
    _file(second / "concept" / "image.png")
    _file(second / "tidy" / "image.png")
    (second / "shape").mkdir(parents=True)
    _json(run / "latest.json", {"attempt": SECOND})
    return run
