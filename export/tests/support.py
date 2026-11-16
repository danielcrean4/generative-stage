"""A small project and runs root for the export tests: a hall, a guide, a key."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.registry import RegistryFile
from core.workspace import Workspace
from core.world import World

ATTEMPT = "20261101T000000Z-aaaa0001"
RUN_KEY = "run-key"
RUN_GUIDE = "run-guide"
GLB = b"glTF\x02\x00\x00\x00" + b"\x00" * 24
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


@dataclass
class Scene:
    world: World
    workspace: Workspace
    runs: Path
    hall: dict[str, Any]
    guide: dict[str, Any]
    key: dict[str, Any]


def _write(path: Path, content: bytes | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")


def make_runs(root: Path) -> Path:
    runs = root / "runs"
    attempt = runs / RUN_KEY / "attempts" / ATTEMPT
    _write(
        attempt / "attempt.json",
        json.dumps(
            {
                "id": RUN_KEY,
                "attempt": ATTEMPT,
                "recipe": {
                    "seed": 11,
                    "output_dir": "/somewhere/on/the/builder/runs",
                    "concept": {"prompt": "a heavy key on a white ground"},
                },
                "models": {
                    "concept": {
                        "adapter_id": "standin-image",
                        "adapter_version": 1,
                        "weights": {"path": "/somewhere/weights", "sha256": "ab" * 32},
                        "runtime_path": "/somewhere/bin/generate",
                    },
                    "mesh": {"model": "standin-mesh", "weights_sha256": "cd" * 32},
                },
                "stages": {
                    "concept": {"seed": 11},
                    "mesh": {"seed": 12, "prompt": "a heavy key"},
                },
            }
        ),
    )
    _write(attempt / "concept" / "image.png", PNG)
    _write(attempt / "mesh" / "mesh.glb", GLB)
    _write(runs / RUN_GUIDE / "portrait.png", PNG + b"guide")
    return runs


def make_scene(root: Path) -> Scene:
    workspace = Workspace(RegistryFile(root / "registry.json"))
    workspace.create(str(root / "sample"), "sample-project", "Sample Project")
    runs = make_runs(root)
    world = workspace.open("sample-project")
    hall = world.create_entity(
        "setting", {"name": "Hall", "brief": "A large hall.", "tags": ["outdoor"]}
    )
    guide = world.create_entity(
        "character", {"name": "Guide", "brief": "Shows visitors around.", "tags": ["crew"]}
    )
    key = world.create_entity(
        "prop",
        {"name": "Key", "brief": "A key to the storage room.", "tags": ["outdoor", "metal"]},
    )
    world.add_link("found_in", key["id"], hall["id"])
    world.choose(key["id"], RUN_KEY, f"attempts/{ATTEMPT}/mesh/mesh.glb")
    world.choose(key["id"], RUN_KEY, f"attempts/{ATTEMPT}/concept/image.png", slot="icon")
    world.choose(guide["id"], RUN_GUIDE, "portrait.png")
    return Scene(world, workspace, runs, hall, guide, key)
