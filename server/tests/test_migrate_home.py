"""scripts/migrate_home.py: moves the folders of the tool's earlier name and rewrites the paths that name them."""

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "migrate_home.py"


def run(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "--home", str(home), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def old_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    config, data = home / ".config/dramatis-fabrica", home / ".local/share/dramatis-fabrica"
    (config / "proxies").mkdir(parents=True)
    (data / "projects/one").mkdir(parents=True)
    (data / "runs/r1").mkdir(parents=True)
    (data / "archive/old/project").mkdir(parents=True)
    (config / "server.json").write_text(
        json.dumps(
            {
                "data_dir": "~/.local/share/dramatis-fabrica",
                "runs_root": f"{data}/runs",
                "gpu_lock": "~/.local/state/dramatis-fabrica/gpu-lock",  # not moved, so not rewritten
            }
        )
    )
    (config / "proxies/live.json").write_text(json.dumps({"/api": {"cwd": str(config)}}))
    (config / "machine.json").write_text(
        json.dumps({"tools_python": "/opt/python", "adapters": []})
    )
    (data / "registry.json").write_text(
        json.dumps(
            {
                "projects": [
                    {"file": f"{data}/projects/one/studio.project.json"},
                    {
                        "file": f"{home}/dramatis-fabrica-example/studio.project.json"
                    },  # a longer name: left alone
                ]
            }
        )
    )
    (data / "projects/one/studio.project.json").write_text(
        json.dumps({"runs": f"{data}/runs", "name": "Bäckerei"}, ensure_ascii=False)
    )
    (data / "archive/old/project/studio.project.json").write_text(
        json.dumps({"runs": f"{data}/runs"})
    )  # history: left alone
    (data / "runs/r1/record.json").write_text(
        json.dumps({"out": f"{data}/runs/r1"})
    )  # history: left alone
    return home


def test_dry_run_reports_and_changes_nothing(tmp_path: Path) -> None:
    home = old_home(tmp_path)
    before = {p: p.read_bytes() for p in home.rglob("*") if p.is_file()}
    done = run(home, "--dry-run")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "Would move" in done.stdout and "would rewrite paths in" in done.stdout
    assert {p: p.read_bytes() for p in home.rglob("*") if p.is_file()} == before
    assert not (home / ".config/generative-stage").exists()


def test_refuses_when_a_new_folder_exists(tmp_path: Path) -> None:
    home = old_home(tmp_path)
    (home / ".local/share/generative-stage").mkdir()
    done = run(home)
    assert done.returncode == 1
    assert "Refused" in done.stdout
    assert (home / ".config/dramatis-fabrica/server.json").is_file()  # nothing moved
    assert not (home / ".config/generative-stage").exists()


def test_moves_the_folders_and_rewrites_the_paths(tmp_path: Path) -> None:
    home = old_home(tmp_path)
    done = run(home)
    assert done.returncode == 0, done.stdout + done.stderr
    config, data = home / ".config/generative-stage", home / ".local/share/generative-stage"
    assert not (home / ".config/dramatis-fabrica").exists()
    assert not (home / ".local/share/dramatis-fabrica").exists()
    server = json.loads((config / "server.json").read_text())
    assert server == {
        "data_dir": "~/.local/share/generative-stage",
        "runs_root": f"{data}/runs",
        "gpu_lock": "~/.local/state/dramatis-fabrica/gpu-lock",
    }
    assert json.loads((config / "proxies/live.json").read_text()) == {"/api": {"cwd": str(config)}}
    registry = json.loads((data / "registry.json").read_text())
    assert registry["projects"] == [
        {"file": f"{data}/projects/one/studio.project.json"},
        {"file": f"{home}/dramatis-fabrica-example/studio.project.json"},
    ]
    assert (
        json.loads((data / "projects/one/studio.project.json").read_text())["runs"]
        == f"{data}/runs"
    )
    assert "Bäckerei" in (data / "projects/one/studio.project.json").read_text(encoding="utf-8")
    old_data = home / ".local/share/dramatis-fabrica"
    archived = json.loads((data / "archive/old/project/studio.project.json").read_text())
    assert archived == {"runs": f"{old_data}/runs"}
    assert json.loads((data / "runs/r1/record.json").read_text()) == {"out": f"{old_data}/runs/r1"}
    assert "rewrote paths in" in done.stdout
    assert "machine.json" not in done.stdout  # it named no old folder, so it was not rewritten
    assert run(home).stdout.startswith("Nothing to move")
