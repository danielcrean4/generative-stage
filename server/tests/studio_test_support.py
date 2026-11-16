"""Shared test helpers: machine configs that never read this computer's own config file."""

from dataclasses import replace
from pathlib import Path

from authoring.machine_config import BUILT_IN, MachineConfig, parse_machine_config

NO_DATA = Path("/var/empty/generative-stage-tests")  # never exists: no registry, no runs


def default_config() -> MachineConfig:
    """The built-in defaults, whatever machine.json this computer has, except that the data
    folder (and so the registry file and the runs root) is a folder that does not exist."""
    home = Path.home()
    return replace(
        parse_machine_config({}, BUILT_IN, home, home),
        data_dir=NO_DATA,
        runs_root=NO_DATA / "asset-runs",
        registry_file=NO_DATA / "registry.json",
    )


def stand_in_config(folder: Path) -> MachineConfig:
    """A config whose runs folder is under `folder`, so a Dispatcher can run on a computer with no model installed
    (the adapters are the pipeline's own, from the machine config the test names in GENSTAGE_MACHINE_CONFIG)."""
    return replace(default_config(), runs_root=folder / "runs")
