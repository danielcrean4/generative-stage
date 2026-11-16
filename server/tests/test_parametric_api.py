"""The parametric routes end to end on the stand-in adapters: info, preview (and its cache), a batch of 20 with no model,
triage, a kept candidate that a record chooses and the export carries, and the refusals."""

import importlib.util
import json
import time
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
from pathlib import Path
from typing import Any

from running_server import Running

from authoring import parametric_api

REPO = Path(__file__).resolve().parents[2]
ROW = {
    "name": "Desk",
    "shade": "drum",
    "height_cm": 80,
    "base_radius_cm": 10,
    "has_arm": False,
    "colour": "#aabbcc",
    "drum_radius_cm": 20,
}


def png(running: Running, path: str) -> bytes:
    client = HTTPConnection("127.0.0.1", running.api.port, timeout=10)
    client.request("GET", path)
    response = client.getresponse()
    data = response.read()
    assert response.status == 200 and response.getheader("Content-Type") == "image/png"
    client.close()
    return data


def install_example(running: Running) -> str:
    spec = importlib.util.spec_from_file_location(
        "add_example", REPO / "scripts" / "add_parametric_example.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.add(running.api.root / "sample")
    return f"{running.project}/parametric/lamp"


def test_the_kind_is_parametric_and_the_info_lists_what_it_offers(running: Running) -> None:
    base = install_example(running)
    kind = running.api.ok("GET", f"{running.project}/kinds/lamp")
    model = kind["parameters"]
    assert model["selector"] == "shade"
    by_name = {f["name"]: f for f in model["fields"]}
    assert by_name["height_cm"] | {"type": "number"} == by_name["height_cm"]
    assert by_name["height_cm"]["unit"] == "cm" and by_name["height_cm"]["step"] == 5
    assert by_name["arm_reach_cm"]["when"] == "has_arm" and by_name["cone_top_cm"]["builders"] == [
        "cone"
    ]
    assert by_name["colour"]["type"] == "colour"
    assert running.api.ok("GET", f"{running.project}/kinds/prop")["parameters"] is None
    info = running.api.ok("GET", base)
    assert info["has_kit"] and info["subject_fields"]["theme"] == ["modern", "rustic", "industrial"]
    assert [g["id"] for g in info["gates"]] == ["not_empty", "not_a_blob", "tall_enough"]
    assert info["defaults"] == {
        "rules": "rules-kit",
        "render": "standin-render",
        "measure": "standin-measure",
    }
    running.api.fails("GET", f"{running.project}/parametric/prop", None, 422, "not_parametric")


def test_a_preview_renders_measures_and_is_cached(running: Running) -> None:
    base = install_example(running)
    shown = running.api.ok("POST", f"{base}/preview", {"row": ROW})
    assert shown["still"] == "still.png" and shown["numbers"]["ink_ratio"] > 0
    assert {g["id"] for g in shown["gates"]} == {"not_empty", "not_a_blob", "tall_enough"}
    again = running.api.ok("POST", f"{base}/preview", {"row": ROW})
    assert again["id"] == shown["id"]
    moved = running.api.ok("POST", f"{base}/preview", {"row": {**ROW, "height_cm": 200}})
    assert (
        moved["id"] != shown["id"]
        and moved["numbers"]["ink_height_px"] > shown["numbers"]["ink_height_px"]
    )
    assert png(
        running, f"{running.project}/parametric/previews/{shown['id']}/still.png"
    ).startswith(b"\x89PNG")
    running.api.fails(
        "POST", f"{base}/preview", {"row": {**ROW, "height_cm": 999}}, 422, "invalid_entity"
    )
    running.api.fails(
        "POST", f"{base}/preview", {"row": ROW, "adapters": {"render": "nope"}}, 422, "bad_adapter"
    )


def test_a_batch_of_twenty_takes_seconds_and_each_row_fits_the_schema(running: Running) -> None:
    base = install_example(running)
    started = time.monotonic()
    batch = running.api.ok(
        "POST",
        f"{base}/batches",
        {
            "subject": {},
            "cross": {"theme": ["modern", "rustic"], "material": ["oak", "steel"]},
            "seed": 4,
            "count": 5,
        },
        201,
    )
    assert time.monotonic() - started < 20
    assert len(batch["tiles"]) == 20
    assert {t["cell"]["theme"] for t in batch["tiles"]} == {"modern", "rustic"}
    for tile in batch["tiles"]:
        assert tile["verdict"] in ("pass", "review", "fail") and tile["still"] == "still.png"
        assert (
            running.config.runs_root / batch["id"] / "tiles" / tile["id"] / "still.png"
        ).is_file()
    twin = running.api.ok(
        "POST",
        f"{base}/batches",
        {
            "cross": {"theme": ["modern", "rustic"], "material": ["oak", "steel"]},
            "seed": 4,
            "count": 5,
        },
        201,
    )
    assert [t["row"] for t in twin["tiles"]] == [t["row"] for t in batch["tiles"]]
    running.api.fails("POST", f"{base}/batches", {"cross": {"colour": ["#000000"]}}, 422, "invalid")
    running.api.fails("POST", f"{base}/batches", {"count": 0}, 422, "invalid")


def test_triage_is_saved_and_a_kept_row_is_chosen_and_exported(running: Running) -> None:
    base = install_example(running)
    batch = running.api.ok(
        "POST", f"{base}/batches", {"cross": {"theme": ["modern"]}, "seed": 1, "count": 3}, 201
    )
    marks = {
        "v001": {"verdict": "keep", "note": "good legs"},
        "v002": {"verdict": "fix", "note": ""},
    }
    saved = running.api.ok(
        "PUT", f"{running.project}/parametric/batches/{batch['id']}/triage", marks
    )
    assert saved["triage"] == marks
    assert (
        running.api.ok("GET", f"{running.project}/parametric/batches/{batch['id']}")["triage"]
        == marks
    )
    running.api.ok(
        "PUT",
        f"{running.project}/parametric/batches/{batch['id']}/triage",
        {"v002": {"verdict": None}},
    )
    assert list(
        running.api.ok("GET", f"{running.project}/parametric/batches/{batch['id']}")["triage"]
    ) == ["v001"]
    running.api.fails(
        "PUT",
        f"{running.project}/parametric/batches/{batch['id']}/triage",
        {"v001": {"verdict": "maybe"}},
        422,
        "invalid",
    )
    running.api.fails(
        "PUT",
        f"{running.project}/parametric/batches/{batch['id']}/triage",
        {"v099": {"verdict": "keep"}},
        422,
        "invalid",
    )

    tile = batch["tiles"][0]
    made = running.api.ok(
        "POST", f"{running.project}/entities", {"kind": "lamp", "data": tile["row"]}, 201
    )
    running.api.ok(
        "POST",
        f"{running.project}/entities/{made['id']}/chosen",
        {"run_id": batch["id"], "candidate": f"tiles/{tile['id']}/still.png", "slot": "parametric"},
        201,
    )
    assert png(
        running, f"{running.project}/entities/{made['id']}/chosen/parametric/file"
    ).startswith(b"\x89PNG")
    export = running.api.ok("POST", f"{running.project}/exports", {"kinds": ["lamp"]}, 201)
    manifest = json.dumps(running.api.ok("GET", f"{running.project}/exports/{export['id']}"))
    assert made["id"] in manifest


def test_a_kept_candidate_is_a_run_a_record_can_choose(running: Running) -> None:
    base = install_example(running)
    kept: dict[str, Any] = running.api.ok("POST", f"{base}/candidates", {"row": ROW}, 201)
    made = running.api.ok("POST", f"{running.project}/entities", {"kind": "lamp", "data": ROW}, 201)
    running.api.ok(
        "POST", f"{running.project}/entities/{made['id']}/runs", {"run_id": kept["run_id"]}, 201
    )
    running.api.ok(
        "POST",
        f"{running.project}/entities/{made['id']}/chosen",
        {"run_id": kept["run_id"], "candidate": kept["candidate"]},
        201,
    )
    assert (
        running.api.ok("GET", f"{running.project}/entities/{made['id']}/chosen")["chosen"]["main"][
            "run_id"
        ]
        == kept["run_id"]
    )


def small_batch(running: Running, base: str, count: int = 3) -> dict[str, Any]:
    body = {"cross": {"theme": ["modern"]}, "seed": 1, "count": count}
    batch: dict[str, Any] = running.api.ok("POST", f"{base}/batches", body, 201)
    return batch


def test_a_boolean_subschema_is_no_parameter_and_does_not_break_the_kinds(
    running: Running,
) -> None:
    install_example(running)
    schema_file = running.api.root / "sample" / "kinds" / "lamp.schema.json"
    schema = json.loads(schema_file.read_text())
    schema["properties"]["extra"] = True
    schema["properties"]["never"] = False
    schema.setdefault("allOf", []).append(True)
    schema_file.write_text(json.dumps(schema))
    kinds = running.api.ok("GET", f"{running.project}/kinds")
    lamp = next(k for k in kinds["kinds"] if k["id"] == "lamp")
    assert "extra" not in {f["name"] for f in lamp["parameters"]["fields"]}


def test_twenty_parallel_triage_saves_are_all_kept_and_a_cut_file_reads_as_empty(
    running: Running,
) -> None:
    base = install_example(running)
    batch = small_batch(running, base, 20)
    ids = [t["id"] for t in batch["tiles"]][:20]
    assert len(ids) == 20
    url = f"{running.project}/parametric/batches/{batch['id']}"
    # called directly: the test server's small connection backlog would reset 20 simultaneous clients
    with ThreadPoolExecutor(20) as pool:
        list(
            pool.map(
                lambda t: parametric_api.triage(
                    running.config, batch["id"], {t: {"verdict": "keep"}}, "sample"
                ),
                ids,
            )
        )
    assert sorted(running.api.ok("GET", url)["triage"]) == sorted(ids)
    (running.config.runs_root / batch["id"] / "triage.json").write_text('{"v001": {"verd')
    assert running.api.ok("GET", url)["triage"] == {}


def test_a_link_out_of_the_batch_folder_is_not_served(running: Running, tmp_path: Path) -> None:
    base = install_example(running)
    batch = small_batch(running, base)
    secret = tmp_path / "secret.png"
    secret.write_bytes(b"\x89PNG not for you")
    folder = running.config.runs_root / batch["id"]
    (folder / "stolen.png").symlink_to(secret)
    url = f"{running.project}/parametric/batches/{batch['id']}/files"
    running.api.fails("GET", f"{url}/stolen.png", None, 404, "file_not_found")
    assert png(running, f"{url}/tiles/v001/still.png").startswith(b"\x89PNG")


def test_a_batch_is_not_reachable_from_another_project(running: Running, tmp_path: Path) -> None:
    base = install_example(running)
    batch = small_batch(running, base)
    running.api.ok(
        "POST",
        "/api/v1/projects",
        {"folder": str(tmp_path / "other"), "slug": "other", "name": "Other"},
        201,
    )
    there = f"/api/v1/projects/other/parametric/batches/{batch['id']}"
    running.api.fails("GET", there, None, 404, "batch_not_found")
    running.api.fails(
        "PUT", f"{there}/triage", {"v001": {"verdict": "keep"}}, 404, "batch_not_found"
    )
    running.api.fails("GET", f"{there}/files/tiles/v001/still.png", None, 404, "batch_not_found")
    assert running.api.ok("GET", f"{running.project}/parametric/batches/{batch['id']}")["id"]
    # a batch made before the project was recorded stays readable from every project
    meta = running.config.runs_root / batch["id"] / "parametric.json"
    old = json.loads(meta.read_text())
    del old["project"]
    meta.write_text(json.dumps(old))
    assert running.api.ok("GET", there)["id"] == batch["id"]


def test_a_malformed_kit_table_answers_422_with_the_rule_and_field(running: Running) -> None:
    base = install_example(running)
    kit_file = running.api.root / "sample" / "parametric" / "lamp.kit.json"
    kit = json.loads(kit_file.read_text())
    kit["rules"][0]["when"] = ["theme"]
    kit_file.write_text(json.dumps(kit))
    error = running.api.fails("POST", f"{base}/batches", {}, 422, "parametric_data_invalid")
    assert "/rules/0/when" in error["message"]
    running.api.fails("GET", base, None, 422, "parametric_data_invalid")
