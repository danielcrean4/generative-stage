"""Load the example project (examples/lantern-cove/seed.json) into a running install through its API.

    python3 scripts/load_example.py [http://127.0.0.1:4280] [--folder DIR]

The project is made in DIR (default `~/generative-stage-example`, outside this checkout) as an ordinary project: its
kinds, its store, its notes. Safe to run again: if the project is already registered nothing changes, and if DIR already
holds the project file it is opened instead of made again. The seed holds records and links only; generating pictures
and meshes is left to you (README, step 5). In a record's data, `{"entity": "<key>"}` stands for the id of the seed record
with that key (a script line's speaker, for example); records that are named so come earlier in the seed. Standard library only.
"""

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

SEED = Path(__file__).resolve().parents[1] / "examples" / "lantern-cove" / "seed.json"


def call(base: str, method: str, path: str, body: Any = None, want: tuple[int, ...] = (200, 201)) -> Any:
    data = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json", "X-Studio-Request": "1"}
    request = urllib.request.Request(base + path, data, headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=60) as answer:
            status, raw = answer.status, answer.read()
    except urllib.error.HTTPError as error:
        status, raw = error.code, error.read()
    except OSError as error:
        raise SystemExit(f"Cannot reach {base}: {error}. Is ./start.sh running?") from error
    if status not in want:
        raise SystemExit(f"{method} {path} answered {status}: {raw[:300]!r}")
    return json.loads(raw) if raw else None


def resolve(value: Any, ids: dict[str, str]) -> Any:
    """VALUE with every `{"entity": "<key>"}` replaced by the id the record with that key was given."""
    if isinstance(value, dict):
        if set(value) == {"entity"}:
            return ids[value["entity"]]
        return {k: resolve(v, ids) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, ids) for v in value]
    return value


def load(base: str, folder: Path, slug: str | None = None, name: str | None = None) -> tuple[str, str]:
    """Make the example project in FOLDER through the API at BASE, as SLUG and NAME (default: the seed's). Returns
    (slug, what was done)."""
    seed = json.loads(SEED.read_text())
    slug = slug or seed["slug"]
    name = name or seed["name"]
    if any(p["slug"] == slug for p in call(base, "GET", "/api/v1/projects")["projects"]):
        return slug, f"The example project '{slug}' is already loaded. Nothing changed."
    if (folder / "studio.project.json").is_file():
        call(base, "POST", "/api/v1/projects", {"project_file": str(folder / "studio.project.json")})
        return slug, f"Opened the existing project in {folder}."
    call(base, "POST", "/api/v1/projects", {"folder": str(folder), "slug": slug, "name": name})
    project = f"/api/v1/projects/{slug}"
    ids: dict[str, str] = {}
    for record in seed["entities"]:
        made = call(base, "POST", f"{project}/entities", {"kind": record["kind"], "data": resolve(record["data"], ids)})
        ids[record["key"]] = made["id"]
    for link in seed["links"]:
        call(base, "POST", f"{project}/links", {"type": link["type"], "source": ids[link["source"]], "target": ids[link["target"]]})
    for note in seed["notes"]:
        call(base, "POST", f"{project}/entities/{ids[note['entity']]}/notes", {"text": note["text"]})
    return slug, f"Loaded '{name}' into {folder}: {len(ids)} records, {len(seed['links'])} links, {len(seed['notes'])} note."


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("base", nargs="?", default="http://127.0.0.1:4280", help="the web app's address")
    parser.add_argument("--folder", default="~/generative-stage-example", help="where the project's folder is made")
    args = parser.parse_args()
    print(load(args.base.rstrip("/"), Path(args.folder).expanduser().resolve())[1])
    return 0


if __name__ == "__main__":
    sys.exit(main())
