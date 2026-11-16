"""Write THIRD_PARTY.md from the real dependency locks, so the list cannot drift from what is installed.

    python3 scripts/third_party.py            rewrite THIRD_PARTY.md
    python3 scripts/third_party.py --check    exit 1 when THIRD_PARTY.md is out of date (prints why)

Names and versions come from `server/uv.lock`, `pipeline/requirements.txt` and `ui/package-lock.json`. A web package's
licence is the `license` field of the lock file. A Python package's licence is read from the metadata of the installed
package (so run `./install.sh --dev` first); nothing is fetched from the network. A package whose licence cannot be
read stops the script with its name: add it to LICENCE_OVERRIDES after reading its project page, never guess.
The output is sorted and has no dates, so the same locks give the same file.
"""

import argparse
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "THIRD_PARTY.md"
SERVER_PYTHON = REPO / "server" / ".venv" / "bin" / "python"
TOOLS_PYTHON = REPO / ".venv-tools" / "bin" / "python"

# Licences the installed metadata does not state, or states only as free text ("BSD License"), read from the
# project's own licence file.
# Each entry: normalised package name -> SPDX identifier. Keep this list short and checked.
# These are locked for other platforms only (Emscripten and Windows), so they are not installed here: read from the
# METADATA of the wheel the lock names.
LICENCE_OVERRIDES: dict[str, str] = {
    "colorama": "BSD-3-Clause",
    "pathspec": "MPL-2.0",
    "scipy": "BSD-3-Clause (some bundled components carry other permissive licences)",  # its LICENSE.txt, read
    "trimesh": "MIT",
    "httpx2-jsfetch": "BSD-3-Clause",
    "pywin32": "PSF (Python Software Foundation licence; also bundles notices for Scintilla, MAPI stubs and IDLE)",
}

# Run inside an environment: print {normalised name: [version, licence or null]} for every installed package.
_METADATA_CODE = r"""
import importlib.metadata as md, json, re
out = {}
for dist in md.distributions():
    meta = dist.metadata
    name = re.sub(r"[-_.]+", "-", meta["Name"]).lower()
    licence = meta.get("License-Expression")
    if not licence:
        free = (meta.get("License") or "").strip()
        if free and "\n" not in free and len(free) <= 60:
            licence = free
    if not licence:
        classes = [c.split("::")[-1].strip() for c in (meta.get_all("Classifier") or []) if c.startswith("License ::")]
        classes = [c for c in classes if c != "OSI Approved"]
        licence = " OR ".join(sorted(set(classes))) or None
    out[name] = [dist.version, licence]
print(json.dumps(out))
"""

# Code in this repository that is adapted from elsewhere, found by reading the files: icon outlines.
ADAPTED = [
    ("Five icon outlines (`landscape`, `person`, `category`, `key`, `place`) in `ui/src/app/world/kind-icon.ts`; four are copies or close redrawings, `key` may be original", "Google's Material Icons", "Apache-2.0", "https://github.com/google/material-design-icons"),
]

INTRO = """\
# Third-party software

Generative Stage is MIT-licensed ([LICENSE](LICENSE); the scripts in `blender/` are covered by
[blender/LICENSE-NOTE.md](blender/LICENSE-NOTE.md)). It uses the packages below. This file is written by
`scripts/third_party.py` from `server/uv.lock`, `pipeline/requirements.txt` and `ui/package-lock.json`; do not edit it
by hand, run the script again after a lock changes. Python licences come from the metadata of the installed packages,
web licences from the lock file. It lists only what this repository ships or what `./install.sh` and the container
install; no model ships, and a model or program you add as an adapter carries its own licence. This is a list for
people, not legal advice.

Apart from the icon outlines listed under "Adapted", no third-party source code is copied or vendored into this repository.
The web app's favicon (`ui/public/favicon.ico`, two overlapping circles on a dark square) is original, made for this
project when the web app was renamed (it replaced the framework's default icon), and is under the repository's MIT
licence.
"""


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def installed(python: Path, label: str) -> dict[str, list[str | None]]:
    if not python.is_file():
        sys.exit(f"{label} environment not found at {python}. Run ./install.sh --dev first.")
    result = subprocess.run([str(python), "-I", "-c", _METADATA_CODE], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def server_packages() -> dict[str, tuple[str, bool]]:
    """name -> (version, needed at run time) from server/uv.lock."""
    lock = tomllib.loads((REPO / "server" / "uv.lock").read_text())
    packages = {norm(p["name"]): p for p in lock["package"]}
    root = next(p for p in lock["package"] if "virtual" in p["source"] or "editable" in p["source"])

    def closure(start: list[str]) -> set[str]:
        seen: set[str] = set()
        todo = [norm(n) for n in start]
        while todo:
            name = todo.pop()
            if name in seen or name not in packages:
                continue
            seen.add(name)
            todo += [norm(d["name"]) for d in packages[name].get("dependencies", [])]
        return seen

    runtime = closure([d["name"] for d in root.get("dependencies", [])])
    return {
        name: (p["version"], name in runtime)
        for name, p in packages.items()
        if p is not root
    }


def tools_packages() -> dict[str, str]:
    pins: dict[str, str] = {}
    for line in (REPO / "pipeline" / "requirements.txt").read_text().splitlines():
        match = re.match(r"([A-Za-z0-9_.-]+)==([^\s#]+)", line.strip())
        if match:
            pins[norm(match.group(1))] = match.group(2)
    return pins


def web_packages() -> list[tuple[str, str, str, bool]]:
    lock = json.loads((REPO / "ui" / "package-lock.json").read_text())
    seen: dict[tuple[str, str], tuple[str, bool]] = {}
    for path, entry in lock["packages"].items():
        if not path:
            continue
        name = path.rsplit("node_modules/", 1)[-1]
        licence = entry.get("license")
        if not licence:
            sys.exit(f"ui/package-lock.json: {name} {entry.get('version')} has no licence field")
        key = (name, entry["version"])
        dev = bool(entry.get("dev") or entry.get("devOptional"))
        # the same package can sit in several folders: it is a run-time package if any copy is
        seen[key] = (licence if isinstance(licence, str) else json.dumps(licence), dev and seen.get(key, ("", True))[1])
    return sorted((n, v, lic, dev) for (n, v), (lic, dev) in seen.items())


def table(rows: list[tuple[str, ...]], head: tuple[str, ...]) -> str:
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)


def python_rows(packages: dict[str, tuple[str, bool]], meta: dict[str, list[str | None]]) -> list[tuple[str, ...]]:
    rows, unknown = [], []
    for name in sorted(packages):
        version, _ = packages[name]
        found = meta.get(name)
        licence = LICENCE_OVERRIDES.get(name) or (found[1] if found else None)
        if not licence:
            unknown.append(name)
            continue
        rows.append((name, version, licence.replace("|", "/")))
    if unknown:
        sys.exit("No licence found for: " + ", ".join(unknown) + ". Read each project's page and add it to LICENCE_OVERRIDES.")
    return rows


def build() -> str:
    server = server_packages()
    server_meta = installed(SERVER_PYTHON, "Server")
    tools = tools_packages()
    tools_meta = installed(TOOLS_PYTHON, "Tools")
    for name, (version, _) in server.items():
        found = server_meta.get(name)
        if found and found[0] != version:
            sys.exit(f"Server environment has {name} {found[0]} but server/uv.lock says {version}. Run ./install.sh --dev.")
    for name, version in tools.items():
        found = tools_meta.get(name)
        if found and found[0] != version:
            sys.exit(f"Tools environment has {name} {found[0]} but requirements.txt says {version}. Run ./install.sh.")
    runtime = {n: v for n, v in server.items() if v[1]}
    development = {n: v for n, v in server.items() if not v[1]}
    web = web_packages()
    web_runtime = [(n, v, lic) for n, v, lic, dev in web if not dev]
    web_dev = [(n, v, lic) for n, v, lic, dev in web if dev]
    parts = [INTRO]
    parts += [
        "## Server (Python), run time\n\nFrom `server/uv.lock`: what the server, the pipeline runner and the MCP server need.\n",
        table(python_rows(runtime, server_meta), ("Package", "Version", "Licence")),
        "\n## Server (Python), development only\n\nTests, linting and type checking. Not needed to run the tool.\n",
        table(python_rows(development, server_meta), ("Package", "Version", "Licence")),
        "\n## Tools environment (Python)\n\nFrom `pipeline/requirements.txt`: the deterministic image and mesh stages.\n",
        table(python_rows({n: (v, True) for n, v in tools.items()}, tools_meta), ("Package", "Version", "Licence")),
        "\n## Web app (npm), in the built app and its tooling\n\nFrom `ui/package-lock.json`: packages the built web app or the build "
        "itself needs. The built app bundles Angular, Angular Material, three.js, JSON Forms and markdown-it; the rest "
        "are build-time.\n",
        table(web_runtime, ("Package", "Version", "Licence")),
        "\n## Web app (npm), development only\n\nTest and build tools. Not part of the built app.\n",
        table(web_dev, ("Package", "Version", "Licence")),
        "\n## Adapted\n\nWhat in this repository is adapted from elsewhere, and under which licence. They are treated as Apache-2.0 material; "
        "the licence text is at the link.\n",
        table([tuple(row) for row in ADAPTED], ("What", "From", "Licence", "Source")),
        "",
    ]
    return "\n".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--check", action="store_true", help="exit 1 if THIRD_PARTY.md is out of date")
    args = parser.parse_args()
    text = build()
    if args.check:
        if not OUT.is_file() or OUT.read_text() != text:
            print("THIRD_PARTY.md is out of date: run python3 scripts/third_party.py")
            return 1
        print("THIRD_PARTY.md is up to date")
        return 0
    OUT.write_text(text)
    print(f"wrote {OUT.name}: {text.count(chr(10))} lines")
    return 0


if __name__ == "__main__":
    sys.exit(main())
