"""A small fake runs root that mirrors the real layout, shared by the run view tests.

RUN_JOB has two attempts: an older failed one (matte gate failed, matte not recorded) and a newer
one with concept, matte and a mesh stage that failed try-0 and passed try-1. RUN_ICON is an
icon-style run with only root files. Planted escapes: a symlinked file in a stage folder, a
symlinked file at a run root, and a symlinked run folder, all pointing outside the root.
"""

import json
from pathlib import Path
from typing import Any

RUN_JOB = "11111111-aaaa-bbbb-cccc-000000000001"
RUN_ICON = "22222222-aaaa-bbbb-cccc-000000000002"
RUN_LINK = "33333333-aaaa-bbbb-cccc-000000000003"
OLD_ATTEMPT = "20261101T000000Z-aaaa0001"
NEW_ATTEMPT = "20261102T000000Z-bbbb0002"
SECRET = "outside-secret"
BIG_LOG_BYTES = 300 * 1024


def _write(path: Path, content: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content)


def _json(path: Path, doc: Any) -> None:
    _write(path, json.dumps(doc))


def _stage_json(seed: int, settings: dict[str, Any], **extra: Any) -> dict[str, Any]:
    recipe = {
        "stage": "x",
        "seed": seed,
        "settings": settings,
        "versions": {"python": "3.15"},
        "model": {"path": "/m", "sha256": "ab", "files": {"a": "1", "b": "2"}},
    }
    return {"recipe": recipe, "retry_errors": [], **extra}


def make_runs_root(base: Path) -> Path:
    """Build the fake root at base/runs and a file outside it at base/outside/secret.txt."""
    root = base / "runs"
    outside = base / "outside"
    _write(outside / "secret.txt", SECRET)
    _write(outside / "secret.png", SECRET)
    _json(outside / "attempts" / "x" / "attempt.json", {"status": "outside"})

    job = root / RUN_JOB
    old = job / "attempts" / OLD_ATTEMPT
    _json(
        old / "attempt.json",
        {
            "id": RUN_JOB,
            "attempt": OLD_ATTEMPT,
            "recipe": {"seed": 7, "stages": ["concept", "matte", "mesh"]},
            "status": "failed",
            "error": "matte failed: subject covers 0.95 of the frame",
            "stages": {"concept": {"key": "k0", "reused": False, "outputs": {}}},
            "started_utc": "2026-11-01T00:00:00Z",
            "finished_utc": "2026-11-01T00:01:00Z",
        },
    )
    _json(old / "concept" / "stage.json", _stage_json(7, {"prompt": "a card"}))
    _write(old / "concept" / "image.png", b"\x89PNG")
    _json(
        old / "matte" / "matte.json",
        {"passed": False, "reasons": ["too big"], "subject_share": 0.95},
    )

    new = job / "attempts" / NEW_ATTEMPT
    _json(
        new / "attempt.json",
        {
            "id": RUN_JOB,
            "attempt": NEW_ATTEMPT,
            "recipe": {"seed": 8, "stages": ["concept", "matte", "mesh"]},
            "status": "generated",
            "stages": {
                "concept": {"key": "kc", "reused": True, "outputs": {}},
                "matte": {"key": "km", "reused": False, "outputs": {}},
                "mesh": {"key": "kh", "reused": False, "seed_used": 9, "outputs": {}},
            },
            "started_utc": "2026-11-02T00:00:00Z",
            "finished_utc": "2026-11-02T00:05:00Z",
        },
    )
    _json(new / "concept" / "stage.json", _stage_json(8, {"prompt": "the resolved prompt"}))
    _json(new / "concept" / "image-validation.json", [{"format": "PNG", "size": [8, 8]}])
    _write(new / "concept" / "image.png", b"\x89PNG")
    _write(new / "concept" / "step.log", "x" * 10 + "\n" * 0)
    _write(new / "concept" / "big.log", "a" * (BIG_LOG_BYTES - 5) + "TAIL!")
    _write(new / "concept" / "tool.exe", "not served")
    _json(new / "matte" / "stage.json", _stage_json(8, {"tolerance": 236}))
    _json(new / "matte" / "matte.json", {"passed": True, "reasons": [], "subject_share": 0.3})
    _write(new / "matte" / "matte.png", b"\x89PNG")
    tries = [
        {
            "try": 0,
            "seed": 8,
            "report": "try-0/mesh-validation.json",
            "passed": False,
            "reasons": ["flat"],
        },
        {
            "try": 1,
            "seed": 9,
            "report": "try-1/mesh-validation.json",
            "passed": True,
            "reasons": [],
        },
    ]
    _json(new / "mesh" / "stage.json", _stage_json(8, {}, tries=tries, seed_used=9))
    _json(
        new / "mesh" / "mesh-validation.json",
        {"measures": {"faces": 10}, "passed": True, "reasons": [], "thresholds": {"min": 1}},
    )
    _write(new / "mesh" / "mesh.glb", b"glTF")
    _json(
        new / "mesh" / "try-0" / "mesh-validation.json",
        {"measures": {"faces": 3}, "passed": False, "reasons": ["flat"], "thresholds": {}},
    )
    _write(new / "mesh" / "try-0" / "mesh.glb", b"glTF")
    _json(
        new / "mesh" / "try-1" / "mesh-validation.json",
        {"measures": {"faces": 10}, "passed": True, "reasons": []},
    )
    _write(new / "mesh" / "try-1" / "mesh.glb", b"glTF")
    _json(job / "latest.json", {"attempt": str(new), "status": "generated"})
    _write(job / "cache" / "concept" / "deadbeef" / "image.png", b"cached")
    _write(job / "bust_raw.png", b"\x89PNG")
    (new / "concept" / "evil.png").symlink_to(outside / "secret.png")
    (job / "leak.png").symlink_to(outside / "secret.png")

    icon = root / RUN_ICON
    _write(icon / "icon.png", b"\x89PNG")
    _json(
        icon / "icon.source.json", {"prompt": "a cap", "resolved_prompt": "a cap, icon", "seed": 11}
    )

    (root / RUN_LINK).symlink_to(outside, target_is_directory=True)
    _write(root / "stray_head.glb", "not a run")
    return root
