"""The Godot example lays a bundle out as files, without Godot."""

import json
from pathlib import Path

import pytest

from export.bundle import MANIFEST, plan_bundle, write_bundle, write_zip
from export.engines.godot_example.godot_import import ImportProblem, import_any, main, target_name
from export.tests.support import GLB, PNG, make_scene


@pytest.fixture
def bundle(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    scene = make_scene(tmp_path)
    out = write_bundle(plan_bundle(scene.world, scene.runs), tmp_path / "bundle")
    return out, {"key": scene.key["id"], "guide": scene.guide["id"]}


def test_target_names() -> None:
    assert (
        target_name("prop", "k1", "main", "model/gltf-binary", "a/main.glb") == "models/prop/k1.glb"
    )
    assert target_name("prop", "k1", "icon", "image/png", "a/icon.png") == "images/prop/k1_icon.png"
    assert (
        target_name("prop", "k1", "main", "application/json", "a/main.json") == "files/prop/k1.json"
    )


def test_layout_and_index(bundle: tuple[Path, dict[str, str]], tmp_path: Path) -> None:
    source, ids = bundle
    target = tmp_path / "godot" / "world"
    assert main([str(source), str(target), "--res-prefix", "res://world"]) == 0
    key = ids["key"]
    assert (target / "models/prop" / f"{key}.glb").read_bytes() == GLB
    assert (target / "images/prop" / f"{key}_icon.png").read_bytes() == PNG
    assert (target / "images/character" / f"{ids['guide']}.png").is_file()
    index = json.loads((target / "index.json").read_text())
    entry = next(e for e in index["entities"] if e["id"] == key)
    assert entry["files"] == {
        "main": f"res://world/models/prop/{key}.glb",
        "icon": f"res://world/images/prop/{key}_icon.png",
    }
    assert entry["data"]["name"] == "Key" and len(index["links"]) == 1
    assert sorted(p.name for p in target.iterdir()) == ["images", "index.json", "models"]


def test_a_zip_gives_the_same_layout(bundle: tuple[Path, dict[str, str]], tmp_path: Path) -> None:
    source, _ = bundle
    from_folder = import_any(source, tmp_path / "a")
    from_zip = import_any(write_zip(source, tmp_path / "b.zip"), tmp_path / "b")
    assert from_folder == from_zip


def test_a_changed_file_stops_the_import(
    bundle: tuple[Path, dict[str, str]], tmp_path: Path
) -> None:
    source, ids = bundle
    (source / "assets/prop" / ids["key"] / "main.glb").write_bytes(b"tampered")
    with pytest.raises(ImportProblem, match="sha256"):
        import_any(source, tmp_path / "out")
    assert main([str(source), str(tmp_path / "out2")]) == 1


def test_refuses_a_bundle_path_that_leaves_it(
    bundle: tuple[Path, dict[str, str]], tmp_path: Path
) -> None:
    source, _ = bundle
    manifest = json.loads((source / MANIFEST).read_text())
    manifest["entities"][0]["assets"] = {
        "main": {
            "path": "../outside.glb",
            "media_type": "model/gltf-binary",
            "sha256": "0" * 64,
            "bytes": 0,
            "provenance": {},
        }
    }
    (source / MANIFEST).write_text(json.dumps(manifest))
    with pytest.raises(ImportProblem, match="leaves the bundle"):
        import_any(source, tmp_path / "out")


def test_refuses_a_non_empty_target(bundle: tuple[Path, dict[str, str]], tmp_path: Path) -> None:
    source, _ = bundle
    (tmp_path / "busy").mkdir()
    (tmp_path / "busy" / "x").write_text("x")
    with pytest.raises(ImportProblem, match="not an empty folder"):
        import_any(source, tmp_path / "busy")


def test_the_example_holds_no_project_content() -> None:
    folder = Path(__file__).resolve().parents[1] / "engines" / "godot_example"
    names = sorted(p.name for p in folder.iterdir() if p.name != "__pycache__")
    assert names == ["README.md", "__init__.py", "godot_import.py"]


def test_only_the_bundle_format_id_is_read(bundle: tuple[Path, dict[str, str]], tmp_path: Path) -> None:
    source, _ = bundle
    manifest = json.loads((source / MANIFEST).read_text())
    assert manifest["format"] == "generative-stage-bundle"  # what the tool writes
    assert main([str(source), str(tmp_path / "bundle-id")]) == 0
    manifest["format"] = "other-bundle"
    (source / MANIFEST).write_text(json.dumps(manifest))
    assert main([str(source), str(tmp_path / "other-id")]) == 1
