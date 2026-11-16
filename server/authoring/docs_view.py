"""What a registered project's markdown docs and allowlisted source say, read-only.

Pure reading over a `ProjectFile` (authoring/project_file.py): list the docs, read one with its
outline and classified links, read a window of one allowlisted source file, search the docs. No
HTTP here (routing is in authoring/readonly_server.py) and no markdown rendering: the text goes
out raw and the UI renders it. docs/docs_view.md explains the routes and the safety rules.

Safety: a request names a repo-relative path. A doc is served only if it is in the listing built
from the project's docs roots and docs files (every file resolved, symlinks included, and kept
only if it stays inside its root). A source file is served only if its resolved path is inside
the project's source_allowlist. Dotfiles and dot folders (`.git` too) are never listed or
served. Folders in `external_docs` (outside the project) are listed read-only under
`external/<folder name>/`. Anything else raises NotFound with a message that names no path.
"""

import bisect
import os
import posixpath
import re
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from authoring.run_view import NotFound
from core.project_file import ProjectFile

MAX_DOC_BYTES = 2 << 20
MAX_SOURCE_BYTES = 8 << 20
DEFAULT_WINDOW = 200
MAX_WINDOW = 500
MAX_LINE_CHARS = 2000
MAX_QUERY = 200
DEFAULT_LIMIT = 50
MAX_LIMIT = 200
MAX_HITS_PER_DOC = 10
EXCERPT_CHARS = 160
BINARY_SNIFF = 8192

NO_FILE = "no such file"
HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$")
FENCE = re.compile(r"^ {0,3}(```|~~~)")
INLINE_LINK = re.compile(r"(!?)\[(?:[^\]\\]|\\.)*\]\(\s*(<[^>]*>|[^)\s]*)(?:\s+\"[^\"]*\")?\s*\)")
REFERENCE_LINK = re.compile(r"^ {0,3}\[[^\]]+\]:\s*(<[^>]*>|\S+)")
EXTERNAL = re.compile(r"(?i)^(https?://|mailto:)")
SOURCE_LINK = re.compile(r"^(?P<path>[^#?]*?)(?::(?P<line>\d+)(?::\d+)?)?(?P<rest>[#?].*)?$")


def clean_path(raw: str) -> str:
    """A repo-relative path from a request, or NotFound: no empty, absolute, `.`/`..` or dot
    components, no backslash or NUL."""
    if not raw or len(raw) > 512 or "\0" in raw or "\\" in raw:
        raise NotFound(NO_FILE)
    if any(part in ("", ".", "..") or part.startswith(".") for part in raw.split("/")):
        raise NotFound(NO_FILE)
    return raw


EXTERNAL_PREFIX = "external"


def external_names(project: ProjectFile) -> dict[str, Path]:
    """Virtual folder name -> external docs folder. The name is the folder's own name (a leading
    dot is dropped), made unique with -2, -3 when two folders share one."""
    names: dict[str, Path] = {}
    for folder in project.external_docs:
        base = folder.name.lstrip(".") or "docs"
        name, count = base, 1
        while name in names:
            count += 1
            name = f"{base}-{count}"
        names[name] = folder
    return names


def _hidden(rel: str) -> bool:
    return any(part.startswith(".") for part in rel.split("/"))


def _iso(mtime_ns: int) -> str:
    return datetime.fromtimestamp(mtime_ns / 1e9, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class DocEntry:
    real: Path
    mtime_ns: int
    size: int
    title: str
    headings: tuple[tuple[int, str, int], ...]  # level, text, line number
    lines: tuple[str, ...]  # empty for a doc over MAX_DOC_BYTES


def _outline(lines: Sequence[str]) -> list[tuple[int, str, int]]:
    found = []
    fenced = False
    for number, line in enumerate(lines, 1):
        if FENCE.match(line):
            fenced = not fenced
        elif not fenced and (match := HEADING.match(line)):
            found.append((len(match.group(1)), match.group(2), number))
    return found


def _read_entry(rel: str, real: Path) -> DocEntry:
    stat = real.stat()
    lines: tuple[str, ...] = ()
    if stat.st_size <= MAX_DOC_BYTES:
        lines = tuple(real.read_bytes().decode("utf-8", errors="replace").splitlines())
    headings = tuple(_outline(lines))
    title = next((text for level, text, _ in headings if level == 1), posixpath.basename(rel))
    return DocEntry(real, stat.st_mtime_ns, stat.st_size, title, headings, lines)


class DocsView:
    """Reads docs and source. Holds one in-memory cache of parsed docs, refreshed per file when
    its modified time or size changes; nothing is written anywhere."""

    def __init__(self) -> None:
        self._cache: dict[tuple[Path, str], DocEntry] = {}
        self._lock = threading.Lock()

    # -- which files are docs / source ------------------------------------------------------

    def doc_files(self, project: ProjectFile) -> dict[str, Path]:
        """Repo-relative path -> resolved file, for every doc that is safe to serve."""
        repo = project.root
        found: dict[str, Path] = {}
        for root in project.docs_roots:
            real_root = root.resolve()
            if not real_root.is_dir() or not real_root.is_relative_to(repo):
                continue
            for dirpath, dirnames, filenames in os.walk(real_root):
                dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
                for name in sorted(filenames):
                    if name.startswith(".") or not name.endswith(".md"):
                        continue
                    path = Path(dirpath) / name
                    real = path.resolve()
                    if real.is_relative_to(real_root) and real.is_file():
                        found[path.relative_to(repo).as_posix()] = real
        for name, folder in external_names(project).items():
            for dirpath, dirnames, filenames in os.walk(folder):
                dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
                for filename in sorted(filenames):
                    if filename.startswith(".") or not filename.endswith(".md"):
                        continue
                    real = (Path(dirpath) / filename).resolve()
                    if real.is_relative_to(folder) and real.is_file():
                        rel = f"{EXTERNAL_PREFIX}/{name}/{real.relative_to(folder).as_posix()}"
                        found.setdefault(rel, real)
        for path in project.docs_files:
            real = path.resolve()
            rel = real.relative_to(repo).as_posix() if real.is_relative_to(repo) else ""
            if rel and not _hidden(rel) and real.is_file():
                found[rel] = real
        return found

    def source_file(self, project: ProjectFile, rel: str) -> Path:
        """The resolved source file for a repo-relative path, or NotFound."""
        rel = clean_path(rel)
        real = (project.root / rel).resolve()
        if not real.is_file() or not real.is_relative_to(project.root):
            raise NotFound(NO_FILE)
        if _hidden(real.relative_to(project.root).as_posix()):
            raise NotFound(NO_FILE)
        if not any(real.is_relative_to(allowed.resolve()) for allowed in project.source_allowlist):
            raise NotFound("not in the source allowlist")
        return real

    def _entry(self, project: ProjectFile, rel: str, real: Path) -> DocEntry:
        key = (project.file, rel)
        stat = real.stat()
        with self._lock:
            cached = self._cache.get(key)
        if cached and (cached.real, cached.mtime_ns, cached.size) == (
            real,
            stat.st_mtime_ns,
            stat.st_size,
        ):
            return cached
        entry = _read_entry(rel, real)
        with self._lock:
            self._cache[key] = entry
        return entry

    # -- list -------------------------------------------------------------------------------

    def doc_count(self, project: ProjectFile) -> int:
        return len(self.doc_files(project))

    def list_docs(self, project: ProjectFile) -> dict[str, Any]:
        """Every doc as a tree rooted at the repo: folders hold files and folders."""
        root: dict[str, Any] = {"type": "dir", "name": project.name, "path": "", "children": []}
        folders: dict[str, dict[str, Any]] = {"": root}
        files = self.doc_files(project)
        for rel, real in sorted(files.items()):
            entry = self._entry(project, rel, real)
            parent, prefix = root, ""
            for part in rel.split("/")[:-1]:
                prefix = f"{prefix}/{part}" if prefix else part
                if prefix not in folders:
                    folders[prefix] = {"type": "dir", "name": part, "path": prefix, "children": []}
                    parent["children"].append(folders[prefix])
                parent = folders[prefix]
            parent["children"].append(
                {
                    "type": "file",
                    "name": posixpath.basename(rel),
                    "path": rel,
                    "title": entry.title,
                    "size": entry.size,
                    "modified": _iso(entry.mtime_ns),
                    "headings": [
                        {"level": lv, "text": tx, "line": ln} for lv, tx, ln in entry.headings
                    ],
                }
            )
        for folder in folders.values():
            folder["children"].sort(key=lambda node: (node["type"] != "dir", node["name"]))
        return {"project": project.slug, "count": len(files), "tree": root}

    # -- read -------------------------------------------------------------------------------

    def read_doc(self, project: ProjectFile, path: str) -> dict[str, Any]:
        rel = clean_path(path)
        files = self.doc_files(project)
        if rel not in files:
            raise NotFound("no such document")
        entry = self._entry(project, rel, files[rel])
        if entry.size > MAX_DOC_BYTES:
            raise ValueError(f"document is larger than {MAX_DOC_BYTES} bytes")
        return {
            "project": project.slug,
            "path": rel,
            "title": entry.title,
            "size": entry.size,
            "modified": _iso(entry.mtime_ns),
            "text": entry.real.read_bytes().decode("utf-8", errors="replace"),
            "headings": [{"level": lv, "text": tx, "line": ln} for lv, tx, ln in entry.headings],
            "links": self._links(project, rel, entry.lines, files),
        }

    def _links(
        self, project: ProjectFile, rel: str, lines: Sequence[str], files: dict[str, Path]
    ) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        fenced = False
        for number, line in enumerate(lines, 1):
            if FENCE.match(line):
                fenced = not fenced
                continue
            if fenced:
                continue
            targets = [(m.group(2), bool(m.group(1))) for m in INLINE_LINK.finditer(line)]
            if reference := REFERENCE_LINK.match(line):
                targets.append((reference.group(1), False))
            for target, image in targets:
                link = self._classify(project, rel, target.strip("<>"), files)
                found.append({"target": target.strip("<>"), "at": number, "image": image, **link})
        return found

    def _classify(
        self, project: ProjectFile, doc: str, target: str, files: dict[str, Path]
    ) -> dict[str, Any]:
        if target.startswith("#"):
            return {"kind": "anchor", "anchor": target[1:]}
        if EXTERNAL.match(target):
            return {"kind": "external", "url": target}
        match = SOURCE_LINK.match(target)
        raw_path = unquote(match.group("path")) if match else ""
        if not match or not raw_path or ":" in raw_path or "\0" in raw_path or "\\" in raw_path:
            return {"kind": "unsupported"}
        joined = (
            raw_path[1:]
            if raw_path.startswith("/")
            else posixpath.join(posixpath.dirname(doc), raw_path)
        )
        rel = posixpath.normpath(joined)
        if rel == "." or rel == ".." or rel.startswith("../"):
            return {"kind": "outside"}
        rest = match.group("rest") or ""
        anchor = rest[1:] if rest.startswith("#") else None
        if rel in files or (rel.endswith(".md") and self._under_docs_root(project, rel)):
            return {"kind": "doc", "path": rel, "exists": rel in files, "anchor": anchor}
        line = int(match.group("line")) if match.group("line") else None
        real = (project.root / rel).resolve()
        if not real.is_relative_to(project.root):
            return {"kind": "outside"}
        try:
            allowed = self.source_file(project, rel) is not None
        except NotFound:
            allowed = False
        exists = real.exists() and not _hidden(real.relative_to(project.root).as_posix())
        return {"kind": "source", "path": rel, "line": line, "allowed": allowed, "exists": exists}

    @staticmethod
    def _under_docs_root(project: ProjectFile, rel: str) -> bool:
        return any(
            rel.startswith(root.relative_to(project.root).as_posix() + "/")
            for root in project.docs_roots
            if root.is_relative_to(project.root)
        )

    def read_source(
        self, project: ProjectFile, path: str, line: int | None = None, window: int = DEFAULT_WINDOW
    ) -> dict[str, Any]:
        """A window of lines from one allowlisted text file, centred on `line` when given."""
        if line is not None and line < 1:
            raise ValueError("line must be 1 or more")
        if not 1 <= window <= MAX_WINDOW:
            raise ValueError(f"window must be from 1 to {MAX_WINDOW}")
        rel = clean_path(path)
        real = self.source_file(project, rel)
        if real.stat().st_size > MAX_SOURCE_BYTES:
            raise ValueError(f"file is larger than {MAX_SOURCE_BYTES} bytes")
        data = real.read_bytes()
        if b"\0" in data[:BINARY_SNIFF]:
            raise ValueError("not a text file")
        try:
            lines = data.decode("utf-8").splitlines()
        except UnicodeDecodeError as error:
            raise ValueError("not a text file") from error
        total = len(lines)
        first = 1 if line is None else max(1, line - window // 2)
        last = min(total, first + window - 1)
        first = max(1, min(first, last - window + 1))
        return {
            "project": project.slug,
            "path": rel,
            "line": line,
            "total_lines": total,
            "start": first,
            "end": last,
            "truncated": first > 1 or last < total,
            "lines": [text[:MAX_LINE_CHARS] for text in lines[first - 1 : last]],
        }

    # -- search -----------------------------------------------------------------------------

    def search(
        self,
        projects: Sequence[ProjectFile],
        query: str,
        whole_word: bool = False,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        """Case-insensitive search of the docs. Docs with a title hit come first, then docs with
        heading-line hits, then by hit count; `hits` is cut at `limit` (and at 10 per doc)."""
        query = query.strip()
        if not query or len(query) > MAX_QUERY:
            raise ValueError(f"q must be 1 to {MAX_QUERY} characters")
        if not 1 <= limit <= MAX_LIMIT:
            raise ValueError(f"limit must be a whole number from 1 to {MAX_LIMIT}")
        escaped = re.escape(query)
        pattern = re.compile(rf"(?<!\w){escaped}(?!\w)" if whole_word else escaped, re.IGNORECASE)
        ranked: list[tuple[tuple[bool, int, int], str, list[dict[str, Any]], int]] = []
        for project in projects:
            for rel, real in self.doc_files(project).items():
                entry = self._entry(project, rel, real)
                hits = self._hits(project, rel, entry, pattern)
                if hits or pattern.search(entry.title):
                    in_headings = sum(1 for hit in hits if hit.pop("is_heading"))
                    score = (bool(pattern.search(entry.title)), in_headings, len(hits))
                    ranked.append((score, f"{project.slug}/{rel}", hits, len(hits)))
        ranked.sort(key=lambda row: (not row[0][0], -row[0][1], -row[0][2], row[1]))
        out = [hit for _, _, hits, _ in ranked for hit in hits[:MAX_HITS_PER_DOC]]
        total = sum(count for *_, count in ranked)
        return {
            "query": query,
            "whole_word": whole_word,
            "limit": limit,
            "docs_matched": len(ranked),
            "total_hits": total,
            "truncated": total > len(out[:limit]),
            "hits": out[:limit],
        }

    @staticmethod
    def _hits(
        project: ProjectFile, rel: str, entry: DocEntry, pattern: "re.Pattern[str]"
    ) -> list[dict[str, Any]]:
        heading_lines = [line for _, _, line in entry.headings]
        found = []
        fenced = False
        for number, text in enumerate(entry.lines, 1):
            if FENCE.match(text):
                fenced = not fenced
            match = pattern.search(text)
            if not match:
                continue
            at = bisect.bisect_right(heading_lines, number) - 1
            start = max(0, match.start() - EXCERPT_CHARS // 2)
            found.append(
                {
                    "project": project.slug,
                    "path": rel,
                    "title": entry.title,
                    "heading": entry.headings[at][1] if at >= 0 else None,
                    "line": number,
                    "excerpt": text[start : start + EXCERPT_CHARS].strip(),
                    "is_heading": not fenced and number in heading_lines,
                }
            )
        found.sort(key=lambda hit: (not hit["is_heading"], hit["line"]))
        return found
