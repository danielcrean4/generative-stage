"""The project file (`studio.project.json` at the root of a project folder): read, validate, write.

A project is a folder a person owns. This file names it and says where its kinds, pipelines,
store and docs are. Core owns the keys below; a caller that adds keys of its own names them in
`extra_keys` and validates them itself from `ProjectFile.extra`, using the path helpers here so
every message has the same form: `<file>: key '<key>': <problem>`.

| Key                | Required | What it is                                                         |
|--------------------|----------|--------------------------------------------------------------------|
| `slug`             | yes      | the project id: lowercase letters, digits, hyphens; never changes  |
| `name`             | yes      | the name people see                                                |
| `schema_dir`       | no       | folder holding kinds.json, link_types.json and the kind schemas    |
| `pipelines`        | no       | the project's default pipeline files or folders                    |
| `store`            | no       | the project's SQLite file (default `world.sqlite3`); need not exist |
| `docs_roots`       | no       | folders of markdown the docs view lists                            |
| `docs_files`       | no       | single markdown files the docs view lists, such as `README.md`     |
| `source_allowlist` | no       | folders whose files the docs view may show as source               |
| `external_docs`    | no       | absolute paths of folders of markdown outside the project, shown read-only |

Paths are relative to the folder, must stay inside it and never reach into `.git`. Every path but
`store` must exist. `external_docs` is the one key of absolute paths: each must be an existing
folder, and the docs view only reads from it.
"""

import json
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.errors import BadProjectFiles
from core.ids import SLUG

PROJECT_FILE_NAME = "studio.project.json"
DEFAULT_STORE = "world.sqlite3"
REQUIRED_KEYS = ("slug", "name")
CORE_KEYS = (
    "slug",
    "name",
    "schema_dir",
    "pipelines",
    "store",
    "docs_roots",
    "docs_files",
    "source_allowlist",
    "external_docs",
)


class ProjectFileError(BadProjectFiles, RuntimeError):
    """A project file or the registry is wrong; the message names the file and the key. Also a
    RuntimeError, as it was before it moved here, for callers that catch that."""

    code = "bad_project_file"


@dataclass(frozen=True)
class ProjectFile:
    file: Path  # the project file this was read from
    root: Path  # the project folder: the folder holding that file
    slug: str
    name: str
    schema_dir: Path | None
    pipelines: tuple[Path, ...]
    store: Path
    docs_roots: tuple[Path, ...] = ()
    docs_files: tuple[Path, ...] = ()
    source_allowlist: tuple[Path, ...] = ()
    external_docs: tuple[Path, ...] = ()  # absolute folders outside the project, read-only
    extra: Mapping[str, Any] = field(default_factory=dict)  # caller-owned keys, unvalidated


def text(file: Path, key: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProjectFileError(f"{file}: key '{key}': expected a non-empty string, got {value!r}")
    return value


def path_inside(
    file: Path,
    root: Path,
    key: str,
    value: object,
    must_exist: bool = True,
    place: str = "the project folder",
) -> Path:
    """A path written relative to the folder. It must stay inside the folder (symlinks followed),
    never reach into .git and, unless told otherwise, exist. `place` names the folder in the
    message."""
    relative = text(file, key, value)
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ProjectFileError(f"{file}: key '{key}': {relative!r} points outside {place}")
    if ".git" in path.relative_to(root).parts:
        raise ProjectFileError(f"{file}: key '{key}': {relative!r} is inside .git")
    if must_exist and not path.exists():
        raise ProjectFileError(f"{file}: key '{key}': {relative!r} does not exist")
    return path


def paths_inside(
    file: Path, root: Path, key: str, value: object, place: str = "the project folder"
) -> tuple[Path, ...]:
    if not isinstance(value, list):
        raise ProjectFileError(f"{file}: key '{key}': expected a list of paths")
    return tuple(
        path_inside(file, root, f"{key}[{i}]", entry, place=place) for i, entry in enumerate(value)
    )


def _docs_files(file: Path, root: Path, value: object) -> tuple[Path, ...]:
    paths = paths_inside(file, root, "docs_files", value)
    for i, path in enumerate(paths):
        if not path.is_file() or path.suffix != ".md":
            raise ProjectFileError(f"{file}: key 'docs_files[{i}]': must be a markdown (.md) file")
    return paths


def _external_docs(file: Path, value: object) -> tuple[Path, ...]:
    if not isinstance(value, list):
        raise ProjectFileError(f"{file}: key 'external_docs': expected a list of absolute paths")
    folders = []
    for i, entry in enumerate(value):
        key = f"external_docs[{i}]"
        raw = text(file, key, entry)
        if not Path(raw).is_absolute():
            raise ProjectFileError(f"{file}: key '{key}': {raw!r} is not an absolute path")
        folder = Path(raw).resolve()
        if not folder.is_dir():
            raise ProjectFileError(f"{file}: key '{key}': {raw!r} is not an existing folder")
        if ".git" in folder.parts:
            raise ProjectFileError(f"{file}: key '{key}': {raw!r} is inside .git")
        folders.append(folder)
    return tuple(folders)


def load_project_file(file: Path, extra_keys: Collection[str] = ()) -> ProjectFile:
    """Read and validate one project file. Keys outside core's and `extra_keys` are refused."""
    try:
        raw: Any = json.loads(file.read_text(encoding="utf-8"))
    except OSError as error:
        raise ProjectFileError(f"{file}: cannot read ({error})") from error
    except ValueError as error:
        raise ProjectFileError(f"{file}: not valid JSON ({error})") from error
    if not isinstance(raw, dict):
        raise ProjectFileError(f"{file}: the file must hold a JSON object")
    known = (*CORE_KEYS, *extra_keys)
    for key in raw:
        if key not in known:
            raise ProjectFileError(
                f"{file}: key '{key}': unknown key (known keys: {', '.join(known)})"
            )
    for key in REQUIRED_KEYS:
        if key not in raw:
            raise ProjectFileError(f"{file}: key '{key}': missing")
    root = file.resolve().parent
    slug = text(file, "slug", raw["slug"])
    if not SLUG.fullmatch(slug):
        raise ProjectFileError(
            f"{file}: key 'slug': {slug!r} must be lowercase letters, digits and hyphens"
        )
    return ProjectFile(
        file=file.resolve(),
        root=root,
        slug=slug,
        name=text(file, "name", raw["name"]),
        schema_dir=path_inside(file, root, "schema_dir", raw["schema_dir"])
        if "schema_dir" in raw
        else None,
        pipelines=paths_inside(file, root, "pipelines", raw.get("pipelines", [])),
        store=path_inside(file, root, "store", raw.get("store", DEFAULT_STORE), must_exist=False),
        docs_roots=paths_inside(file, root, "docs_roots", raw.get("docs_roots", [])),
        docs_files=_docs_files(file, root, raw.get("docs_files", [])),
        source_allowlist=paths_inside(
            file, root, "source_allowlist", raw.get("source_allowlist", [])
        ),
        external_docs=_external_docs(file, raw.get("external_docs", [])),
        extra={key: raw[key] for key in raw if key not in CORE_KEYS},
    )


def write_project_file(folder: Path, slug: str, name: str, schema_dir: str) -> Path:
    """Write a new project file into `folder` and return its path. Refuses to overwrite one."""
    file = folder / PROJECT_FILE_NAME
    if file.exists():
        raise ProjectFileError(f"{file}: a project file already exists here")
    content = {"slug": slug, "name": name, "schema_dir": schema_dir, "pipelines": []}
    file.write_text(json.dumps(content, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return file
