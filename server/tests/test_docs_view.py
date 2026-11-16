"""The docs view: listing, reading, link classes, source windows, search and path safety."""

import json
import os
import time
from pathlib import Path

import pytest
from docs_project_fixture import SECRET, make_project

from authoring.docs_view import MAX_DOC_BYTES, DocsView
from authoring.run_view import NotFound
from core.project_file import PROJECT_FILE_NAME, ProjectFileError, load_project_file
from core.project_file import ProjectFile as Project

SECOND = Path(__file__).parent / "fixtures/docs_fixture"


@pytest.fixture
def project(tmp_path: Path) -> Project:
    return make_project(tmp_path)


@pytest.fixture
def view() -> DocsView:
    return DocsView()


def paths(tree: dict[str, object]) -> list[str]:
    out: list[str] = []
    for node in tree["children"]:  # type: ignore[attr-defined]
        out += paths(node) if node["type"] == "dir" else [node["path"]]
    return out


def test_list_is_a_tree_of_docs_only(view: DocsView, project: Project) -> None:
    listing = view.list_docs(project)
    assert sorted(paths(listing["tree"])) == [
        "README.md",
        "docs/deep/nested.md",
        "docs/guide.md",
        "docs/index.md",
    ]
    assert listing["count"] == 4
    top = [n["name"] for n in listing["tree"]["children"]]
    assert top == ["docs", "README.md"]  # folders first
    nested = next(n for n in listing["tree"]["children"][0]["children"][0]["children"])
    assert nested["title"] == "Nested" and nested["size"] > 0 and nested["modified"].endswith("Z")
    assert [(h["level"], h["text"]) for h in nested["headings"]] == [(1, "Nested"), (2, "Top")]
    guide = next(c for c in listing["tree"]["children"][0]["children"] if c["name"] == "guide.md")
    assert guide["title"] == "guide.md"  # no level-1 heading: the file name
    assert str(project.root) not in json.dumps(listing)


def test_read_returns_raw_text_outline_and_classified_links(
    view: DocsView, project: Project
) -> None:
    doc = view.read_doc(project, "docs/index.md")
    assert doc["text"].startswith("# Tmp Game") and doc["title"] == "Tmp Game"
    assert [h["text"] for h in doc["headings"]] == ["Tmp Game", "Links"]
    by_target = {link["target"]: link for link in doc["links"]}
    assert by_target["guide.md"]["kind"] == "doc" and by_target["guide.md"]["exists"] is True
    nested = by_target["deep/nested.md#top"]
    assert (nested["path"], nested["anchor"], nested["exists"]) == (
        "docs/deep/nested.md",
        "top",
        True,
    )
    assert (
        by_target["missing.md"]["exists"] is False
        and by_target["missing.md"]["path"] == "docs/missing.md"
    )
    code = by_target["../src/main.gd:12"]
    assert (code["kind"], code["path"], code["line"], code["allowed"], code["exists"]) == (
        "source",
        "src/main.gd",
        12,
        True,
        True,
    )
    assert by_target["/src/main.gd"]["path"] == "src/main.gd"
    assert by_target["../secret_src/key.txt"]["allowed"] is False
    assert by_target["../secret_src/key.txt"]["exists"] is True
    git = by_target["../.git/config"]
    assert git["kind"] == "source" and git["allowed"] is False and git["exists"] is False
    assert by_target["../../outside/secret.md"] == {
        **by_target["../../outside/secret.md"],
        "kind": "outside",
    }
    assert (
        by_target["../src/evil.gd"]["kind"] == "outside"
    )  # planted symlink resolves out of the repo
    assert by_target["https://example.com/a"] == {
        **by_target["https://example.com/a"],
        "kind": "external",
        "url": "https://example.com/a",
    }
    assert by_target["mailto:a@b.c"]["kind"] == "external"
    assert by_target["#links"] == {**by_target["#links"], "kind": "anchor", "anchor": "links"}
    assert by_target["javascript:void"]["kind"] == "unsupported"
    assert by_target["..%2Fsrc%2Fmain.gd"]["path"] == "src/main.gd"
    assert [link for link in doc["links"] if link["image"]][0]["path"] == "src/main.gd"
    assert not any(link["at"] > 14 for link in doc["links"])  # the fenced block holds no links
    assert (
        len([link for link in doc["links"] if link["target"] == "guide.md"]) == 2
    )  # inline and [ref]:
    assert SECRET not in json.dumps(doc) and str(project.root) not in json.dumps(doc)


def test_top_level_docs_files_are_docs(view: DocsView, project: Project) -> None:
    assert view.read_doc(project, "README.md")["links"][0]["path"] == "docs/index.md"


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "..",
        "../outside/secret.md",
        "docs/../../outside/secret.md",
        "/etc/passwd",
        "/docs/index.md",
        "docs//index.md",
        "docs/./index.md",
        "docs\\index.md",
        "docs/index.md\0",
        "%2e%2e/outside/secret.md",
        "..%2f..%2foutside%2fsecret.md",
        "%252e%252e/x.md",
        "docs/evil.md",
        "docs/outlink/secret.md",
        "docs/.hidden.md",
        ".git/config",
        "docs/notes.txt",
        "docs/missing.md",
        "src/main.gd",
        "docs",
        "docs/",
        "studio.project.json",
    ],
)
def test_read_doc_refuses_everything_not_listed(view: DocsView, project: Project, bad: str) -> None:
    with pytest.raises(NotFound) as caught:
        view.read_doc(project, bad)
    assert str(project.root) not in str(caught.value) and SECRET not in str(caught.value)


def test_planted_symlinks_are_not_listed_or_searched(view: DocsView, project: Project) -> None:
    listing = json.dumps(view.list_docs(project))
    assert "evil" not in listing and "outlink" not in listing and ".hidden" not in listing
    assert view.search([project], "TOPSECRET")["total_hits"] == 0


def test_a_symlinked_docs_root_is_rejected_at_load(tmp_path: Path) -> None:
    repo, outside = tmp_path / "repo", tmp_path / "outside"
    (repo / "data").mkdir(parents=True)
    outside.mkdir()
    (outside / "a.md").write_text("# a")
    (repo / "docs").symlink_to(outside, target_is_directory=True)
    file = repo / PROJECT_FILE_NAME
    file.write_text(
        json.dumps(
            {
                "slug": "s",
                "name": "S",
                "docs_roots": ["docs"],
            }
        )
    )
    with pytest.raises(ProjectFileError, match="docs_roots"):
        load_project_file(file)


def test_a_docs_root_swapped_for_a_symlink_after_load_serves_nothing(
    view: DocsView, project: Project
) -> None:
    docs = project.root / "docs"
    moved = project.root.parent / "moved"
    docs.rename(moved)
    docs.symlink_to(project.root.parent / "outside", target_is_directory=True)
    assert paths(view.list_docs(project)["tree"]) == ["README.md"]
    with pytest.raises(NotFound):
        view.read_doc(project, "docs/secret.md")


def test_oversize_doc_is_listed_but_not_read(view: DocsView, project: Project) -> None:
    (project.root / "docs/huge.md").write_text("x" * (MAX_DOC_BYTES + 1))
    assert "docs/huge.md" in paths(view.list_docs(project)["tree"])
    with pytest.raises(ValueError, match="larger"):
        view.read_doc(project, "docs/huge.md")


def test_source_window_is_centred_and_capped(view: DocsView, project: Project) -> None:
    window = view.read_source(project, "src/main.gd", line=150, window=21)
    assert (window["start"], window["end"], window["total_lines"]) == (140, 160, 300)
    assert window["lines"][10] == "line 150" and window["truncated"] is True
    head = view.read_source(project, "src/main.gd")
    assert (head["start"], head["end"], len(head["lines"])) == (1, 200, 200)
    tail = view.read_source(project, "src/main.gd", line=300, window=50)
    assert (tail["start"], tail["end"]) == (251, 300)
    small = view.read_source(project, "src/main.gd", line=2, window=10)
    assert (small["start"], small["end"]) == (1, 10)


@pytest.mark.parametrize(
    "bad",
    [
        "secret_src/key.txt",
        "src/evil.gd",
        ".git/config",
        "../outside/secret.txt",
        "/etc/passwd",
        "src/../secret_src/key.txt",
        "README.md",
        "src",
        "src/missing.gd",
        "docs/index.md",
        "data/x.json",
        "%2e%2e/x",
    ],
)
def test_source_outside_the_allowlist_is_refused(
    view: DocsView, project: Project, bad: str
) -> None:
    with pytest.raises(NotFound) as caught:
        view.read_source(project, bad)
    assert str(project.root) not in str(caught.value) and SECRET not in str(caught.value)


def test_source_refuses_binary_and_bad_numbers(view: DocsView, project: Project) -> None:
    with pytest.raises(ValueError, match="not a text file"):
        view.read_source(project, "src/blob.bin")
    with pytest.raises(ValueError):
        view.read_source(project, "src/main.gd", line=0)
    with pytest.raises(ValueError):
        view.read_source(project, "src/main.gd", window=100000)


def test_search_modes_context_and_ranking(view: DocsView, project: Project) -> None:
    result = view.search([project], "ratchet")
    assert result["docs_matched"] == 2 and result["total_hits"] == 3  # index (intro), guide x2
    assert {h["path"] for h in result["hits"]} == {"docs/index.md", "docs/guide.md"}
    guide_hit = next(h for h in result["hits"] if h["path"] == "docs/guide.md" and h["line"] == 5)
    assert guide_hit["heading"] == "Setup" and "ratchet" in guide_hit["excerpt"]
    assert guide_hit["title"] == "guide.md" and guide_hit["project"] == "tmp-game"
    word = view.search([project], "RATCHET", whole_word=True)
    assert word["total_hits"] == 2  # "ratcheting" no longer matches
    assert view.search([project], "qzxjvw")["hits"] == []
    assert view.search([project], "world state")["hits"][0]["path"] in {
        "docs/deep/nested.md",
        "docs/index.md",
    }
    cut = view.search([project], "ratchet", limit=1)
    assert len(cut["hits"]) == 1 and cut["truncated"] is True


def test_search_ranks_title_hits_then_heading_hits_first(view: DocsView, project: Project) -> None:
    (project.root / "docs/zzz.md").write_text("# Nested topic\n")
    (project.root / "docs/aaa.md").write_text("# Plain\n\nnested nested nested nested\n")
    (project.root / "docs/mmm.md").write_text("# Plain\n\n## nested heading\n\nnested\n")
    order = [h["path"] for h in view.search([project], "nested")["hits"]]
    firsts = list(dict.fromkeys(order))
    assert set(firsts[:2]) == {"docs/deep/nested.md", "docs/zzz.md"}  # title hits lead
    assert firsts.index("docs/mmm.md") < firsts.index("docs/aaa.md")  # heading hit beats raw count


@pytest.mark.parametrize("bad", ["", "   ", "x" * 500])
def test_search_refuses_bad_queries(view: DocsView, project: Project, bad: str) -> None:
    with pytest.raises(ValueError):
        view.search([project], bad)


def test_index_refreshes_when_a_file_changes(view: DocsView, project: Project) -> None:
    assert view.search([project], "freshword")["total_hits"] == 0
    guide = project.root / "docs/guide.md"
    guide.write_text("# Guide\n\nfreshword\n")
    later = time.time() + 5
    os.utime(guide, (later, later))
    assert view.search([project], "freshword")["total_hits"] == 1
    assert view.read_doc(project, "docs/guide.md")["title"] == "Guide"


def test_search_across_two_projects(view: DocsView, project: Project) -> None:
    other = load_project_file(SECOND / PROJECT_FILE_NAME)
    result = view.search([project, other], "tiny")
    assert {h["project"] for h in result["hits"]} == {"docs-fixture"}
    assert view.read_doc(other, "docs/overview.md")["title"] == "Docs Fixture"
    with pytest.raises(NotFound):
        view.read_doc(other, "docs/index.md")  # another project's doc is not reachable


def test_external_docs_are_listed_and_read_but_nothing_else_leaks(
    view: DocsView, project: Project, tmp_path: Path
) -> None:
    outside = tmp_path / "elsewhere" / "notes"
    (outside / "sub").mkdir(parents=True)
    (outside / "top.md").write_text("# Top\n\nSee [sub](sub/deep.md).\n")
    (outside / "sub" / "deep.md").write_text("# Deep\n")
    (outside / "plain.txt").write_text("not markdown")
    (outside / ".hidden.md").write_text("hidden")
    (outside / "leak.md").symlink_to(tmp_path / "outside" / "secret.md")
    file = project.root / PROJECT_FILE_NAME
    raw = json.loads(file.read_text())
    file.write_text(json.dumps({**raw, "external_docs": [str(outside)]}))
    shared = load_project_file(file)

    listed = view.doc_files(shared)
    assert sorted(p for p in listed if p.startswith("external/")) == [
        "external/notes/sub/deep.md",
        "external/notes/top.md",
    ]
    doc = view.read_doc(shared, "external/notes/top.md")
    assert doc["title"] == "Top"
    assert doc["links"][0]["kind"] == "doc" and doc["links"][0]["exists"] is True
    assert str(outside) not in json.dumps(view.list_docs(shared))
    with pytest.raises(NotFound):
        view.source_file(shared, "external/notes/top.md")
    assert SECRET not in json.dumps(view.search([shared], "secret"))


def test_two_external_folders_with_one_name_get_distinct_names(
    view: DocsView, project: Project, tmp_path: Path
) -> None:
    first, second = tmp_path / "a" / "docs", tmp_path / "b" / "docs"
    for folder in (first, second):
        folder.mkdir(parents=True)
        (folder / "one.md").write_text("# One")
    file = project.root / PROJECT_FILE_NAME
    raw = json.loads(file.read_text())
    file.write_text(json.dumps({**raw, "external_docs": [str(first), str(second)]}))
    found = view.doc_files(load_project_file(file))
    assert "external/docs/one.md" in found and "external/docs-2/one.md" in found
