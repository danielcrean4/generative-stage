"""adapters/adapter.schema.json and pipeline/adapter_config.py describe one contract: every shipped entry passes
both, and each broken entry below fails both."""

import copy
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "pipeline"))
import adapter_config  # noqa: E402

SCHEMA = Draft202012Validator(json.loads((REPO / "adapters" / "adapter.schema.json").read_text()))
SHIPPED = sorted((REPO / "adapters").rglob("adapters.json"))
GOOD = {
    "id": "a",
    "kind": "image",
    "argv": ["/bin/prog", "{prompt}"],
    "sandbox": {"network": "deny"},
    "licence": "MIT",
}
BROKEN: list[tuple[str, Any]] = [
    ("licence", None),
    ("id", "has space"),
    ("kind", "video"),
    ("argv", "/bin/sh -c x"),
    ("argv", []),
    ("argv", ["/bin/prog", 3]),
    ("sandbox", {"network": "open"}),
    ("sandbox", {}),
    ("timeout_seconds", 0),
    ("gpu", "yes"),
    ("requires", ["quantum"]),
    ("env", {"lower": "x"}),
    ("model", {"weights": "/w"}),
    ("shell", True),
]


def test_the_schema_is_valid() -> None:
    Draft202012Validator.check_schema(SCHEMA.schema)


@pytest.mark.parametrize("file", SHIPPED, ids=lambda p: p.parent.name)
def test_every_shipped_file_passes_both(file: Path) -> None:
    body = json.loads(file.read_text())
    assert list(SCHEMA.iter_errors(body)) == []
    adapter_config.parse(
        {"adapters": body["adapters"]} if file.parent.name != "standin" else {}, str(file)
    )


@pytest.mark.parametrize(("key", "value"), BROKEN)
def test_each_broken_entry_fails_both(key: str, value: Any) -> None:
    entry = copy.deepcopy(GOOD)
    if value is None:
        entry.pop(key)
    else:
        entry[key] = value
    assert list(SCHEMA.iter_errors({"adapters": [entry]})), key
    with pytest.raises(adapter_config.AdapterError):
        adapter_config.parse_entry(entry, "test")


def test_a_machine_config_with_entries_and_defaults_passes_both() -> None:
    """A whole machine config (the other keys are machine.py's): its entries and defaults load, and the default wins."""
    raw = {
        "gpu_lock": "/state/gpu-lock",
        "tools_python": "/venvs/tools/bin/python",
        "adapters": [{**GOOD, "id": "my-image-model", "kind": "image"}],
        "defaults": {"image": "my-image-model"},
    }
    found = adapter_config.parse(raw, "machine.json")
    assert found.defaults["image"] == "my-image-model"
    assert found.defaults["image-to-mesh"] == "standin-mesh"
    assert list(SCHEMA.iter_errors(raw)) == []
