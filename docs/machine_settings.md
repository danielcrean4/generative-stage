# Machine settings

Where this computer keeps the pipeline's models, interpreters and GPU lock. The tools guess nothing: a setting that is
needed and not set stops the tool with an error that names the setting and the file.

The file is JSON. It is the one named by the environment variable `GENSTAGE_MACHINE_CONFIG` (it must exist), else
`~/.config/generative-stage/machine.json` (while that file is missing, `~/.config/dramatis-fabrica/machine.json`, the
tool's earlier name, is read with a note; `scripts/migrate_home.py` moves it). A value may start with `~` (the home folder); a relative value is taken from the
file's folder. Unknown keys are an error. A setting is read when a tool first needs it, so a tool that never runs a model
never asks for one. `pipeline/machine.py` is the one reader.

| Key | What it is | Needed by |
|---|---|---|
| `adapters` | a list of adapter entries: the only place a command is defined ([adapters](adapters.md)) | every model stage |
| `defaults` | `{kind: adapter id}`: the adapter a stage runs when it names none | every model stage |
| `tools_python` | interpreter with numpy, scipy, trimesh, Pillow and fast-simplification (`pipeline/requirements.txt`; `./install.sh` makes `.venv-tools` and names it here); when unset, the interpreter running the pipeline | every image and mesh tool |
| `gpu_lock` | the machine-wide GPU lock file ([GPU lock](gpu_lock.md)) | every adapter whose entry says `"gpu": true` |
| `icon_dir` | working folder of `icon_batch.py` | `icon_batch.py` |

With no file, or an empty one, every model stage uses the stand-in adapters: the pipeline runs end to end with no model
installed.

Example:

```json
{
  "gpu_lock": "~/.local/state/generative-stage/gpu-lock",
  "tools_python": "/venvs/tools/bin/python",
  "adapters": [],
  "defaults": {"image": "standin-image"}
}
```

`attempt.json` names the interpreters it used by these keys and adapter ids, never by path ([pipeline files](pipeline_files.md), "Running").
