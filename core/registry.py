"""Which projects this tool knows about.

`ProjectRegistry` is an immutable list of loaded projects with unique slugs, built from files a
person lists (the machine config). `RegistryFile` is the editable list behind the world-model API,
a JSON file whose location the caller passes in. Adding or removing an entry never touches the
project's folder.
"""

import json
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Protocol

from core.errors import Conflict, NotFound
from core.project_file import ProjectFile, ProjectFileError, load_project_file


class Registered(Protocol):
    @property
    def file(self) -> Path: ...
    @property
    def slug(self) -> str: ...


class ProjectRegistry[P: Registered]:
    """The projects known, in registration order. Immutable once built."""

    def __init__(self, projects: Sequence[P]) -> None:
        seen: dict[str, P] = {}
        for project in projects:
            if project.slug in seen:
                raise ProjectFileError(
                    f"{project.file}: key 'slug': {project.slug!r} is already used by "
                    f"{seen[project.slug].file}"
                )
            seen[project.slug] = project
        self._projects = tuple(projects)

    @property
    def projects(self) -> tuple[P, ...]:
        return self._projects

    def get(self, slug: str) -> P:
        for project in self._projects:
            if project.slug == slug:
                return project
        known = ", ".join(p.slug for p in self._projects) or "none registered"
        raise ProjectFileError(f"no project with slug {slug!r} (registered: {known})")


def unique_files(files: Iterable[Path]) -> list[Path]:
    """Each project file once, by its resolved path, in first-seen order."""
    return list(dict.fromkeys(f.expanduser().resolve() for f in files))


@dataclass(frozen=True)
class Entry:
    """One registered project. `project` is None when its file cannot be loaded now (the folder
    was moved or the file broken); `problem` then says why. The slug is kept in the registry file
    so a broken entry can still be named and removed."""

    slug: str
    file: Path
    project: ProjectFile | None
    problem: str | None


class RegistryFile:
    """The editable list of world-model projects, persisted at `path` as
    `{"projects": [{"slug": ..., "file": ...}]}`. A missing file is an empty list. Every change
    rewrites the file whole (a temporary file, then a rename)."""

    def __init__(self, path: Path, load: Callable[[Path], ProjectFile] = load_project_file) -> None:
        self.path = path
        self._load = load
        self._lock = RLock()

    def _read(self) -> list[tuple[str, Path]]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise ProjectFileError(f"{self.path}: cannot read as JSON ({error})") from error
        entries = raw.get("projects") if isinstance(raw, dict) else None
        if not isinstance(entries, list):
            raise ProjectFileError(f"{self.path}: key 'projects': expected a list")
        rows: list[tuple[str, Path]] = []
        for i, entry in enumerate(entries):
            if (
                not isinstance(entry, dict)
                or not isinstance(entry.get("slug"), str)
                or not isinstance(entry.get("file"), str)
            ):
                raise ProjectFileError(
                    f'{self.path}: key \'projects[{i}]\': expected {{"slug": ..., "file": ...}}'
                )
            rows.append((entry["slug"], Path(entry["file"])))
        return rows

    def entries(self) -> list[Entry]:
        """Every registered project, loaded now (files may have changed on disk)."""
        result = []
        for slug, file in self._read():
            try:
                project = self._load(file)
            except ProjectFileError as error:
                result.append(Entry(slug, file, None, error.message))
                continue
            if project.slug != slug:
                problem = (
                    f"{project.file}: key 'slug': {project.slug!r}, but it was registered as "
                    f"{slug!r}; remove and open it again"
                )
                result.append(Entry(slug, file, None, problem))
                continue
            result.append(Entry(slug, file, project, None))
        return result

    def get(self, slug: str) -> ProjectFile:
        """The loaded project with this slug; raises if unknown or if it cannot be loaded."""
        for entry in self.entries():
            if entry.slug == slug:
                if entry.project is None:
                    raise ProjectFileError(entry.problem or f"project {slug!r} cannot be loaded")
                return entry.project
        known = ", ".join(e.slug for e in self.entries()) or "none registered"
        raise NotFound(f"no project with slug {slug!r} (registered: {known})", field="/slug")

    def add(self, file: Path) -> ProjectFile:
        """Register one project file. Refused if that file or its slug is already registered."""
        with self._lock:
            project = self._load(file)
            rows = self._read()
            for slug, existing in rows:
                if existing.expanduser().resolve() == project.file:
                    raise Conflict(f"{project.file}: already registered", "already_registered")
                if slug == project.slug:
                    raise Conflict(
                        f"{project.file}: key 'slug': {slug!r} is already used by {existing}",
                        "slug_taken",
                        "/slug",
                    )
            self._write([*rows, (project.slug, project.file)])
            return project

    def remove(self, slug: str) -> Path:
        """Unregister the project with this slug and return its project file path. The folder and
        its files are left exactly as they are."""
        with self._lock:
            rows = self._read()
            kept = [row for row in rows if row[0] != slug]
            if len(kept) == len(rows):
                raise NotFound(f"no project with slug {slug!r}", field="/slug")
            self._write(kept)
            return next(file for s, file in rows if s == slug)

    def _write(self, rows: list[tuple[str, Path]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        body = {"projects": [{"slug": slug, "file": str(file)} for slug, file in rows]}
        temporary.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)
