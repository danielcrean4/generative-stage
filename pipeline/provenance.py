"""File hashes, atomic JSON and the identity of an installed model folder (plain Python, no model imports).

The helpers every record-writing tool shares: `digest` (sha256 of a file), `fingerprint` (sha256 of a JSON value),
`atomic_json` / `read_json`, and `cached_model_identity`, which hashes a model folder once and serves the answer
from a small cache file while the folder is unchanged.
"""
import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path

from local_run import StepFailed

IDENTITY_CACHE_ENV = "GENSTAGE_IDENTITY_CACHE"
IDENTITY_CACHE_FILE = "model-identity.json"  # in ~/.cache/generative-stage


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def atomic_json(path: Path, value) -> None:
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    os.replace(temporary, path)


def read_json(path: Path, default):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def identity_cache_path() -> Path:
    """The one file that remembers model-folder hashes between runs (the environment overrides it, for tests and other disks)."""
    named = os.environ.get(IDENTITY_CACHE_ENV)
    return Path(named).expanduser() if named else Path("~/.cache/generative-stage").expanduser() / IDENTITY_CACHE_FILE


def model_identity_uncached(folder: Path, hasher=digest) -> dict:
    """Hash every file of an installed model folder. No network or model imports."""
    files = {str(path.relative_to(folder)): hasher(path)
             for path in sorted(folder.rglob("*")) if path.is_file()}
    if not files:
        raise StepFailed(f"Installed model files are missing: {folder}")
    return {"path": str(folder), "sha256": fingerprint(files), "files": files}


def cached_model_identity(folder: Path, cache_file: Path | None = None, hasher=digest) -> dict:
    """model_identity_uncached, served from `cache_file` while the folder is unchanged: same file
    names, and the same size and modification time for each. A change to any of them rehashes the
    folder and rewrites its entry. (A file edited in place with its size and mtime restored would be
    missed; touching a weights file never does that.)"""
    folder, cache_file = Path(folder), cache_file or identity_cache_path()
    stats = {str(path.relative_to(folder)): [path.stat().st_size, path.stat().st_mtime_ns]
             for path in sorted(folder.rglob("*")) if path.is_file()}
    cache = read_json(cache_file, {})
    entry = cache.get(str(folder)) if isinstance(cache, dict) else None
    if isinstance(entry, dict) and entry.get("stats") == stats and isinstance(entry.get("identity"), dict):
        return entry["identity"]
    identity = model_identity_uncached(folder, hasher)
    cache = cache if isinstance(cache, dict) else {}
    cache[str(folder)] = {"stats": stats, "identity": identity}
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(cache_file, cache)
    return identity


@lru_cache(maxsize=None)
def model_identity(folder: Path) -> dict:
    """The model folder's identity, hashed once per change on disk (persistent cache) and once per process."""
    return cached_model_identity(folder)
