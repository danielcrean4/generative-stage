# Docs view server

The read-only server (port 8781, see [run view](run_view.md)) can also list, serve and search
the markdown docs of every registered project, and show code that docs link to. It only reads.
Editing docs stays in the editor and git.

The server sends markdown as raw text. It does not turn it into HTML: the UI renders it, so the
server has no HTML sanitising to get wrong. Along with the text it sends the outline (headings)
and the links, already sorted into kinds, so the UI can make them work.

## Register a project

A project is any folder with a `studio.project.json` (keys in
[configuration](configuration.md)). The server shows every project in the registry file whose
project file loads, plus any passed with `--project FILE` (repeatable; needs no config file):

```sh
cd server
uv run python -m authoring.readonly_server --port 8781 --project /path/to/studio.project.json
```

The list is built by `registry_for` in `authoring/readonly_server.py`; each file counts once.

What counts as a doc: every `.md` file under `docs_roots`, plus each file in `docs_files` (use
it for top-level files such as `README.md` or `CONTRIBUTING.md`). What a link can open as code: files
under `source_allowlist`. Docs kept outside the project folder are named in `external_docs`
(absolute folders) and listed read-only as `external/<folder name>/...`. With no projects registered the routes work and list nothing.

## Routes

All GET, all under the same Host and Origin checks as the rest of the server. Paths in requests
and answers are relative to the repo.

| Route | Answers |
|---|---|
| `/api/ro/projects` | registered projects |
| `/api/ro/projects/{slug}/docs` | the docs as a tree |
| `/api/ro/projects/{slug}/docs/file?path=docs/README.md` | one doc |
| `/api/ro/projects/{slug}/source?path=ui/hint.gd&line=40&window=200` | a window of one source file |
| `/api/ro/projects/{slug}/docs/search?q=ratchet&whole_word=1&limit=50` | search one project |
| `/api/ro/docs/search?q=ratchet` | search every registered project |

```json
GET /api/ro/projects
{"projects": [{"slug": "my-game", "name": "My Game", "doc_count": 140}]}

GET /api/ro/projects/my-game/docs
{"project": "my-game", "count": 140, "tree": {"type": "dir", "name": "My Game", "path": "",
 "children": [{"type": "dir", "name": "docs", "path": "docs", "children": [
   {"type": "file", "name": "README.md", "path": "docs/README.md", "title": "Docs",
    "size": 4120, "modified": "2026-11-11T02:09:13Z",
    "headings": [{"level": 1, "text": "Docs", "line": 1}]}]}]}}

GET /api/ro/projects/my-game/docs/file?path=docs/README.md
{"path": "docs/README.md", "title": "Docs", "text": "# Docs\n...", "headings": [...],
 "links": [{"target": "../ui/hint.gd:40", "at": 12, "image": false, "kind": "source",
            "path": "ui/hint.gd", "line": 40, "allowed": true, "exists": true}]}

GET /api/ro/projects/my-game/source?path=ui/hint.gd&line=40&window=5
{"path": "ui/hint.gd", "total_lines": 160, "start": 38, "end": 42, "truncated": true,
 "lines": ["var x", "", "", "func _ready() -> void:", "\tpass"]}

GET /api/ro/projects/my-game/docs/search?q=ratchet
{"docs_matched": 5, "total_hits": 7, "truncated": false, "hits": [{"project": "my-game",
 "path": "docs/LOG.md", "title": "Shared agent log", "heading": "2026-11-11 ...", "line": 943,
 "excerpt": "- New ratchet ..."}]}
```

Link kinds in `links` (`at` is the line of the link in the doc; `image` is true for `![..](..)`):

- `doc`: another doc of the same project. `path`, `exists`, `anchor`.
- `source`: a code or other file in the repo, `path` or `path:line`. `allowed` is true only when
  the file is inside `source_allowlist` (only then can `/source` open it); `exists` says whether
  the file is there.
- `external`: an `http`, `https` or `mailto` address. Returned as `url`, never fetched.
- `anchor`: `#heading` in the same doc.
- `outside`: points out of the repo (including through a symlink). Nothing else is said about it.
- `unsupported`: any other form, such as `javascript:`.

Source windows centre on `line` and hold at most `window` lines (default 200, largest 500);
`total_lines` gives the full length. Only UTF-8 text files up to 8 MB; a binary file is refused.

Search is case-insensitive. By default it finds the text anywhere; `whole_word=1` finds it only
as a whole word. Docs whose title matches come first, then docs with a matching heading, then
by number of hits. Each hit carries the nearest heading above it. `limit` is 1 to 200 (default
50); a doc contributes at most 10 hits. The index is built in memory on first use and a file is
read again when its modified time or size changes. There is no database.

## Errors

JSON `{"error": "..."}`. 404 for an unknown project or route and for any path that is not a
listed doc or allowed source file; 400 for a missing or bad argument (`path`, `q`, `line`,
`window`, `limit`), a binary or oversize file; 403 and 405 as in the run view. Messages never
contain file contents or a path outside the repo.

## Safety rules

- A doc is served only if it is in the listing: found under a docs root (or named in
  `docs_files`), resolved with symlinks followed, and still inside that root. A symlink pointing
  outside the repo is not listed, so it cannot be read or searched.
- A source file is served only if its resolved path is inside `source_allowlist` of the same
  project. A project can never reach another project's files.
- Request paths must be relative with no `..`, no empty or `.` parts, no backslash or NUL and no
  part starting with a dot. `.git`, dotfiles and dot folders are never listed or served.
  Encoded forms (`%2e%2e%2f`) are decoded once and then refused by the same rules.
- The project file is checked when it loads: a docs root or allowlist entry that is outside the
  repo or in `.git` stops the server with an error naming the file and key.

## Docs view in the Studio UI

The Angular UI has a **Docs** page (left nav, `/docs`) that shows everything above. It needs this
server running on 8781 (the dev server proxies `/api/ro` to it) and is read-only.

| Address | Shows |
|---|---|
| `/docs` | the registered projects with doc counts, and search across all of them |
| `/docs/<project>` | that project's docs tree (folders open and close, files by title with the path beside it) and a search box |
| `/docs/<project>?q=gpu%20lock&all=1` | the same page with a search running; `all=1` searches every project |
| `/docs/<project>/file?path=docs/README.md#heading` | one doc, rendered, with an outline of its headings; `&line=40` scrolls to that source line (what a search hit uses) |
| `/docs/<project>/source?path=ui/hint.gd&line=40` | a read-only window of a source file with line numbers and the target line marked |

All of these can be reloaded and linked.

How a doc is shown:

- The UI renders the markdown with the bundled `markdown-it` package (MIT, no CDN). Raw HTML in a
  doc is not run: it shows as text. `javascript:` links are refused, images are not loaded (the
  alt text is shown, since the server has no route for repo images), and the result also goes
  through Angular's own sanitiser.
- Headings get GitHub-style anchors (`## Two words` becomes `#two-words`, repeats get `-1`, `-2`).
  A doc's own `#` title is shown as an `h2`, because the page has its own `h1`.
- A link to another doc opens it in the docs view. A `#anchor` scrolls. An external link opens in a
  new tab. A `path` or `path:line` link opens the source pane. A link to a doc that does not exist
  is plain text marked "missing". A source link outside `source_allowlist` opens the pane with the
  note "not shown: outside the folders this project lets the docs view open" (a link to a folder
  gets the same note, because the server only opens files).
- When the server is not running, the page says so and shows the start command.

Known gaps: repo images are not shown; the file answer carries `project`, `size` and `modified`
that the example above leaves out; no doc in the three registered projects links to a `path:line`
in an allowed folder yet, so the line marker is only reached through a hand-made address or a
search hit.

