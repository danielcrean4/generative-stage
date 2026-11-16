"""Entities, revisions, links and references to pipeline output, through World."""

import json
import threading
from pathlib import Path
from typing import Any

import pytest

from core.errors import Conflict, Invalid, NotFound
from core.registry import RegistryFile
from core.workspace import Workspace
from core.world import World


def make(world: World, kind: str, name: str, **fields: Any) -> dict[str, Any]:
    return world.create_entity(kind, {"name": name, **fields})


def test_create_read_update_keeps_every_revision(world: World) -> None:
    key = make(world, "prop", "Key", brief="Opens the storage room.", tags=["hall"])
    assert key["revision"] == 1 and key["title"] == "Key" and not key["archived"]
    assert world.get_entity(key["id"]) == key
    data = {**key["data"], "condition": "used"}
    updated = world.update_entity(key["id"], 1, data, "Edited")
    assert updated["revision"] == 2 and updated["data"]["condition"] == "used"
    history = world.revisions(key["id"])
    assert [(r["revision"], r["note"]) for r in history] == [(2, "Edited"), (1, "Created")]
    assert world.revision(key["id"], 1)["data"] == key["data"]
    with pytest.raises(NotFound):
        world.revision(key["id"], 9)
    with pytest.raises(NotFound):
        world.get_entity("not-an-id")


def test_ids_are_opaque_and_never_names(world: World) -> None:
    one = make(world, "character", "Guide")
    two = make(world, "character", "Guide")
    assert one["id"] != two["id"]
    assert "cart" not in one["id"].lower()


@pytest.mark.parametrize(
    "kind, data, field",
    [
        ("prop", {"brief": "no name"}, "/data/name"),
        ("prop", {"name": ""}, "/data/name"),
        ("prop", {"name": "Key", "size": "enormous"}, "/data/size"),
        ("prop", {"name": "Key", "tags": "hall"}, "/data/tags"),
        ("prop", {"name": "Key", "colour": "gold"}, "/data"),
        ("prop", ["not", "an", "object"], "/data"),
        ("vehicle", {"name": "Cart"}, "/kind"),
    ],
)
def test_invalid_entities_are_refused(world: World, kind: str, data: Any, field: str) -> None:
    with pytest.raises(Invalid) as caught:
        world.create_entity(kind, data)
    assert caught.value.field == field
    assert world.list_entities(include_archived=True) == []


def test_update_validates_and_needs_the_current_revision(world: World) -> None:
    key = make(world, "prop", "Key")
    with pytest.raises(Invalid):
        world.update_entity(key["id"], 1, {"brief": "lost its name"})
    world.update_entity(key["id"], 1, {"name": "Key", "material": "steel"})
    with pytest.raises(Conflict) as caught:
        world.update_entity(key["id"], 1, {"name": "Iron key"})
    assert caught.value.code == "revision_conflict" and caught.value.field == "/revision"
    assert world.get_entity(key["id"])["data"]["name"] == "Key"


def test_concurrent_updates_of_one_entity_let_exactly_one_win(world: World) -> None:
    key = make(world, "prop", "Key")
    results: list[str] = []
    barrier = threading.Barrier(8)

    def write(n: int) -> None:
        barrier.wait()
        try:
            world.update_entity(key["id"], 1, {"name": f"Key {n}"})
            results.append("ok")
        except Conflict:
            results.append("conflict")

    threads = [threading.Thread(target=write, args=(n,)) for n in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(results) == ["conflict"] * 7 + ["ok"]
    assert world.get_entity(key["id"])["revision"] == 2
    assert len(world.revisions(key["id"])) == 2


def test_list_filters_by_kind_tag_and_text(world: World) -> None:
    hall = make(world, "setting", "Hall", brief="A large hall.", tags=["outdoor"])
    make(world, "character", "Guide", brief="Knows the town.", tags=["outdoor", "crew"])
    make(world, "prop", "Key", tags=["hall"])

    def titles(**query: Any) -> list[str]:
        return sorted(e["title"] for e in world.list_entities(**query))

    assert titles(kind="setting") == ["Hall"]
    assert titles(tag="outdoor") == ["Guide", "Hall"]
    assert titles(text="TOWN") == ["Guide"]
    assert titles(text="hall") == ["Hall", "Key"]
    assert titles(kind="prop", tag="outdoor") == []
    world.archive_entity(hall["id"], 1)
    assert titles(tag="outdoor") == ["Guide"]
    assert titles(tag="outdoor", include_archived=True) == ["Guide", "Hall"]
    with pytest.raises(Invalid):
        world.list_entities(kind="vehicle")


def test_archive_restore_and_revert(world: World) -> None:
    key = make(world, "prop", "Key")
    world.update_entity(key["id"], 1, {"name": "Iron key"})
    archived = world.archive_entity(key["id"], 2)
    assert archived["archived"] and archived["revision"] == 3
    with pytest.raises(Conflict, match="archived"):
        world.update_entity(key["id"], 3, {"name": "Steel key"})
    with pytest.raises(Conflict):
        world.archive_entity(key["id"], 3)
    restored = world.restore_entity(key["id"], 3)
    assert not restored["archived"] and restored["revision"] == 4
    with pytest.raises(Conflict):
        world.restore_entity(key["id"], 4)
    reverted = world.revert_entity(key["id"], 4, 1)
    assert reverted["data"]["name"] == "Key" and reverted["revision"] == 5
    notes = [r["note"] for r in world.revisions(key["id"])]
    assert notes == ["Reverted to revision 1", "Restored", "Archived", "Updated", "Created"]


def test_schema_edits_apply_at_once_and_archive_never_revalidates(
    workspace: Workspace, world: World
) -> None:
    key = make(world, "prop", "Key", material="steel")
    schema_file = world.project.root / "kinds" / "prop.schema.json"
    schema = json.loads(schema_file.read_text())
    schema["properties"]["material"]["enum"] = ["iron"]
    schema_file.write_text(json.dumps(schema))
    edited = workspace.open("sample")
    with pytest.raises(Invalid) as caught:
        edited.update_entity(key["id"], 1, key["data"])
    assert caught.value.field == "/data/material"
    edited.archive_entity(key["id"], 1)  # the old data no longer fits; archiving still works
    edited.restore_entity(key["id"], 2)
    with pytest.raises(Invalid) as caught:
        edited.revert_entity(key["id"], 3, 1)
    assert caught.value.field == "/revisions/1/data/material"


def test_links_in_both_directions(world: World) -> None:
    hall = make(world, "setting", "Hall")
    guide = make(world, "character", "Guide")
    key = make(world, "prop", "Key")
    lives = world.add_link("lives_in", guide["id"], hall["id"])
    owns = world.add_link("belongs_to", key["id"], guide["id"])
    out = world.links(guide["id"], "out")
    assert [(link["type"], link["label"], link["other"]["title"]) for link in out] == [
        ("lives_in", "lives in", "Hall")
    ]
    into = world.links(guide["id"], "in")
    assert [(link["type"], link["label"], link["other"]["title"]) for link in into] == [
        ("belongs_to", "owns", "Key")
    ]
    assert {link["id"] for link in world.links(guide["id"])} == {lives["id"], owns["id"]}
    assert world.get_link(lives["id"])["source"] == guide["id"]
    world.delete_link(lives["id"])
    assert world.links(hall["id"]) == []
    with pytest.raises(NotFound):
        world.delete_link(lives["id"])
    with pytest.raises(Invalid):
        world.links(guide["id"], "sideways")


def test_bad_links_are_refused(world: World) -> None:
    hall = make(world, "setting", "Hall")
    guide = make(world, "character", "Guide")
    key = make(world, "prop", "Key")
    cases: list[tuple[tuple[str, str, str], type[Exception], str, str | None]] = [
        (("lives_in", guide["id"], "missing"), NotFound, "entity_not_found", "/target"),
        (("lives_in", "missing", hall["id"]), NotFound, "entity_not_found", "/source"),
        (("lives_in", key["id"], hall["id"]), Invalid, "link_kinds", "/source"),
        (("lives_in", guide["id"], key["id"]), Invalid, "link_kinds", "/target"),
        (("sails_to", guide["id"], hall["id"]), Invalid, "unknown_link_type", "/type"),
        (("knows", guide["id"], guide["id"]), Invalid, "self_link", "/target"),
    ]
    for args, error, code, field in cases:
        with pytest.raises(error) as caught:
            world.add_link(*args)
        assert (caught.value.code, caught.value.field) == (code, field), args  # type: ignore[attr-defined]
    world.add_link("lives_in", guide["id"], hall["id"])
    with pytest.raises(Conflict) as conflict:
        world.add_link("lives_in", guide["id"], hall["id"])
    assert conflict.value.code == "duplicate_link"


def test_archiving_hides_links_and_restoring_shows_them(world: World) -> None:
    hall = make(world, "setting", "Hall")
    guide = make(world, "character", "Guide")
    world.add_link("lives_in", guide["id"], hall["id"])
    world.archive_entity(hall["id"], 1)
    assert world.links(guide["id"]) == []
    [hidden] = world.links(guide["id"], include_archived=True)
    assert hidden["other"] == {
        "id": hall["id"],
        "kind": "setting",
        "title": "Hall",
        "archived": True,
    }
    other = make(world, "character", "Helper")
    with pytest.raises(Conflict) as caught:
        world.add_link("lives_in", other["id"], hall["id"])
    assert caught.value.code == "entity_archived"
    world.restore_entity(hall["id"], 2)
    assert len(world.links(guide["id"])) == 1


def test_runs_and_chosen_candidates(world: World) -> None:
    key = make(world, "prop", "Key")
    attached = world.attach_run(key["id"], "run-1", "first try")
    assert attached["entity_revision"] == 1 and attached["note"] == "first try"
    with pytest.raises(Conflict):
        world.attach_run(key["id"], "run-1")
    with pytest.raises(Invalid) as caught:
        world.attach_run(key["id"], "../escape")
    assert caught.value.field == "/run_id"
    world.update_entity(key["id"], 1, {"name": "Key", "material": "steel"})
    first = world.choose(key["id"], "run-2", "concept/candidate-1.png")
    assert first["slot"] == "main" and first["entity_revision"] == 2
    world.choose(key["id"], "run-2", "concept/candidate-3.png")
    world.choose(key["id"], "run-1", "mesh/model.glb", slot="mesh")
    chosen = world.chosen(key["id"])
    assert chosen["main"]["candidate"] == "concept/candidate-3.png"
    assert chosen["mesh"]["run_id"] == "run-1"
    assert len(world.choices(key["id"])) == 3
    assert sorted(r["run_id"] for r in world.runs(key["id"])) == ["run-1", "run-2"]
    with pytest.raises(Conflict) as conflict:
        world.detach_run(key["id"], "run-2")
    assert conflict.value.code == "run_has_choice"
    for bad in ({"slot": "Main"}, {"candidate": ""}, {"candidate": "a\nb"}):
        with pytest.raises(Invalid):
            world.choose(key["id"], "run-2", **{"candidate": "x", **bad})
    world.attach_run(key["id"], "run-3")
    world.detach_run(key["id"], "run-3")
    with pytest.raises(NotFound):
        world.detach_run(key["id"], "run-3")


def test_a_run_store_check_can_be_passed_in(tmp_path: Path) -> None:
    known = {"run-1"}
    workspace = Workspace(RegistryFile(tmp_path / "r.json"), run_exists=known.__contains__)
    workspace.create(str(tmp_path / "p"), "p", "P")
    world = workspace.open("p")
    key = make(world, "prop", "Key")
    world.attach_run(key["id"], "run-1")
    with pytest.raises(NotFound) as caught:
        world.choose(key["id"], "run-9", "concept/a.png")
    assert caught.value.code == "run_not_found"
