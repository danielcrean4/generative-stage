"""Puts a stand-in pipeline run in a project, for the trace, statistics and choosing end-to-end test.

    uv run python ../ui/e2e-world/seed_trace.py <project folder> <entity id> <entity revision> <runs root> [model.glb]

The run has three attempts, written the way the pipeline runner writes them:
  - 20261110T100000Z-aaaa0001: concept, tidy (reused) and shape. The shape gate fails, so the
    attempt is `failed`. Its three files are the job's candidates.
  - 20261111T100000Z-bbbb0002: the newest. Its tidy stage errored, so shape was never reached.
  - 20261109T100000Z-cccc0003: the oldest, which finished cleanly (it has no files).
It prints the job id and the candidate paths as JSON. Nothing here needs a forge or a GPU.
"""

import json
import sys
from pathlib import Path

from authoring.job_store import JobStore
from seed_run import png

FIRST = "20261110T100000Z-aaaa0001"
SECOND = "20261111T100000Z-bbbb0002"
THIRD = "20261109T100000Z-cccc0003"
PROMPT = "a worn oak workshop bench, whole object in frame, plain white background"
PLAN = [
    {"id": "concept", "label": "Concept image", "tool": "concept", "params": {"width": 512}},
    {"id": "tidy", "label": "Tidy the image", "tool": "tidy", "params": {"tolerance": 236}},
    {"id": "shape", "label": "Make the shape", "tool": "mesh", "params": {"steps": 30}},
]
MODEL = {"adapter_id": "stand-in", "adapter_version": "1", "weights_sha256": "ab12cd34"}


def write(path: Path, doc: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc))


def entry(stage: str, seconds: float, **extra: object) -> dict[str, object]:
    return {
        "stage": stage,
        "tool": stage,
        "key": f"key-{stage}",
        "seed": 7,
        "model": MODEL,
        "outputs": {},
        "timing": {"seconds": seconds},
        "reused_from": None,
        "reused": False,
        "folder": stage,
        **extra,
    }


def main() -> None:
    folder, entity_id, revision, runs_root = sys.argv[1:5]
    model = Path(sys.argv[5]).read_bytes() if len(sys.argv) > 5 else b"glTF stand-in"
    store = JobStore.for_project(Path(folder))
    job = store.create_job(
        {"id": entity_id, "kind": "prop", "revision": int(revision), "data": {"name": "Bench"}},
        "concept",
        {"prompt": PROMPT, "adapters": {}, "choices": {"seed": 7}},
    )
    run = Path(runs_root) / job["id"]
    first = run / "attempts" / FIRST
    for stage, colours, seed in (
        ("concept", ((235, 232, 224), (200, 196, 186)), 0),
        ("tidy", ((224, 232, 238), (186, 196, 204)), 1),
    ):
        png(first / stage / "final.png", colours, seed)
        write(first / stage / "image-validation.json", {"verdict": "pass"})
    write(first / "concept" / "stage.json", {"prompt": PROMPT, "negative": "blurry, cropped"})
    (first / "shape").mkdir(parents=True)
    (first / "shape" / "mesh.glb").write_bytes(model)
    write(
        first / "shape" / "mesh-validation.json",
        {
            "verdict": "fail",
            "reasons": ["the silhouette does not match the image"],
            "measures": {"faces": 4200, "silhouette_iou": 0.48},
            "thresholds": {"silhouette_iou": 0.6},
        },
    )
    write(
        first / "attempt.json",
        {
            "attempt": FIRST,
            "run_id": job["id"],
            "status": "failed",
            "started_utc": "2026-11-10T10:00:00Z",
            "finished_utc": "2026-11-10T10:03:30Z",
            "wall_seconds": 210.0,
            "seed": 7,
            "resolved_job": {"stages": PLAN},
            "sources": {"style": {"id": "plain-pack", "sha256": "ef56"}},
            "stages": {
                "concept": entry("concept", 62.5, prompt=PROMPT),
                "tidy": entry("tidy", 0.0, reused=True, reused_from="attempts/earlier/tidy"),
                "shape": entry("shape", 147.5, gate={"verdict": "fail", "reasons": []}),
            },
            "tries": [],
        },
    )

    second = run / "attempts" / SECOND
    png(second / "concept" / "final.png", ((232, 236, 226), (196, 202, 190)), 3)
    write(second / "concept" / "stage.json", {"prompt": PROMPT, "negative": "blurry, cropped"})
    (second / "tidy").mkdir(parents=True)
    write(
        second / "attempt.json",
        {
            "attempt": SECOND,
            "run_id": job["id"],
            "status": "failed",
            "error": "tidy: the image tool stopped with a memory error",
            "started_utc": "2026-11-11T10:00:00Z",
            "finished_utc": "2026-11-11T10:01:20Z",
            "wall_seconds": 80.0,
            "seed": 8,
            "resolved_job": {"stages": PLAN},
            "stages": {
                "concept": entry("concept", 58.0),
                "tidy": entry(
                    "tidy",
                    21.0,
                    failed=["the image tool stopped with a memory error"],
                    gate={"verdict": "fail", "reasons": ["the image tool stopped"]},
                ),
            },
        },
    )
    write(run / "latest.json", {"attempt": SECOND})

    third = run / "attempts" / THIRD  # an earlier attempt that finished cleanly
    write(
        third / "attempt.json",
        {
            "attempt": THIRD,
            "run_id": job["id"],
            "status": "generated",
            "started_utc": "2026-11-09T10:00:00Z",
            "finished_utc": "2026-11-09T10:02:00Z",
            "wall_seconds": 120.0,
            "seed": 6,
            "resolved_job": {"stages": PLAN},
            "stages": {
                "concept": entry("concept", 50.0),
                "tidy": entry("tidy", 12.0),
                "shape": entry("shape", 58.0, gate={"verdict": "pass", "reasons": []}),
            },
        },
    )

    made = [
        f"attempts/{FIRST}/concept/final.png",
        f"attempts/{FIRST}/tidy/final.png",
        f"attempts/{FIRST}/shape/mesh.glb",
    ]
    for ref in made:
        store.add_candidate(job["id"], str(run / ref), "stand-in")
    print(json.dumps({"job_id": job["id"], "candidates": made, "first": FIRST, "second": SECOND}))


if __name__ == "__main__":
    main()
