"""Write the default machine config (every kind on the stand-in adapters) unless a file is already there.

    python3 scripts/write_machine_config.py [--file PATH] --tools-python PATH

PATH is the file the pipeline reads (pipeline/machine.py): $GENSTAGE_MACHINE_CONFIG, else
~/.config/generative-stage/machine.json. An existing file is never read for changes, never overwritten and never
edited; this says so and exits 0.
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
import machine  # noqa: E402

DEFAULTS = {
    "image": "standin-image",
    "image-to-mesh": "standin-mesh",
    "text": "standin-text",
    "review": "standin-review",
}


def target(named: str | None) -> Path:
    if named:
        return Path(named).expanduser()
    try:
        return machine.config_file()
    except machine.MachineError:  # the variable names a file that is not there yet: that is the file to write
        return Path(os.environ.get(machine.CONFIG_ENV) or "").expanduser()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--file", help="where to write (default: the pipeline's own place)")
    parser.add_argument("--tools-python", required=True, help="the interpreter of the tools environment")
    args = parser.parse_args()
    file = target(args.file)
    if file.exists():
        print(f"Machine config kept as it is: {file}")
        return 0
    file.parent.mkdir(parents=True, exist_ok=True)
    # abspath, not resolve(): a venv interpreter is a link, and the link is what carries its packages
    config = {"tools_python": os.path.abspath(args.tools_python), "adapters": [], "defaults": DEFAULTS}
    file.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(f"Machine config written: {file} (every kind runs on the stand-in; edit it to use a real model)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
