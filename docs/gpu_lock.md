# The GPU lock

One lock that every GPU job on this machine takes, so two models never sit in memory at once.

## What it protects

On a computer with a modest amount of memory shared between the CPU and the GPU, the image model and the mesh model can each need most of it. Two at once make the machine swap or kill a job, so a job that runs a neural command holds the lock for the length of that command. Other programs that load a model on the same machine can take the same lock (`gpu_lock.py run -- COMMAND`).

## Who takes it

- `pipeline/gpu_session.py`: `gpu_lock()` is the lock plus a wait while another process runs the program or a fixed script of any adapter entry that holds the lock (`"gpu": true`; [adapters](adapters.md)), and a tool that runs one model command (`icon_batch.py`) takes it around that command.
- `pipeline/gpu_session.py`, the same module, is also the one owner of the lock for a whole `pipeline_run`, `pipeline_batch` or `style_tracer` job (a `pipeline_run --candidates n` job is one job for all `n` seeds, which is how the server runs a request for several candidates): its `GpuSession` takes the lock lazily before the first model stage that runs and holds it until the job ends.
- `gpu_lock.py run -- COMMAND...`, for any other program.

All of them call `pipeline/gpu_lock.py`. Nothing else in this repo spells the lock path.

## Where the lock is

The path comes from one function, `gpu_lock.default_lock_path()`. It reads the key `gpu_lock` in the machine settings ([machine settings](machine_settings.md)). There is no fallback: with no file or no key the tool stops with an error that names the key and the file. Every program on the computer must resolve the same path, so set the same value wherever a second program (a server, a game's capture tool) keeps its own settings. Run `python3 pipeline/gpu_lock.py status` to see the path and who holds it.

The lock is a small JSON file holding the owner's pid, the time that process started, what it is running, and since when.

## The takeover rule

- A lock held by a live process is never removed, however old it is. A waiting job gives up after its timeout and the error names the owner (pid, command, since when).
- A lock is stale when no process has that pid, or a process has that pid but started at a different time (the number was reused, for example after a reboot). Pid plus start time is the owner's identity.
- A stale lock is replaced in one atomic rename, under a short mutex, so two jobs that find the same stale lock cannot both win. The exact sequence is in the docstring of `pipeline/gpu_lock.py`.
- A job killed with `kill -9` leaves its lock behind. The next job finds it stale and takes over. A job stopped with SIGTERM or Ctrl-C releases it.

## Command line

```
python3 pipeline/gpu_lock.py status                 # free, live, stale or unprovable; exit 0 free, 1 held, 2 stale
python3 pipeline/gpu_lock.py run [--timeout S] -- COMMAND ARGS...
```

`run` waits for the lock (default 1800 s), runs the command, passes its exit code on, and releases on exit and on SIGTERM (the child is sent the signal too). If `run` itself is killed with SIGKILL its child keeps running without a valid lock, so do not do that.

## The old folder lock

A lock path that is a folder made with `mkdir` by another tool is still respected:

- A folder whose `owner` file names a live process blocks.
- A folder whose `owner` file names a dead process is taken over.
- A folder with no `owner` file blocks until the timeout. It cannot be proved stale: a crashed holder and a live one look the same, and removing a live lock lets two models load. The error says so.

To clear one by hand, first check nothing is running (`pgrep -fl pipeline_run`, and the programs of your `gpu` adapters), then `rm -r <lock path>`. Next to the lock you may also see `<lock>.takeover` (an empty file used as the mutex); it is safe to leave.
