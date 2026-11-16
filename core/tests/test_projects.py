"""Projects: the project file, the editable registry and the workspace that creates projects."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from core.errors import BadProjectFiles, Conflict, Invalid, NotFound
from core.project_file import PROJECT_FILE_NAME, ProjectFileError, load_project_file
from core.registry import ProjectRegistry, RegistryFile
from core.workspace import Workspace

REPO = Path(__file__).resolve().parents[2]


def test_create_makes_a_folder_with_kinds_and_a_store(workspace: Workspace, tmp_path: Path) -> None:
    folder = tmp_path / "sample"
    project = workspace.create(str(folder), "sample", "Sample Project")
    assert project["slug"] == "sample"
    assert (folder / PROJECT_FILE_NAME).is_file()
    assert sorted(p.name for p in (folder / "kinds").iterdir()) == [
        "character.schema.json",
        "kinds.json",
        "link_types.json",
        "prop.schema.json",
        "script.schema.json",
        "setting.schema.json",
    ]
    assert (folder / "world.sqlite3").is_file()
    assert [p["slug"] for p in workspace.projects()] == ["sample"]
    assert [k["id"] for k in workspace.open("sample").kinds()] == [
        "setting",
        "character",
        "prop",
        "script",
    ]


def test_create_refuses_bad_input(workspace: Workspace, tmp_path: Path) -> None:
    with pytest.raises(Invalid) as caught:
        workspace.create(str(tmp_path / "a"), "Bad Slug", "A")
    assert caught.value.field == "/slug"
    with pytest.raises(Invalid) as caught:
        workspace.create("relative/folder", "a", "A")
    assert caught.value.field == "/folder"
    (tmp_path / "full").mkdir()
    (tmp_path / "full" / "keep.txt").write_text("mine")
    with pytest.raises(Conflict) as conflict:
        workspace.create(str(tmp_path / "full"), "full", "Full")
    assert conflict.value.code == "folder_not_empty"
    workspace.create(str(tmp_path / "one"), "same", "One")
    with pytest.raises(Conflict) as conflict:
        workspace.create(str(tmp_path / "two"), "same", "Two")
    assert conflict.value.code == "slug_taken"
    assert not (tmp_path / "two").exists()


def test_remove_unregisters_and_keeps_the_folder(workspace: Workspace, tmp_path: Path) -> None:
    folder = tmp_path / "sample"
    workspace.create(str(folder), "sample", "Sample Project")
    workspace.open("sample").create_entity("prop", {"name": "Key"})
    workspace.remove("sample")
    assert workspace.projects() == []
    assert (folder / PROJECT_FILE_NAME).is_file() and (folder / "world.sqlite3").is_file()
    with pytest.raises(NotFound):
        workspace.open("sample")
    with pytest.raises(NotFound):
        workspace.remove("sample")
    # Opening it again finds the same entities.
    workspace.register(str(folder / PROJECT_FILE_NAME))
    assert [e["title"] for e in workspace.open("sample").list_entities()] == ["Key"]


def test_register_refuses_twice_and_bad_kinds(workspace: Workspace, tmp_path: Path) -> None:
    folder = tmp_path / "sample"
    workspace.create(str(folder), "sample", "Sample Project")
    with pytest.raises(Conflict) as conflict:
        workspace.register(str(folder / PROJECT_FILE_NAME))
    assert conflict.value.code == "already_registered"
    workspace.remove("sample")
    (folder / "kinds" / "prop.schema.json").write_text("{")
    with pytest.raises(BadProjectFiles, match="prop.schema.json: not valid JSON"):
        workspace.register(str(folder / PROJECT_FILE_NAME))
    assert workspace.projects() == []


def test_a_moved_project_is_listed_with_its_problem(workspace: Workspace, tmp_path: Path) -> None:
    folder = tmp_path / "sample"
    workspace.create(str(folder), "sample", "Sample Project")
    folder.rename(tmp_path / "moved")
    [entry] = workspace.projects()
    assert entry["slug"] == "sample" and "cannot read" in entry["problem"]
    with pytest.raises(ProjectFileError):
        workspace.open("sample")
    workspace.remove("sample")  # a broken entry can still be removed
    assert workspace.projects() == []


def test_project_file_keys_are_checked(tmp_path: Path) -> None:
    file = tmp_path / PROJECT_FILE_NAME
    cases: list[tuple[dict[str, object], str]] = [
        ({"name": "A"}, "key 'slug': missing"),
        ({"slug": "a", "name": "A", "colour": "red"}, "key 'colour': unknown key"),
        ({"slug": "A", "name": "A"}, "key 'slug'"),
        ({"slug": "a", "name": ""}, "key 'name'"),
        ({"slug": "a", "name": "A", "schema_dir": "nowhere"}, "key 'schema_dir'"),
        ({"slug": "a", "name": "A", "store": "../outside.sqlite3"}, "key 'store'.*outside"),
        ({"slug": "a", "name": "A", "pipelines": ["missing.json"]}, r"key 'pipelines\[0\]'"),
    ]
    for raw, message in cases:
        file.write_text(json.dumps(raw))
        with pytest.raises(ProjectFileError, match=f"{PROJECT_FILE_NAME}: {message}"):
            load_project_file(file)
    file.write_text(json.dumps({"slug": "a", "name": "A", "engine": "x"}))
    assert load_project_file(file, extra_keys=("engine",)).extra == {"engine": "x"}


def test_registry_rules(tmp_path: Path) -> None:
    for name in ("a", "b"):
        (tmp_path / name).mkdir()
        (tmp_path / name / PROJECT_FILE_NAME).write_text(json.dumps({"slug": "same", "name": name}))
    first = load_project_file(tmp_path / "a" / PROJECT_FILE_NAME)
    second = load_project_file(tmp_path / "b" / PROJECT_FILE_NAME)
    with pytest.raises(ProjectFileError, match="'same' is already used"):
        ProjectRegistry([first, second])
    registry = RegistryFile(tmp_path / "registry.json")
    registry.add(tmp_path / "a" / PROJECT_FILE_NAME)
    with pytest.raises(Conflict, match="already used"):
        registry.add(tmp_path / "b" / PROJECT_FILE_NAME)
    (tmp_path / "registry.json").write_text('{"projects": [3]}')
    with pytest.raises(ProjectFileError, match=r"registry.json: key 'projects\[0\]'"):
        registry.entries()


def test_core_imports_without_the_server_or_game_code() -> None:
    script = (
        "import sys, core.workspace, core.world, core.kinds, core.store, core.registry\n"
        "bad = sorted(m for m in sys.modules if m.split('.')[0] in "
        "{'authoring', 'schemas', 'studio', 'tools', 'pipelines'})\n"
        "assert not bad, bad\n"
    )
    subprocess.run([sys.executable, "-c", script], cwd=REPO, check=True)
