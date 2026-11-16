"""Adapter entries: the only place a command is defined (plain Python; docs/adapters.md is the format's owner).

    python3 -I pipeline/adapter_config.py check [FILE]   validate a machine config's adapters and print them
    python3 -I pipeline/adapter_config.py show ID        print one entry as the runner would use it

An adapter entry lives in the machine config (machine.py), a file a person edits. It says how to run one model or
program: `argv` (a list, never a shell line) with {placeholders}, `env`, `cwd`, what it `requires` of the host, its
network `sandbox`, `timeout_seconds`, whether it holds the GPU lock, the `model` it runs and a `licence` note.
adapters/adapter.schema.json is the same contract as a JSON Schema; server/tests/test_adapter_schema.py keeps the two
in step.

Trust rule: project data, pipeline files, resolved jobs and API requests choose an adapter by id (`pick`); nothing
they hold becomes part of a command except the values of the data placeholders, each substituted into one argv
element in a single pass, so a value can never add an argument, a program or a variable.

Where entries come from, in order (an id may be defined once):
    1. the stand-in entries in adapters/standin/adapters.json (always there; no model, CPU only)
    2. the `adapters` list of the machine config
The default adapter of a kind: `defaults[kind]` from the machine config, else the stand-in of that kind.
"""
import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import host  # noqa: E402
import machine  # noqa: E402
import provenance  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
STANDIN_FILE = REPO / "adapters" / "standin" / "adapters.json"
KINDS = ("text", "image", "image-to-mesh", "material", "review", "rig", "motion", "rules", "render", "measure")
OUTPUT = {"text": "text.txt", "image": "image.png", "image-to-mesh": "mesh.glb", "review": "review.json",
          "rig": "rigged.glb", "motion": "animated.glb", "rules": "rows.json", "render": "still.png", "measure": "measure.json"}
SYSTEM = ("python", "repo")  # placeholders this program fills, allowed anywhere
DATA = {  # placeholders a run fills from its stage, allowed only in argv[1:]; any kind may also use params.<name>
    "text": ("prompt", "seed", "output", "out_dir"),
    "image": ("prompt", "negative", "seed", "width", "height", "output", "out_dir"),
    "image-to-mesh": ("image", "seed", "output", "out_dir"),
    "material": ("image", "seed", "out_dir"),
    "review": ("image", "prompt", "seed", "output", "out_dir"),
    "rig": ("mesh", "seed", "output", "out_dir"),  # also writes rig.json (the fitted rig profile) in out_dir
    "motion": ("mesh", "rig", "seed", "output", "out_dir"),
    # the parametric kinds (docs/parametric.md): files of this run's own making, so no model and no prompt
    "rules": ("schema", "kit", "subject", "seed", "count", "output", "out_dir"),
    "render": ("row", "schema", "seed", "output", "out_dir"),
    "measure": ("row", "image", "schema", "seed", "output", "out_dir"),
}
NETWORK = ("deny", "loopback", "allow")
REQUIRED = ("id", "kind", "argv", "sandbox", "licence")
OPTIONAL = ("description", "env", "cwd", "requires", "timeout_seconds", "gpu", "model")
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}")  # the same rule as a pipeline stage id
ENV_NAME = re.compile(r"[A-Z_][A-Z0-9_]*")
TOKEN = re.compile(r"\{\{|\}\}|\{([^{}]*)\}|[{}]")
PARAM = re.compile(r"params\.[A-Za-z][A-Za-z0-9_]{0,63}")
DEFAULT_TIMEOUT = 1800
MAX_TIMEOUT = 86400
MAX_ARGS = 128
MAX_TEXT = 4096


class AdapterError(ValueError):
    """An entry, a default or a choice is wrong; the message names the file, the entry and the key."""


@dataclass(frozen=True)
class Adapter:
    id: str
    kind: str
    argv: tuple
    sandbox: str
    licence: str
    origin: str             # where the entry came from: the machine config file or "built in"
    env: dict = field(default_factory=dict)
    cwd: str | None = None
    requires: tuple = ()
    timeout_seconds: int = DEFAULT_TIMEOUT
    gpu: bool = False
    model: dict = field(default_factory=dict)  # {"name": text, "weights": path (optional)}
    description: str = ""

    def needs(self):
        """Everything the host must offer: the entry's requires plus what its sandbox needs."""
        extra = [host.NETWORK[self.sandbox]] if self.sandbox in host.NETWORK else []
        return tuple(dict.fromkeys((*self.requires, *extra)))


@dataclass(frozen=True)
class Adapters:
    entries: dict           # id -> Adapter
    defaults: dict          # kind -> id
    source: str             # the machine config file, for messages

    def pick(self, chosen, kind):
        """The entry a stage asked for by id (CHOSEN), or the default of KIND when CHOSEN is None. Anything other
        than an id or None is refused; an unknown id is an error, never a fall back to a default."""
        if chosen is None:
            if kind not in self.defaults:
                raise AdapterError(f"{self.source}: no adapter of kind '{kind}' is configured "
                                   f"(add one to 'adapters' and name it in 'defaults')")
            chosen = self.defaults[kind]
        elif not isinstance(chosen, str) or not IDENTIFIER.fullmatch(chosen):
            raise AdapterError(f"an adapter is chosen by its id (letters, digits, '_' and '-'), not {_short(chosen)}")
        entry = self.entries.get(chosen)
        if entry is None:
            raise AdapterError(f"{self.source}: no adapter '{chosen}' is configured (configured: "
                               f"{', '.join(sorted(self.entries))})")
        if entry.kind != kind:
            raise AdapterError(f"adapter '{chosen}' is of kind '{entry.kind}'; this stage needs kind '{kind}'")
        return entry


def _short(value):
    text = json.dumps(value) if not isinstance(value, str) else repr(value)
    return text if len(text) <= 60 else text[:57] + "..."


def placeholders(text):
    """The placeholder names in TEXT; AdapterError for a lone brace ('{{' and '}}' are literal braces)."""
    names = []
    for match in TOKEN.finditer(text):
        token = match.group(0)
        if token in ("{{", "}}"):
            continue
        if match.group(1) is None:
            raise AdapterError(f"a lone '{token}' (write '{token * 2}' for a literal brace)")
        names.append(match.group(1))
    return names


def _check_template(text, allowed, at):
    try:
        names = placeholders(text)
    except AdapterError as error:
        raise AdapterError(f"{at}: {error}") from None
    for name in names:
        if name not in allowed and not (allowed is not SYSTEM and PARAM.fullmatch(name)):
            raise AdapterError(f"{at}: unknown placeholder {{{name}}} (allowed here: "
                               f"{', '.join('{' + n + '}' for n in allowed) or 'none'}"
                               + (", {params.NAME}" if allowed is not SYSTEM else "") + ")")


def _text(value, at, limit=MAX_TEXT):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise AdapterError(f"{at}: expected text of 1 to {limit} characters, got {_short(value)}")
    return value


def parse_entry(raw, origin):
    """One validated Adapter from RAW (a parsed JSON object); AdapterError names ORIGIN, the entry and the key."""
    label = f"{origin}: adapter {raw.get('id')!r}" if isinstance(raw, dict) and isinstance(raw.get("id"), str) \
        else f"{origin}: adapter entry"
    if not isinstance(raw, dict):
        raise AdapterError(f"{label}: must be an object")
    for key in REQUIRED:
        if key not in raw:
            raise AdapterError(f"{label}: key '{key}' is required")
    for key in raw:
        if key not in REQUIRED and key not in OPTIONAL:
            raise AdapterError(f"{label}: key '{key}' is not known (known: {', '.join((*REQUIRED, *OPTIONAL))})")
    if not isinstance(raw["id"], str) or not IDENTIFIER.fullmatch(raw["id"]):
        raise AdapterError(f"{label}: key 'id': letters, digits, '_' and '-', up to 80, starting with a letter or digit")
    kind = raw["kind"]
    if kind not in KINDS:
        raise AdapterError(f"{label}: key 'kind': {_short(kind)} is not a kind (kinds: {', '.join(KINDS)})")
    argv = raw["argv"]
    if not isinstance(argv, list) or not 1 <= len(argv) <= MAX_ARGS:
        raise AdapterError(f"{label}: key 'argv': expected a list of 1 to {MAX_ARGS} strings (a program and its "
                           f"arguments, never a shell line)")
    for index, part in enumerate(argv):
        _text(part, f"{label}: argv[{index}]")
        _check_template(part, SYSTEM if index == 0 else (*SYSTEM, *DATA[kind]), f"{label}: argv[{index}]")
    env = raw.get("env", {})
    if not isinstance(env, dict):
        raise AdapterError(f"{label}: key 'env': expected an object of NAME: text")
    for name, value in env.items():
        if not ENV_NAME.fullmatch(name):
            raise AdapterError(f"{label}: env {name!r}: names are upper-case letters, digits and '_'")
        if not isinstance(value, str) or len(value) > MAX_TEXT:
            raise AdapterError(f"{label}: env {name}: expected text up to {MAX_TEXT} characters")
        _check_template(value, SYSTEM, f"{label}: env {name}")
    cwd = raw.get("cwd")
    if cwd is not None:
        _check_template(_text(cwd, f"{label}: key 'cwd'"), SYSTEM, f"{label}: key 'cwd'")
    requires = raw.get("requires", [])
    if not isinstance(requires, list) or not all(isinstance(r, str) for r in requires):
        raise AdapterError(f"{label}: key 'requires': expected a list of capability names ({', '.join(host.KNOWN)})")
    unknown = [r for r in requires if r not in host.KNOWN]
    if unknown:
        raise AdapterError(f"{label}: key 'requires': unknown capability {', '.join(unknown)} "
                           f"(known: {', '.join(host.KNOWN)})")
    sandbox = raw["sandbox"]
    if not isinstance(sandbox, dict) or set(sandbox) != {"network"} or sandbox["network"] not in NETWORK:
        raise AdapterError(f'{label}: key \'sandbox\': expected {{"network": "deny" | "loopback" | "allow"}}')
    timeout = raw.get("timeout_seconds", DEFAULT_TIMEOUT)
    if type(timeout) is not int or not 1 <= timeout <= MAX_TIMEOUT:
        raise AdapterError(f"{label}: key 'timeout_seconds': a whole number from 1 to {MAX_TIMEOUT}")
    gpu = raw.get("gpu", False)
    if type(gpu) is not bool:
        raise AdapterError(f"{label}: key 'gpu': true or false")
    model = raw.get("model", {})
    if "model" in raw and (not isinstance(model, dict) or set(model) - {"name", "weights"} or "name" not in model):
        raise AdapterError(f'{label}: key \'model\': expected {{"name": text, "weights": path (optional)}}')
    if "name" in model:
        _text(model["name"], f"{label}: model.name", 200)
    if "weights" in model:
        _check_template(_text(model["weights"], f"{label}: model.weights"), SYSTEM, f"{label}: model.weights")
    description = raw.get("description", "")
    if description:
        _text(description, f"{label}: key 'description'", 1000)
    return Adapter(id=raw["id"], kind=kind, argv=tuple(argv), sandbox=sandbox["network"],
                   licence=_text(raw["licence"], f"{label}: key 'licence'", 2000), origin=origin, env=dict(env),
                   cwd=cwd, requires=tuple(requires), timeout_seconds=timeout, gpu=gpu, model=dict(model),
                   description=description)


def standin_entries():
    raw = json.loads(STANDIN_FILE.read_text())
    return [parse_entry(entry, "built in") for entry in raw["adapters"]]


def parse(raw, source):
    """Adapters from a parsed machine config RAW (an object); SOURCE names it in messages."""
    entries = {}
    for entry in standin_entries():
        entries[entry.id] = entry
    listed = raw.get("adapters", [])
    if not isinstance(listed, list):
        raise AdapterError(f"{source}: key 'adapters': expected a list of adapter entries")
    for index, item in enumerate(listed):
        entry = parse_entry(item, f"{source}: adapters[{index}]")
        if entry.id in entries:
            raise AdapterError(f"{source}: adapters[{index}]: id '{entry.id}' is already defined "
                               f"({entries[entry.id].origin})")
        entries[entry.id] = entry
    defaults = {entry.kind: entry.id for entry in entries.values() if entry.origin == "built in"}
    chosen = raw.get("defaults", {})
    if not isinstance(chosen, dict):
        raise AdapterError(f"{source}: key 'defaults': expected an object of kind: adapter id")
    for kind, ident in chosen.items():
        if kind not in KINDS:
            raise AdapterError(f"{source}: defaults: {kind!r} is not a kind (kinds: {', '.join(KINDS)})")
        if ident not in entries:
            raise AdapterError(f"{source}: defaults.{kind}: no adapter '{ident}' is configured")
        if entries[ident].kind != kind:
            raise AdapterError(f"{source}: defaults.{kind}: adapter '{ident}' is of kind '{entries[ident].kind}'")
        defaults[kind] = ident
    return Adapters(entries, defaults, source)


def from_machine(environ=None, home=None):
    """The Adapters of this computer's machine config (an absent default file gives the stand-ins only)."""
    try:
        raw, file = machine.load(environ, home)
        return parse(raw, str(file))
    except machine.MachineError as error:
        raise AdapterError(str(error)) from error


def _home_expanded(text, home):
    return str(home) + text[1:] if text == "~" or text.startswith("~/") else text


def render(text, values):
    """TEXT with each {name} replaced by str(VALUES[name]) in one pass; '{{' and '}}' become braces. A value is never
    scanned again, so a value holding '{out_dir}' stays as written. KeyError-free: a missing name is AdapterError."""
    def one(match):
        token = match.group(0)
        if token in ("{{", "}}"):
            return token[0]
        name = match.group(1)
        if name not in values:
            raise AdapterError(f"no value for the placeholder {{{name}}}")
        value = values[name]
        if isinstance(value, bool) or not isinstance(value, (str, int, float, Path)):
            raise AdapterError(f"the placeholder {{{name}}} takes text or a number, not {_short(value)}")
        return str(value)
    placeholders(text)  # a lone brace is refused before anything is replaced
    return TOKEN.sub(one, text)


def system_values():
    return {"python": sys.executable, "repo": str(REPO)}


def command(entry, data, home=None):
    """(argv, env, cwd) for ENTRY with the run's DATA values ({name: value}; params as params.<name>). Data names
    the kind does not take are refused, so a run cannot reach a placeholder the entry's kind does not allow."""
    home = Path.home() if home is None else Path(home)
    allowed = set(DATA[entry.kind])
    extra = [name for name in data if name not in allowed and not PARAM.fullmatch(name)]
    if extra:
        raise AdapterError(f"adapter '{entry.id}' (kind {entry.kind}) takes no value {', '.join(sorted(extra))}")
    system = system_values()
    argv = [render(_home_expanded(entry.argv[0], home), system)]
    argv += [render(_home_expanded(part, home), {**system, **data}) for part in entry.argv[1:]]
    env = {name: render(_home_expanded(value, home), system) for name, value in entry.env.items()}
    cwd = render(_home_expanded(entry.cwd, home), system) if entry.cwd else None
    return argv, env, cwd


def program(entry, home=None):
    """The program ENTRY runs (argv[0] with {python} and {repo} filled and ~ expanded)."""
    return Path(render(_home_expanded(entry.argv[0], Path.home() if home is None else Path(home)), system_values()))


def weights_path(entry, home=None):
    if "weights" not in entry.model:
        return None
    return Path(render(_home_expanded(entry.model["weights"], Path.home() if home is None else home), system_values()))


def identity(entry, home=None):
    """What the reuse key holds for ENTRY, known before it runs: its id and kind, a hash of its command template,
    the hash of each fixed argv element that is a file (the program and its scripts) and the hash of its weights.
    A missing weights path is AdapterError (the model is not installed where the entry says)."""
    home = Path.home() if home is None else Path(home)
    system = system_values()
    template = {"argv": list(entry.argv), "env": entry.env, "cwd": entry.cwd, "model": entry.model}
    found = {}
    for index, part in enumerate(entry.argv):
        if index and set(placeholders(part)) - set(SYSTEM):
            continue
        path = Path(render(_home_expanded(part, home), system))
        if path.is_absolute() and path.is_file():
            found[str(index)] = provenance.digest(path)
    result = {"adapter": entry.id, "kind": entry.kind, "model": entry.model.get("name"),
              "template_sha256": provenance.fingerprint(template), "files_sha256": found}
    weights = weights_path(entry, home)
    if weights is not None:
        if weights.is_dir():
            result["weights_sha256"] = provenance.cached_model_identity(weights)["sha256"]
        elif weights.is_file():
            result["weights_sha256"] = provenance.digest(weights)
        else:
            raise AdapterError(f"adapter '{entry.id}' ({entry.origin}): model.weights {weights} does not exist")
    return result


def describe(entry):
    """A JSON-ready view of ENTRY for people (show, the docs)."""
    return {"id": entry.id, "kind": entry.kind, "origin": entry.origin, "argv": list(entry.argv), "env": entry.env,
            "cwd": entry.cwd, "requires": list(entry.needs()), "sandbox": {"network": entry.sandbox},
            "timeout_seconds": entry.timeout_seconds, "gpu": entry.gpu, "model": entry.model,
            "licence": entry.licence}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check").add_argument("file", nargs="?", type=Path)
    commands.add_parser("show").add_argument("id")
    args = parser.parse_args(argv)
    try:
        if args.command == "check" and args.file:
            adapters = from_machine({machine.CONFIG_ENV: str(args.file)})
        else:
            adapters = from_machine()
        if args.command == "show":
            entry = adapters.entries.get(args.id)
            if entry is None:
                raise AdapterError(f"no adapter '{args.id}' (configured: {', '.join(sorted(adapters.entries))})")
            print(json.dumps(describe(entry), indent=2))
            return 0
    except AdapterError as error:
        print(error, file=sys.stderr)
        return 1
    for entry in sorted(adapters.entries.values(), key=lambda e: (e.kind, e.id)):
        default = " (default)" if adapters.defaults.get(entry.kind) == entry.id else ""
        problems = host.unmet(entry.needs())
        state = "ready" if not problems else "not on this host: " + "; ".join(problems)
        print(f"{entry.kind:14} {entry.id}{default}  [{entry.origin}]  {state}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
