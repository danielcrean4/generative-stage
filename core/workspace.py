"""The projects a person works on: create, open (register), list, remove, and open one as a World.

A new project is a folder holding the project file, a copy of the default kinds (setting,
character, prop and their link types) in `kinds/`, and its SQLite store. Removing a project
only takes it off the registry; its folder is never touched.
"""

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from core.errors import BadProjectFiles, Conflict, Invalid
from core.ids import SLUG
from core.kinds import load_catalogue
from core.project_file import ProjectFile, write_project_file
from core.registry import Entry, RegistryFile
from core.store import WorldStore
from core.world import World

TEMPLATES = Path(__file__).parent / "templates" / "kinds"
KINDS_FOLDER = "kinds"


def describe(project: ProjectFile) -> dict[str, Any]:
    return {
        "slug": project.slug,
        "name": project.name,
        "folder": str(project.root),
        "project_file": str(project.file),
        "schema_dir": str(project.schema_dir) if project.schema_dir else None,
        "pipelines": [str(p) for p in project.pipelines],
        "store": str(project.store),
    }


def describe_entry(entry: Entry) -> dict[str, Any]:
    if entry.project is not None:
        return {**describe(entry.project), "problem": None}
    return {"slug": entry.slug, "project_file": str(entry.file), "problem": entry.problem}


class Workspace:
    def __init__(
        self,
        registry: RegistryFile,
        run_exists: Callable[[str], bool] | None = None,
        templates: Path = TEMPLATES,
    ) -> None:
        self.registry = registry
        self._run_exists = run_exists
        self._templates = templates

    def projects(self) -> list[dict[str, Any]]:
        """Every registered project; one that cannot be loaded is listed with its problem."""
        return [describe_entry(entry) for entry in self.registry.entries()]

    def project(self, slug: str) -> dict[str, Any]:
        return describe(self.registry.get(slug))

    def create(self, folder: object, slug: object, name: object) -> dict[str, Any]:
        """Make a new project in `folder` (absolute; missing or empty) and register it."""
        if not isinstance(slug, str) or not SLUG.fullmatch(slug):
            raise Invalid(
                "/slug: use 1-49 lowercase letters, digits or hyphens, starting with a letter",
                field="/slug",
            )
        if not isinstance(name, str) or not name.strip() or len(name) > 160:
            raise Invalid("/name: expected a name of 1 to 160 characters", field="/name")
        if not isinstance(folder, str) or not Path(folder).is_absolute():
            raise Invalid("/folder: expected an absolute folder path", field="/folder")
        root = Path(folder)
        if root.exists() and (not root.is_dir() or any(root.iterdir())):
            raise Conflict(
                f"/folder: {root} exists and is not an empty folder", "folder_not_empty", "/folder"
            )
        if any(entry.slug == slug for entry in self.registry.entries()):
            raise Conflict(f"/slug: {slug!r} is already registered", "slug_taken", "/slug")
        root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(self._templates, root / KINDS_FOLDER)
        file = write_project_file(root, slug, name.strip(), KINDS_FOLDER)
        project = self.registry.add(file)
        self.open(slug)  # creates the store and proves the kinds load
        return describe(project)

    def register(self, project_file: object) -> dict[str, Any]:
        """Register an existing project. Its project file and kinds must load."""
        if not isinstance(project_file, str) or not Path(project_file).is_absolute():
            raise Invalid(
                "/project_file: expected an absolute path to a project file", field="/project_file"
            )
        project = self.registry.add(Path(project_file))
        try:
            self.open(project.slug)
        except BadProjectFiles:
            self.registry.remove(project.slug)
            raise
        return describe(project)

    def remove(self, slug: str) -> dict[str, Any]:
        file = self.registry.remove(slug)
        return {"slug": slug, "project_file": str(file), "removed": True}

    def open(self, slug: str) -> World:
        """The project as a World. Kinds are read from disk each time, so edits apply at once."""
        return open_world(self.registry.get(slug), self._run_exists)


def open_world(project: ProjectFile, run_exists: Callable[[str], bool] | None = None) -> World:
    """One loaded project file as a World, registered or not (a command line names the file)."""
    if project.schema_dir is None:
        raise BadProjectFiles(
            f"{project.file}: key 'schema_dir': missing (the world model reads kinds from it)",
            "bad_project_file",
        )
    catalogue = load_catalogue(project.schema_dir)
    return World(project, catalogue, WorldStore(project.store), run_exists)
