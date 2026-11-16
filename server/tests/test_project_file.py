"""Project files with docs: the keys the docs view reads, and a bad one names its key."""

import json
from pathlib import Path

import pytest

from core.project_file import PROJECT_FILE_NAME, ProjectFileError, load_project_file
from core.registry import ProjectRegistry

SECOND = Path(__file__).parent / "fixtures/docs_fixture"


def write_project(folder: Path, raw: object) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    file = folder / PROJECT_FILE_NAME
    file.write_text(json.dumps(raw))
    return file


def test_fixture_project_loads() -> None:
    project = load_project_file(SECOND / PROJECT_FILE_NAME)
    assert (project.slug, project.name, project.root) == (
        "docs-fixture",
        "Docs Fixture",
        SECOND.resolve(),
    )
    assert project.docs_roots == ((SECOND / "docs").resolve(),)
    assert project.source_allowlist == ((SECOND / "docs").resolve(),)
    assert project.docs_files == () and project.schema_dir is None
    assert (project.docs_roots[0] / "overview.md").is_file()


def test_docs_files_must_be_markdown(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Readme")
    (tmp_path / "notes.txt").write_text("notes")
    good = write_project(tmp_path, {"slug": "tiny", "name": "Tiny", "docs_files": ["README.md"]})
    assert load_project_file(good).docs_files == ((tmp_path / "README.md").resolve(),)
    bad = write_project(tmp_path, {"slug": "tiny", "name": "Tiny", "docs_files": ["notes.txt"]})
    with pytest.raises(ProjectFileError, match=r"key 'docs_files\[0\]': must be a markdown"):
        load_project_file(bad)


def test_duplicate_slug_is_rejected(tmp_path: Path) -> None:
    other = write_project(tmp_path / "a", {"slug": "docs-fixture", "name": "Copy"})
    with pytest.raises(ProjectFileError, match="key 'slug': 'docs-fixture' is already used"):
        ProjectRegistry([load_project_file(SECOND / PROJECT_FILE_NAME), load_project_file(other)])


@pytest.mark.parametrize(
    "change, key",
    [
        ({"colour": "red"}, "colour"),
        ({"engine": "custom"}, "engine"),
        ({"docs_roots": "docs"}, "docs_roots"),
        ({"docs_roots": ["nowhere"]}, r"docs_roots\[0\]"),
        ({"docs_roots": ["../outside"]}, r"docs_roots\[0\]"),
        ({"docs_roots": [".git"]}, r"docs_roots\[0\]"),
        ({"source_allowlist": [3]}, r"source_allowlist\[0\]"),
        ({"docs_files": ["missing.md"]}, r"docs_files\[0\]"),
    ],
)
def test_bad_docs_key_names_the_key(tmp_path: Path, change: dict[str, object], key: str) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path.parent / "outside").mkdir(exist_ok=True)
    file = write_project(tmp_path, {"slug": "tiny", "name": "Tiny", **change})
    with pytest.raises(ProjectFileError, match=rf"{PROJECT_FILE_NAME}: key '{key}'"):
        load_project_file(file)


def test_external_docs_take_absolute_folders_outside_the_project(tmp_path: Path) -> None:
    other = tmp_path / "other" / "docs"
    other.mkdir(parents=True)
    file = write_project(
        tmp_path / "p", {"slug": "tiny", "name": "Tiny", "external_docs": [str(other)]}
    )
    assert load_project_file(file).external_docs == (other.resolve(),)
    assert (
        load_project_file(write_project(tmp_path / "q", {"slug": "q", "name": "Q"})).external_docs
        == ()
    )


@pytest.mark.parametrize("kind", ["missing", "relative", "file", "not_a_list"])
def test_external_docs_are_refused_when_wrong(tmp_path: Path, kind: str) -> None:
    (tmp_path / "note.md").write_text("# Note")
    value: object = {
        "missing": [str(tmp_path / "nowhere")],
        "relative": ["docs"],
        "file": [str(tmp_path / "note.md")],
        "not_a_list": str(tmp_path),
    }[kind]
    file = write_project(tmp_path / "p", {"slug": "tiny", "name": "Tiny", "external_docs": value})
    with pytest.raises(ProjectFileError, match=rf"{PROJECT_FILE_NAME}: key 'external_docs"):
        load_project_file(file)
