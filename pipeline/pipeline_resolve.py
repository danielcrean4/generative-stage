"""Combine a pipeline file with a subject, motif, style pack, contract and seed into one resolved job (plain Python).

    python3 -I pipeline/pipeline_resolve.py --pipeline P --subject S.json --motif M.json --style DIR_OR_JSON \\
        --contract C.json --seed N [--lint] (--dry-run | --out FILE)

Dry run only: nothing here starts a model or touches the GPU. The resolved job holds, per stage, the tool,
model, exact params, ONLY the values the stage declares in `reads`, its inputs and outputs, and a
`key_inputs` hash (tool, model, params, gate, values read) for staleness; the concept stage also holds
its final prompt. `sources` records the sha256 of every source file and of the flattened style.

The subject, motif, style and contract shapes read here are provisional (docs/pipeline_files.md); the
style pack format is owned by the style pack design (D25). Each shape is validated in one place below and
every problem is a line `FILE: POINTER: message`, as in pipeline_file.
"""
import argparse
import copy
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import normaliser_common as common
import pipeline_file as pf

RESOLVED_VERSION = 1
PLACEHOLDER = re.compile(r"\{([^{}]*)\}")
TEMPLATE_VARIABLES = ("subject", "motif")
SIGNED_AXIS = re.compile(r"[+-][xyz]")
HEX_COLOUR = re.compile(r"#[0-9a-fA-F]{6}")
STYLE_FILE = "style.json"
STYLE_KEYS = ("name", "version", "prompt", "palette", "surface", "presentation", "terms")
PROMPT_JOIN = ", "
KEY_HEX = 12  # characters of key_inputs shown in the dry-run table


def canonical_sha256(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def signed_axis(value):
    if not isinstance(value, str) or not SIGNED_AXIS.fullmatch(value):
        raise ValueError('must be a signed axis such as "+y" or "-z"')


def string_list(value):
    if not isinstance(value, list) or not value or not all(isinstance(v, str) and v.strip() for v in value):
        raise ValueError("must be a non-empty list of non-empty strings")


def hex_colours(value):
    if not isinstance(value, list) or not value or not all(isinstance(v, str) and HEX_COLOUR.fullmatch(v) for v in value):
        raise ValueError('must be a non-empty list of "#rrggbb" colours')


def hex_colour(value):
    if not isinstance(value, str) or not HEX_COLOUR.fullmatch(value):
        raise ValueError('must be a "#rrggbb" colour')


@dataclass(frozen=True, eq=False)
class Source:
    """A loaded source file: where it came from, its sha256 and its validated body."""
    path: Path
    sha256: str
    body: dict


def _load_object(path, required, optional, rules, what):
    raw, sha = pf.read_json(path, what)
    check = pf.Checker(path)
    if check.keys(raw, pf.ROOT, required, optional):
        for key, rule in rules.items():
            if key in raw:
                check.value("/" + key, rule, raw[key])
    check.raise_if_any()
    return Source(Path(path), sha, raw)


def load_subject(path):
    """subject.json: id, kind, text, optional colours (["#rrggbb"]), materials ([text]) and hair_colour ("#rrggbb", read by colour_head)."""
    return _load_object(path, ("id", "kind", "text"), ("colours", "materials", "hair_colour"),
                        {"id": pf.identifier, "kind": pf.identifier, "text": pf.text, "colours": hex_colours,
                         "materials": string_list, "hair_colour": hex_colour}, "subject")


def load_motif(path):
    """motif.json: id, text."""
    return _load_object(path, ("id", "text"), (), {"id": pf.identifier, "text": pf.text}, "motif")


def load_contract(path):
    """contract.json: kind, up_axis, front_axis, target_size, scale_axis, face_budget."""
    rules = {"kind": pf.identifier, "up_axis": signed_axis, "front_axis": signed_axis, "target_size": common.positive_number,
             "scale_axis": common.one_of("largest", "x", "y", "z"), "face_budget": common.positive_int}
    source = _load_object(path, tuple(rules), (), rules, "contract")
    body = source.body
    if body["up_axis"][1] == body["front_axis"][1]:
        raise pf.PipelineError([f"{path}: /front_axis: must be a different axis from up_axis"])
    return source


def _template(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("must be a non-empty string")
    names = PLACEHOLDER.findall(value)
    for name in names:
        if name not in TEMPLATE_VARIABLES:
            raise ValueError(f"has the variable {{{name}}}; only {{subject}} and {{motif}} are allowed")
    for name in TEMPLATE_VARIABLES:
        if name not in names:
            raise ValueError(f"must contain {{{name}}}")


def _check_style_file(raw, path):
    check = pf.Checker(path)
    if check.keys(raw, pf.ROOT, ("id", "extends"), STYLE_KEYS):
        check.value("/id", pf.identifier, raw["id"])
        if raw.get("extends") is not None and "extends" in raw:
            check.value("/extends", pf.identifier, raw["extends"])
        rules = {"name": pf.text, "version": common.positive_int, "palette": pf.text, "presentation": pf.text,
                 "terms": string_list}
        for key, rule in rules.items():
            if key in raw:
                check.value("/" + key, rule, raw[key])
        if "surface" in raw and not isinstance(raw["surface"], dict):
            check.add("/surface", "must be an object")
        if "prompt" in raw and check.keys(raw["prompt"], "/prompt", (), ("templates", "negative")):
            prompt = raw["prompt"]
            if "negative" in prompt and not isinstance(prompt["negative"], str):
                check.add("/prompt/negative", "must be a string")
            if "templates" in prompt and check.keys(prompt["templates"], "/prompt/templates", (), tuple(prompt["templates"])):
                for kind, template in prompt["templates"].items():
                    check.value(f"/prompt/templates/{kind}", _template, template)
    check.raise_if_any()


def _merge(base, over):
    """Child over parent: objects merge key by key, everything else (strings, numbers, lists) is replaced."""
    merged = copy.deepcopy(base)
    for key, value in over.items():
        merged[key] = _merge(merged[key], value) if isinstance(value, dict) and isinstance(merged.get(key), dict) else copy.deepcopy(value)
    return merged


@dataclass(frozen=True, eq=False)
class Style:
    id: str
    chain: tuple     # (id, path, sha256) from the root pack to this one
    flat: dict       # the flattened pack (no `extends`)
    flat_sha256: str
    terms: tuple     # the style words of every pack in the chain
    origins: dict = field(default_factory=dict)  # dotted key of every value in the flattened pack -> {id, version, sha256} of the pack that supplied it


def _find_pack(root, name, leaf_path):
    forms = [p for p in (root / name / STYLE_FILE, root / f"{name}.json") if p.is_file()]
    if not forms:
        raise pf.PipelineError([f"{leaf_path}: /extends: parent style '{name}' not found (looked for {root / name / STYLE_FILE} and {root / (name + '.json')})"])
    if len(forms) > 1:
        raise pf.PipelineError([f"{leaf_path}: /extends: parent style '{name}' is ambiguous: {forms[0]} and {forms[1]}"])
    return forms[0]


def _leaves(value, prefix=""):
    """The dotted key of every non-object value in VALUE (a list or string is a leaf)."""
    if isinstance(value, dict):
        return [leaf for key, inner in value.items() for leaf in _leaves(inner, f"{prefix}.{key}" if prefix else key)]
    return [prefix]


def _origins(chain):
    """Which pack of CHAIN (leaf first) supplied each key of the flattened pack: the nearest to the leaf that sets it."""
    origins = {}
    for pack_id, _, sha, raw in reversed(chain):
        info = {"id": pack_id, "version": raw.get("version"), "sha256": sha}
        for key in _leaves({k: v for k, v in raw.items() if k not in ("extends", "id")}):
            origins[key] = info
    return origins


def load_style(path):
    """Load a style pack (a folder holding style.json, or a .json file) and flatten its `extends` chain.

    A parent is the sibling `<name>/style.json` or `<name>.json` in the folder that holds this pack.
    """
    path = Path(path)
    leaf_file = path / STYLE_FILE if path.is_dir() else path
    root = path.parent
    chain, seen, current, current_file = [], [], None, leaf_file
    while True:
        raw, sha = pf.read_json(current_file, "style")
        _check_style_file(raw, current_file)
        if current_file == leaf_file and path.is_dir() and path.name != raw["id"]:
            raise pf.PipelineError([f"{current_file}: /id: is '{raw['id']}' but the folder is '{path.name}'"])
        if current is not None and raw["id"] != current:
            raise pf.PipelineError([f"{current_file}: /id: is '{raw['id']}' but a style extends '{current}'"])
        if raw["id"] in seen:
            raise pf.PipelineError([f"{current_file}: /extends: cycle: {' -> '.join([*seen, raw['id']])}"])
        seen.append(raw["id"])
        chain.append((raw["id"], current_file, sha, raw))
        if raw["extends"] is None:
            break
        current = raw["extends"]
        current_file = _find_pack(root, current, leaf_file)
    flat = {}
    for _, _, _, raw in reversed(chain):
        flat = _merge(flat, {k: v for k, v in raw.items() if k != "extends"})
    terms = tuple(dict.fromkeys(t for _, _, _, raw in reversed(chain) for t in raw.get("terms", [])))
    return Style(flat["id"], tuple((i, p, s) for i, p, s, _ in reversed(chain)), flat, canonical_sha256(flat), terms, _origins(chain))


def fill(template, subject_text, motif_text):
    """Fill {subject} and {motif} in one pass, so a value that looks like a variable is not filled again."""
    values = {"subject": subject_text, "motif": motif_text}
    return PLACEHOLDER.sub(lambda match: values[match.group(1)], template)


def _source(kind, ident=None, **more):
    return {"kind": kind, **({"id": ident} if ident is not None else {}), **more}


def assemble_parts(template, subject_text, motif_text, capture, sources=None):
    """The concept prompt as an ordered list of `(text, source)` pieces whose concatenation is the prompt: the style
    template filled in one pass (its own words, the subject, the motif), then the capture words in the order
    background, framing, view (view only when the pipeline's capture has one), each after a PROMPT_JOIN glue piece.
    SOURCES names where each piece came from (keys `template`, `subject`, `motif`, `capture` for the shared source of
    each capture words block); a missing key leaves the piece with a kind and no id."""
    sources = sources or {}
    pieces, at = [], 0
    for match in PLACEHOLDER.finditer(template):
        pieces.append((template[at:match.start()], sources.get("template", _source("style_pack"))))
        name = match.group(1)
        pieces.append(({"subject": subject_text, "motif": motif_text}[name], sources.get(name, _source(name))))
        at = match.end()
    pieces.append((template[at:], sources.get("template", _source("style_pack"))))
    while pieces:  # the filled template loses its trailing commas and spaces, from the last piece back
        text, source = pieces[-1]
        trimmed = text.rstrip(" ,")
        if trimmed:
            pieces[-1] = (trimmed, source)
            break
        pieces.pop()
    pieces = [piece for piece in pieces if piece[0]]
    blocks = [("capture.background.words", capture["background"]["words"]), ("capture.framing.words", capture["framing"]["words"])]
    if "view" in capture:
        blocks.append(("capture.view.words", capture["view"]["words"]))
    for key, words in blocks:
        pieces.append((PROMPT_JOIN, _source("glue")))
        pieces.append((words, {**sources.get("capture", _source("pipeline")), "key": key}))
    return pieces


def assemble_prompt(template, subject_text, motif_text, capture):
    """The concept prompt (see assemble_parts)."""
    return "".join(text for text, _ in assemble_parts(template, subject_text, motif_text, capture))


def with_offsets(pieces):
    """PIECES as the recorded `prompt_parts`: `{text, source, start, end}` with the character offsets of the piece in the
    joined string (Unicode code points). The joined string is the prompt."""
    parts, at = [], 0
    for text, source in pieces:
        parts.append({"text": text, "source": source, "start": at, "end": at + len(text)})
        at += len(text)
    return parts


def lint(pipeline, subject, motif, style):
    """Problem lines for every style term (any pack in the style's chain) found in the subject text, motif
    text or the pipeline's capture words; whole words, case-insensitive."""
    places = [(subject.path, "/text", subject.body["text"]), (motif.path, "/text", motif.body["text"]),
              (pipeline.path, "/capture/background/words", pipeline.capture["background"]["words"]),
              (pipeline.path, "/capture/framing/words", pipeline.capture["framing"]["words"])]
    if "view" in pipeline.capture:
        places.append((pipeline.path, "/capture/view/words", pipeline.capture["view"]["words"]))
    problems = []
    for term in style.terms:
        pattern = re.compile(r"(?<!\w)" + re.escape(term) + r"(?!\w)", re.IGNORECASE)
        for where, at, words in places:
            if pattern.search(words):
                problems.append(f"{where}: {at}: contains the style term '{term}' (a style word belongs in the style pack '{style.id}', not here)")
    return problems


def _style_value(style, name, kind):
    flat = style.flat
    if name == "style.prompt":
        prompt = flat.get("prompt", {})
        return {"template": prompt.get("templates", {}).get(kind), "negative": prompt.get("negative")}
    return flat.get(name.split(".", 1)[1])


def _style_source(style, key):
    """The source of the style value at KEY: the pack of the chain that set it (and its version and hash)."""
    origin = style.origins[key]
    return _source("style_pack", origin["id"], key=key, **{k: origin[k] for k in ("version", "sha256") if origin[k] is not None})


def resolve(pipeline, subject, motif, style, contract, seed):
    """The fully resolved job (a plain dict) or a PipelineError listing every problem."""
    problems = []
    if type(seed) is not int or not 0 <= seed < 2**32:
        problems.append("seed: must be a whole number from 0 to 2**32 - 1")
    elif seed + max([s.retry["max"] for s in pipeline.stages if s.retry] or [0]) >= 2**32:
        problems.append("seed: seed plus the largest retry.max must stay below 2**32")
    for label, source in (("subject", subject), ("contract", contract)):
        if source.body["kind"] != pipeline.kind:
            problems.append(f"{source.path}: /kind: is '{source.body['kind']}' but the pipeline {pipeline.path} makes '{pipeline.kind}'")
    prompt = style.flat.get("prompt", {})
    if pipeline.kind not in prompt.get("templates", {}):
        problems.append(f"{style.chain[-1][1]}: /prompt/templates/{pipeline.kind}: the style '{style.id}' has no template for kind '{pipeline.kind}'")
    if "negative" not in prompt:
        problems.append(f"{style.chain[-1][1]}: /prompt/negative: the style '{style.id}' sets no negative prompt (own or inherited)")
    values = {"capture": pipeline.capture, "capture.background": pipeline.capture["background"],
              "subject": {k: v for k, v in subject.body.items()}, "motif": dict(motif.body),
              "contract": {k: v for k, v in contract.body.items() if k != "kind"}}
    if "view" in pipeline.capture:
        values["capture.view"] = pipeline.capture["view"]
    stages = []
    for index, stage in enumerate(pipeline.stages):
        read = {}
        for name in stage.reads:
            if name.startswith("style."):
                value = _style_value(style, name, pipeline.kind)
                if value is None or (name == "style.prompt" and (value["template"] is None or value["negative"] is None)):
                    problems.append(f"{pipeline.path}: {pf.pointer('stages', index, 'reads')}: stage '{stage.id}' reads {name} but the style '{style.id}' sets none")
                    continue
            else:
                value = values[name]
            read[name] = copy.deepcopy(value)
        gate = stage.gate
        if stage.tool == "mesh_gates":
            _, gate_problems = pf.gate_config(pipeline, stage, contract.body["face_budget"])
            problems.extend(gate_problems)
        entry = {"id": stage.id, "label": stage.label, "tool": stage.tool, "model": stage.model, "inputs": dict(stage.inputs),
                 "params": copy.deepcopy(stage.params), "gate": copy.deepcopy(gate), "retry": copy.deepcopy(stage.retry),
                 "outputs": list(stage.outputs), "reads": read}
        if stage.tool == "concept" and len(read) == len(stage.reads):
            template, negative = read["style.prompt"]["template"], read["style.prompt"]["negative"]
            parts = with_offsets(assemble_parts(template, read["subject"]["text"], read["motif"]["text"], read["capture"], {
                "template": _style_source(style, f"prompt.templates.{pipeline.kind}"),
                "subject": _source("subject", subject.body["id"], sha256=subject.sha256),
                "motif": _source("motif", motif.body["id"], sha256=motif.sha256),
                "capture": _source("pipeline", pipeline.id, sha256=pipeline.sha256)}))
            entry["prompt"] = "".join(p["text"] for p in parts)
            entry["prompt_parts"] = parts
            entry["negative_parts"] = with_offsets([(negative, _style_source(style, "prompt.negative"))])
        entry["key_inputs"] = canonical_sha256({"tool": stage.tool, "model": stage.model, "params": entry["params"],
                                                "gate": entry["gate"], "reads": read})
        stages.append(entry)
    if problems:
        raise pf.PipelineError(problems)
    return {"resolved_version": RESOLVED_VERSION, "seed": seed,
            "pipeline": {"id": pipeline.id, "name": pipeline.name, "kind": pipeline.kind, "version": pipeline.version},
            "sources": {"pipeline": {"id": pipeline.id, "sha256": pipeline.sha256},
                        "subject": {"id": subject.body["id"], "sha256": subject.sha256},
                        "motif": {"id": motif.body["id"], "sha256": motif.sha256},
                        "contract": {"sha256": contract.sha256},
                        "style": {"id": style.id, "flattened_sha256": style.flat_sha256,
                                  "chain": [{"id": i, "sha256": s} for i, _, s in style.chain]}},
            "stages": stages}


def dry_run_text(job):
    """What --dry-run prints: each concept prompt, then the stage table."""
    lines = []
    for stage in job["stages"]:
        if "prompt" in stage:
            lines += [f"prompt ({stage['id']}): {stage['prompt']}", f"negative ({stage['id']}): {stage['reads']['style.prompt']['negative']}"]
    rows = [("stage", "tool", "model", "reads", "key_inputs")]
    rows += [(s["id"], s["tool"], s["model"] or "-", ", ".join(s["reads"]) or "-", s["key_inputs"][:KEY_HEX]) for s in job["stages"]]
    widths = [max(len(r[c]) for r in rows) for c in range(len(rows[0]))]
    lines += ["  ".join(cell.ljust(w) for cell, w in zip(row, widths)).rstrip() for row in rows]
    style = job["sources"]["style"]
    lines.append(f"style {style['id']} flattened_sha256 {style['flattened_sha256'][:KEY_HEX]}")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ("pipeline", "subject", "motif", "style", "contract"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--lint", action="store_true", help="fail when a style term appears in the subject, motif or capture words")
    parser.add_argument("--dry-run", action="store_true", help="print the prompt and the stage table; write nothing")
    parser.add_argument("--out", type=Path, help="where to write the resolved job (not with --dry-run)")
    args = parser.parse_args(argv)
    if args.dry_run == (args.out is not None):
        parser.error("give exactly one of --dry-run and --out")
    try:
        pipeline = pf.load(args.pipeline)
        subject, motif = load_subject(args.subject), load_motif(args.motif)
        style, contract = load_style(args.style), load_contract(args.contract)
        if args.lint:
            found = lint(pipeline, subject, motif, style)
            if found:
                raise pf.PipelineError(found)
        job = resolve(pipeline, subject, motif, style, contract, args.seed)
    except pf.PipelineError as exc:
        print(exc, file=sys.stderr)
        return 1
    if args.dry_run:
        print(dry_run_text(job))
        return 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(job, indent=2, sort_keys=True) + "\n")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
