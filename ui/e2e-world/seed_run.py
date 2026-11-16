"""Puts a stand-in generation job and its run in a project, for the profile end-to-end test.

    uv run python ../ui/e2e-world/seed_run.py <project folder> <entity id> <entity revision> <runs root> [model.glb]

It writes three small real PNG images and a 3D file into a new run folder, each in the stage that
would have made it, with the gate report that stage would have left (pass, review, fail), records
the job and its candidates, and prints the job id and candidates as JSON. Nothing here needs a
forge or a GPU.
"""

import json
import struct
import sys
import zlib
from pathlib import Path

from authoring.job_store import JobStore

WIDTH, HEIGHT = 360, 270


def png(path: Path, colours: tuple[tuple[int, int, int], tuple[int, int, int]], seed: int) -> None:
    """A gradient with a simple object in it, as a valid 8-bit RGB PNG."""
    rows = []
    for y in range(HEIGHT):
        row = bytearray([0])
        for x in range(WIDTH):
            top, bottom = colours
            t = y / HEIGHT
            pixel = [int(top[i] * (1 - t) + bottom[i] * t) for i in range(3)]
            on_top = 70 + seed * 6 < y < 100 + seed * 6 and 60 < x < 300
            on_leg = 100 + seed * 6 <= y < 220 and (70 < x < 90 or 270 < x < 290)
            if on_top:
                pixel = [185, 138, 85]
            elif on_leg:
                pixel = [95, 102, 112]
            row.extend(pixel)
        rows.append(bytes(row))

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", WIDTH, HEIGHT, 8, 2, 0, 0, 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(b"".join(rows)))
        + chunk(b"IEND", b"")
    )


def main() -> None:
    folder, entity_id, revision, runs_root = sys.argv[1:5]
    model = Path(sys.argv[5]).read_bytes() if len(sys.argv) > 5 else b"glTF stand-in"
    store = JobStore.for_project(Path(folder))
    job = store.create_job(
        {"id": entity_id, "kind": "prop", "revision": int(revision), "data": {"name": "Key"}},
        "concept",
        {"prompt": "a key on a white background", "adapters": {}, "choices": {"seed": 1}},
    )
    run = Path(runs_root) / job["id"] / "attempts" / "a1"
    plan = [
        ("concept", "final.png", ((235, 232, 224), (200, 196, 186)), 0, {"verdict": "pass"}),
        ("tidy", "final.png", ((224, 232, 238), (186, 196, 204)), 1, {"verdict": "review"}),
        ("shape", "final.png", ((238, 226, 224), (204, 190, 186)), 2, {"passed": False}),
    ]
    made = []
    for stage, name, colours, seed, report in plan:
        png(run / stage / name, colours, seed)
        (run / stage / "image-validation.json").write_text(json.dumps(report))
        made.append(f"attempts/a1/{stage}/{name}")
    (run / "mesh").mkdir(parents=True)
    (run / "mesh" / "mesh.glb").write_bytes(model)
    (run / "mesh" / "mesh-validation.json").write_text(json.dumps({"verdict": "pass"}))
    made.append("attempts/a1/mesh/mesh.glb")
    for ref in made:
        store.add_candidate(job["id"], str(Path(runs_root) / job["id"] / ref), "stand-in")
    print(json.dumps({"job_id": job["id"], "candidates": made}))


if __name__ == "__main__":
    main()
