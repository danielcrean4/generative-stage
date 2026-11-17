"""Pytest configuration: no test may change the built-in default registry of projects."""

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from authoring.machine_config import default_data_dir


@pytest.fixture(scope="session", autouse=True)
def default_registry_is_untouched() -> Iterator[None]:
    """Every test uses temporary configs and registries. The registry file the built-in defaults
    name, when it exists on this computer, must be byte-for-byte as the suite found it."""
    registry = default_data_dir(Path.home()) / "registry.json"

    def state() -> tuple[int, int] | None:
        if not registry.exists():
            return None
        stat = registry.stat()
        return stat.st_mtime_ns, stat.st_size

    before = state()
    yield
    assert state() == before, f"a test touched {registry}"


def _tools_python() -> Path | None:
    """An interpreter with numpy, scipy, trimesh, Pillow and fast-simplification (the image and mesh tools need it):
    GENSTAGE_TEST_TOOLS_PYTHON, else the one the pipeline's machine settings name."""
    import subprocess

    import machine  # type: ignore[import-not-found]

    import authoring.pipeline_catalog  # noqa: F401 - puts pipeline/ on the path

    named = os.environ.get("GENSTAGE_TEST_TOOLS_PYTHON")
    try:
        python = Path(named) if named else Path(machine.tools_python())
    except Exception:  # noqa: BLE001 - any trouble reading the settings means: not available
        return None
    probe = "import numpy, scipy, trimesh, PIL, fast_simplification"
    try:
        ok = subprocess.run([str(python), "-I", "-c", probe], capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return python if ok.returncode == 0 else None


def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, settings: dict[str, str]) -> Path:
    config = tmp_path / "pipeline-machine.json"
    config.write_text(json.dumps(settings))
    monkeypatch.setenv("GENSTAGE_MACHINE_CONFIG", str(config))
    monkeypatch.setenv("GENSTAGE_IDENTITY_CACHE", str(tmp_path / "identity-cache.json"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    return config


@pytest.fixture(autouse=True)
def bare_pipeline_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A pipeline machine config with no settings (only the stand-in adapters), a temporary home and identity cache:
    nothing on this computer's own settings can reach the test. Every test gets it, so none reads this computer's
    machine config. Returns the config file."""
    return _isolate(tmp_path, monkeypatch, {})


@pytest.fixture
def standin_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The environment of a run on the stand-in adapters only: the same, plus the tools interpreter (the image and
    mesh tools need it), so no model and no GPU is involved. Skips the test when there is no tools interpreter."""
    python = _tools_python()
    if python is None:
        pytest.skip("no tools interpreter (numpy, scipy, trimesh, Pillow, fast-simplification)")
    return _isolate(tmp_path, monkeypatch, {"tools_python": str(python)})


@pytest.fixture
def running(tmp_path: Path, bare_pipeline_environment: Path) -> Iterator[Any]:
    """A running HTTP server (tests/running_server.py) on the stand-in adapters, with a project named `sample`."""
    from running_server import Running

    found = Running(tmp_path)
    yield found
    found.close()
