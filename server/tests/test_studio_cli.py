"""`studio export` on a temporary project and runs root: the bundle, the zip, a since-export and a
refusal. --runs-root is always given, so the machine config is never read."""

import json
import zipfile
from pathlib import Path

import pytest

from export.tests.support import make_scene
from tools.studio import main


def test_export_writes_a_bundle_a_zip_and_a_since_bundle(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    scene = make_scene(tmp_path)
    project = str(scene.world.project.file)
    runs = str(scene.runs)
    first = tmp_path / "first"
    args = ["export", "--project", project, "--out", str(first), "--runs-root", runs]
    assert main([*args, "--zip", str(tmp_path / "first.zip")]) == 0
    assert "Exported 3 entities, 3 assets, 1 links" in capsys.readouterr().out
    manifest = json.loads((first / "manifest.json").read_text(encoding="utf-8"))
    with zipfile.ZipFile(tmp_path / "first.zip") as archive:
        assert archive.read("manifest.json") == (first / "manifest.json").read_bytes()

    scene.world.archive_entity(scene.hall["id"], scene.hall["revision"])
    since = ["--since", str(first / "manifest.json"), "--kind", "setting"]
    second = [
        "export",
        "--project",
        project,
        "--out",
        str(tmp_path / "second"),
        "--runs-root",
        runs,
    ]
    assert main([*second, *since]) == 0
    assert "Archived or gone since the earlier bundle: 1" in capsys.readouterr().out
    assert len(manifest["entities"]) == 3


def test_export_refuses_a_folder_that_is_not_empty(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    scene = make_scene(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    (out / "something").write_text("x")
    args = ["export", "--project", str(scene.world.project.file), "--out", str(out)]
    assert main([*args, "--runs-root", str(scene.runs)]) == 1
    assert "studio export:" in capsys.readouterr().err
