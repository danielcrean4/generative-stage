"""The export bundle: what the manifest holds, determinism, selection, and the refusals."""

import copy
import hashlib
import json
import os
import re
import zipfile
from pathlib import Path

import pytest

from core.errors import Conflict, Invalid, NotFound
from export.bundle import (
    MANIFEST,
    Selection,
    manifest_text,
    plan_bundle,
    since_from_manifest,
    validate_manifest,
    write_bundle,
    write_zip,
)
from export.provenance import read_provenance
from export.tests.support import ATTEMPT, GLB, PNG, RUN_KEY, Scene, make_scene


@pytest.fixture
def scene(tmp_path: Path) -> Scene:
    return make_scene(tmp_path)


def files_of(folder: Path) -> dict[str, bytes]:
    return {
        p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*") if p.is_file()
    }


def test_full_export_holds_entities_links_assets_and_provenance(
    scene: Scene, tmp_path: Path
) -> None:
    out = write_bundle(plan_bundle(scene.world, scene.runs), tmp_path / "bundle")
    manifest = json.loads((out / MANIFEST).read_text())
    validate_manifest(manifest)
    assert manifest["format_version"] == 1
    assert manifest["project"] == {"slug": "sample-project", "name": "Sample Project"}
    assert [k["id"] for k in manifest["kinds"]] == ["character", "prop", "script", "setting"]
    assert all("family" not in k and "form" not in k for k in manifest["kinds"])
    assert all("schema" in k and "schema_file" not in k for k in manifest["kinds"])
    assert {e["id"] for e in manifest["entities"]} == {
        scene.hall["id"],
        scene.guide["id"],
        scene.key["id"],
    }
    key = next(e for e in manifest["entities"] if e["id"] == scene.key["id"])
    assert key["data"]["name"] == "Key" and key["revision"] == 1
    main, icon = key["assets"]["main"], key["assets"]["icon"]
    assert main["path"] == f"assets/prop/{scene.key['id']}/main.glb"
    assert main["media_type"] == "model/gltf-binary" and icon["media_type"] == "image/png"
    assert main["sha256"] == hashlib.sha256(GLB).hexdigest() and main["bytes"] == len(GLB)
    assert (out / main["path"]).read_bytes() == GLB and (out / icon["path"]).read_bytes() == PNG
    assert main["provenance"] == {
        "run_id": RUN_KEY,
        "candidate": f"attempts/{ATTEMPT}/mesh/mesh.glb",
        "attempt": ATTEMPT,
        "stage": "mesh",
        "prompt": "a heavy key",
        "seed": 12,
        "entity_revision": 1,
        "chosen_at": main["provenance"]["chosen_at"],
        "models": {
            "concept": {
                "adapter_id": "standin-image",
                "adapter_version": 1,
                "weights_sha256": "ab" * 32,
            },
            "mesh": {"model": "standin-mesh", "weights_sha256": "cd" * 32},
        },
    }
    assert icon["provenance"]["prompt"] == "a heavy key on a white ground"  # the recipe's prompt
    assert icon["provenance"]["seed"] == 11
    guide = next(e for e in manifest["entities"] if e["id"] == scene.guide["id"])
    portrait = guide["assets"]["main"]["provenance"]
    assert set(portrait) == {
        "run_id",
        "candidate",
        "entity_revision",
        "chosen_at",
    }  # nothing invented
    assert manifest["links"] == [
        {
            "id": manifest["links"][0]["id"],
            "type": "found_in",
            "source": scene.key["id"],
            "target": scene.hall["id"],
        }
    ]
    assert "removed" not in manifest


def test_no_absolute_path_reaches_the_manifest(scene: Scene, tmp_path: Path) -> None:
    text = manifest_text(plan_bundle(scene.world, scene.runs).manifest)
    assert "/somewhere" not in text and str(tmp_path) not in text
    assert not re.search(r'"/', text)


def test_same_inputs_give_the_same_bytes(scene: Scene, tmp_path: Path) -> None:
    first = write_bundle(plan_bundle(scene.world, scene.runs), tmp_path / "one")
    second = write_bundle(plan_bundle(scene.world, scene.runs), tmp_path / "two")
    assert files_of(first) == files_of(second)
    zip_one = write_zip(first, tmp_path / "one.zip").read_bytes()
    os.utime(second / MANIFEST, (1, 1))  # file times on disk never reach the zip
    assert zip_one == write_zip(second, tmp_path / "two.zip").read_bytes()
    with zipfile.ZipFile(tmp_path / "one.zip") as archive:
        names = archive.namelist()
        assert names == sorted(names) and MANIFEST in names
        assert {info.date_time for info in archive.infolist()} == {(1980, 1, 1, 0, 0, 0)}


def test_select_by_kind_and_tag(scene: Scene) -> None:
    by_kind = plan_bundle(scene.world, scene.runs, Selection(kinds=("prop",))).manifest
    assert [e["id"] for e in by_kind["entities"]] == [scene.key["id"]]
    assert by_kind["selection"] == {"kinds": ["prop"], "tags": [], "since": None}
    by_tag = plan_bundle(scene.world, scene.runs, Selection(tags=("outdoor",))).manifest
    assert {e["id"] for e in by_tag["entities"]} == {scene.key["id"], scene.hall["id"]}
    both = plan_bundle(scene.world, scene.runs, Selection(kinds=("setting",), tags=("crew",)))
    assert both.manifest["entities"] == []
    with pytest.raises(Invalid, match="no kind 'ship'"):
        plan_bundle(scene.world, scene.runs, Selection(kinds=("ship",)))


def test_changed_since_an_earlier_bundle(scene: Scene) -> None:
    earlier = plan_bundle(scene.world, scene.runs).manifest
    since = since_from_manifest(earlier)
    assert plan_bundle(scene.world, scene.runs, Selection(since=since)).manifest["entities"] == []
    world = scene.world
    world.update_entity(scene.key["id"], 1, {"name": "Key", "brief": "Edited."})
    world.archive_entity(scene.guide["id"], 1)
    rope = world.create_entity("prop", {"name": "Coil of rope"})
    later = plan_bundle(world, scene.runs, Selection(since=since)).manifest
    assert sorted(e["id"] for e in later["entities"]) == sorted([scene.key["id"], rope["id"]])
    assert next(e for e in later["entities"] if e["id"] == scene.key["id"])["revision"] == 2
    assert later["removed"] == [scene.guide["id"]]
    assert later["selection"]["since"] == dict(sorted(since.items()))


def test_archived_entities_and_their_links_stay_out(scene: Scene) -> None:
    scene.world.archive_entity(scene.hall["id"], 1)
    manifest = plan_bundle(scene.world, scene.runs).manifest
    assert scene.hall["id"] not in {e["id"] for e in manifest["entities"]}
    assert manifest["links"] == []


@pytest.mark.parametrize(
    "candidate",
    ["../run-guide/portrait.png", "/etc/hosts", f"attempts/{ATTEMPT}/../../x", "missing.glb", ""],
)
def test_candidates_outside_the_run_are_refused(scene: Scene, candidate: str) -> None:
    store = scene.world.store
    with store._transaction() as db:  # a choice written behind the world's checks
        db.execute(
            "INSERT INTO entity_choices(entity_id, slot, run_id, candidate, entity_revision, note,"
            " chosen_at) VALUES(?,?,?,?,?,?,?)",
            (scene.hall["id"], "main", RUN_KEY, candidate, 1, "", "2026-11-01T00:00:00Z"),
        )
    with pytest.raises(NotFound, match="is not a file in that run"):
        plan_bundle(scene.world, scene.runs)


def test_a_symlink_out_of_the_run_is_refused(scene: Scene, tmp_path: Path) -> None:
    secret = tmp_path / "secret.png"
    secret.write_bytes(PNG)
    (scene.runs / RUN_KEY / "escape.png").symlink_to(secret)
    scene.world.choose(scene.hall["id"], RUN_KEY, "escape.png")
    with pytest.raises(NotFound):
        plan_bundle(scene.world, scene.runs)


def test_the_schema_catches_a_bad_manifest(scene: Scene) -> None:
    manifest = plan_bundle(scene.world, scene.runs).manifest
    broken = copy.deepcopy(manifest)
    broken["entities"][0]["revision"] = 0
    with pytest.raises(Invalid, match="/entities/0/revision"):
        validate_manifest(broken)
    broken = copy.deepcopy(manifest)
    broken["format_version"] = 2
    with pytest.raises(Invalid):
        validate_manifest(broken)


def test_a_bundle_goes_only_into_an_empty_folder(scene: Scene, tmp_path: Path) -> None:
    out = tmp_path / "full"
    out.mkdir()
    (out / "keep.txt").write_text("mine")
    with pytest.raises(Conflict):
        write_bundle(plan_bundle(scene.world, scene.runs), out)
    assert files_of(out) == {"keep.txt": b"mine"}


def test_a_mesh_takes_the_prompt_of_the_stage_that_drew_it(tmp_path: Path) -> None:
    """The runner's attempt record: stages keyed by folder, the prompt only on the concept stage."""
    attempt = tmp_path / "runs" / "run-lamp" / "attempts" / "20261102T000000Z-bbbb0002"
    (attempt / "mesh").mkdir(parents=True)
    (attempt / "mesh" / "mesh.glb").write_bytes(b"glTF")
    record = {
        "stages": {
            "concept": {"stage": "concept", "seed": 5, "prompt": "steel lamp, white background"},
            "mesh": {"stage": "mesh", "seed": 6},
        },
        "models": {"mesh": {"adapter_id": "standin-mesh", "adapter_version": 2}},
    }
    (attempt / "attempt.json").write_text(json.dumps(record), encoding="utf-8")
    choice = {
        "run_id": "run-lamp",
        "candidate": "attempts/20261102T000000Z-bbbb0002/mesh/mesh.glb",
        "entity_revision": 1,
        "chosen_at": "2026-11-02T00:00:00Z",
    }
    found = read_provenance(tmp_path / "runs", choice).record
    assert found["prompt"] == "steel lamp, white background"
    assert found["seed"] == 6 and found["stage"] == "mesh"
    assert found["models"] == {"mesh": {"adapter_id": "standin-mesh", "adapter_version": 2}}


def test_identity_reads_the_adapter_id_the_runner_records() -> None:
    from export.provenance import identity

    record = {"adapter": "standin-image", "kind": "image", "model": "standin", "files_sha256": {}}
    assert identity(record) == {"model": "standin", "adapter_id": "standin-image"}
    assert identity({"adapter": "/opt/bin/tool"}) == {}  # a path is never shown
