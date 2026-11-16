"""A throwaway project for the docs view tests: nested docs, links of every kind, planted
symlinks that point outside the repo, a source folder and a secret next to it."""

import json
from pathlib import Path

from core.project_file import ProjectFile, load_project_file

SECRET = "TOPSECRET-outside-the-repo"
INDEX = """# Tmp Game

Intro with ratchet and World State words.

## Links

- [guide](guide.md) and [nested](deep/nested.md#top) and [missing](missing.md)
- [code](../src/main.gd:12) and [absolute](/src/main.gd) and [encoded](..%2Fsrc%2Fmain.gd)
- [not allowed](../secret_src/key.txt) and [git](../.git/config)
- [outside](../../outside/secret.md) and [planted](../src/evil.gd)
- [web](https://example.com/a) and [mail](mailto:a@b.c) and [here](#links)
- [script](javascript:void) and ![pic](../src/main.gd)
[ref]: guide.md

```
[fenced](guide.md) is code, not a link
```
"""


def make_project(base: Path) -> ProjectFile:
    repo = base / "repo"
    outside = base / "outside"
    for folder in (
        repo / "docs/deep",
        repo / "src",
        repo / "secret_src",
        repo / "data",
        repo / ".git",
        outside,
    ):
        folder.mkdir(parents=True)
    (outside / "secret.md").write_text(SECRET)
    (outside / "secret.txt").write_text(SECRET)
    (repo / "README.md").write_text("# Tmp Game readme\n\nSee [index](docs/index.md).\n")
    (repo / "docs/index.md").write_text(INDEX)
    (repo / "docs/guide.md").write_text(
        "Guide without a title.\n\n## Setup\n\nRun the ratchet.\nratcheting is not the word\n"
    )
    (repo / "docs/deep/nested.md").write_text("# Nested\n\n## Top\n\nworld state lives here\n")
    (repo / "docs/notes.txt").write_text("not markdown")
    (repo / "docs/.hidden.md").write_text("hidden")
    (repo / "docs/evil.md").symlink_to(outside / "secret.md")
    (repo / "docs/outlink").symlink_to(outside, target_is_directory=True)
    (repo / "src/main.gd").write_text("".join(f"line {n}\n" for n in range(1, 301)))
    (repo / "src/blob.bin").write_bytes(b"\x00\x01binary")
    (repo / "src/evil.gd").symlink_to(outside / "secret.txt")
    (repo / "secret_src/key.txt").write_text(SECRET)
    (repo / ".git/config").write_text("[core]\n")
    (repo / "data/x.json").write_text("{}")
    file = repo / "studio.project.json"
    file.write_text(
        json.dumps(
            {
                "slug": "tmp-game",
                "name": "Tmp Game",
                "docs_roots": ["docs"],
                "docs_files": ["README.md"],
                "source_allowlist": ["src"],
            }
        )
    )
    return load_project_file(file)
