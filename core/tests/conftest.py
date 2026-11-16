from pathlib import Path

import pytest

from core.registry import RegistryFile
from core.workspace import Workspace
from core.world import World


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    return Workspace(RegistryFile(tmp_path / "data" / "registry.json"))


@pytest.fixture
def world(workspace: Workspace, tmp_path: Path) -> World:
    workspace.create(str(tmp_path / "sample"), "sample", "Sample Project")
    return workspace.open("sample")
