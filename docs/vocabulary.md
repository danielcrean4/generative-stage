# Condition vocabulary

A story is full of rules: a quest step that opens when the player holds a key, a line of dialogue
offered only at night, an effect that lights a lamp. The rules are written as **conditions** and
**effects**, and the words they may use are the project's **vocabulary**: the facts a condition
can read, the operators that compare them, the effects a rule can run and how often it may fire.

The tool never invents a vocabulary. A game makes the file from its own code and supplies it as
data, so the tool can check, show and explain conditions without knowing the game.

## Where it lives

`vocabulary.json` in the project's schema folder, beside `kinds.json`. It is optional. When it is
there it is checked whenever the kinds load, and a wrong file makes every request about the project
answer 422 `bad_schema` with the file and the JSON pointer, as a wrong kind schema does. It is read
again on every request, so replacing the file applies at once.

`core/vocabulary.schema.json` is the format as a JSON Schema (draft 2020-12).

## The format

```json
{
  "format": "generative-stage-vocabulary",
  "format_version": 1,
  "source": "made by the game's exporter",
  "types": {"int": {"json": "integer"}, "bool": {"json": "boolean"},
            "id": {"json": "string"}, "id_set": {"json": "array", "doc": "a set of ids"}},
  "facts": [{"pattern": "errand(errand).step", "type": "int", "doc": "The step an errand has reached."},
            {"pattern": "keeper.seen", "type": "id_set"}],
  "operators": {"gte": {"types": ["int"], "operand": "same", "text": "is at least"},
                "has": {"types": ["id_set"], "operand": "member", "text": "has"},
                "in": {"types": ["id", "int"], "operand": "list", "text": "is one of"}},
  "id_kinds": {"errand": {"entity_kinds": ["errand"]}, "mark": {"doc": "Any mark name."}},
  "effects": {"key": "do", "kinds": {
    "advance": {"doc": "Move an errand to a step.",
                "args": {"errand": {"type": "string", "id_kind": "errand"}, "step": {"type": "integer", "minimum": 1}},
                "required": ["errand", "step"],
                "ref": {"id_kind": "errand", "id": "errand", "at": "/steps/{step}"}}}},
  "rule_modes": {"once": {"doc": "The first time it holds."}, "each": {"doc": "Every time it turns true."}},
  "shorthand": {"keys": ["after_step"], "doc": "The older form."}
}
```

| Key | Required | What it is |
|---|---|---|
| `format`, `format_version` | yes | `"generative-stage-vocabulary"` and `1`; `"dramatis-vocabulary"`, the id used before the rename, is read too |
| `source` | no | what made the file, for people |
| `types` | yes | each fact type with the JSON type of its values; `array` is a list of strings |
| `facts` | yes | every fact a condition may read. A pattern is dot-separated names; a name may take an id kind in parentheses, which a condition fills with an id: `errand(errand).step` is read as `errand(fetch_oil).step`. An id is lowercase letters, digits, `_`, spaces, `.`, `:` and `-` |
| `operators` | yes | the fact types each accepts, what its value must be (`same`: a value of the fact's type; `member`: one id; `list`: a non-empty list of values of the fact's type) and the words that show it |
| `id_kinds` | no | the id kinds the patterns and effect arguments use. `entity_kinds` names the project kinds whose entities those ids are, matched on the data field `field` (default `key`), so the tool can link a condition to what it reads. When the key is present, every id kind used must be listed |
| `effects` | no | `key` is the field that names an effect's kind (`{"do": "advance", ...}`); each kind lists its `args`, each a small schema (`type` of integer, number, boolean or string; optional `minimum`, `maximum`, `minLength`, `maxLength`, `pattern`, `enum`, `description`, `id_kind`), which args are `required`, and optionally `ref`: the entity (and the JSON pointer inside it, where `{arg}` is an argument's value) the effect points at |
| `rule_modes` | no | how often a rule may fire, by name |
| `shorthand` | no | older condition keys a game still reads. An object made only of these keys is accepted as written and shown key by key; the tool cannot say what it reads |

## Conditions

A condition is one of:

| Shape | Holds when |
|---|---|
| `{"all": [C, ...]}` | every one holds |
| `{"any": [C, ...]}` | at least one holds |
| `{"not": C}` | C does not hold |
| `{"fact": "<path>", "<operator>": <value>}` | the fact compares as the operator says |

The tool checks a condition's shape against the vocabulary: that each path matches a pattern, that
the operator applies to the fact's type and that the value has the right JSON type. It does not
evaluate conditions and does not check that an id exists; the game does that.

Shown to people, `{"all": [{"fact": "keeper.oil", "gte": 2}, {"any": [...]}]}` reads
`keeper.oil is at least 2 and (... or ...)`.

## Marking a kind's fields

A kind schema marks a value with the keyword `x-vocabulary` (JSON Schema ignores keywords it does not
know, so the schema validates as before):

```json
"when":    {"x-vocabulary": "condition", "anyOf": [{"type": "object"}, {"type": "null"}]},
"effects": {"x-vocabulary": "effects", "type": "array", "items": {"type": "object"}},
"mode":    {"x-vocabulary": "rule_mode", "type": "string"}
```

The roles are `condition`, `effects`, `rule_mode` and `fact` (a single fact path). The mark may sit
anywhere the schema reaches through `properties`, `items`, `additionalProperties`, local `$ref` and
`anyOf`/`oneOf`/`allOf`. Every create, update and revert then checks each marked value against the
vocabulary and answers 422 `invalid_entity` naming the value (`/data/steps/10/when/gte`) at the first
problem. An absent or `null` value is not checked. A kind that marks values needs `vocabulary.json`
in the same folder; without it the kinds do not load. `core/annotations.py` finds the marks.

The [story graph](story_graph.md) shows each marked condition and effect where it sits in the story,
with the same words and problems.

## Routes

| Route | What it does |
|---|---|
| `GET /api/v1/projects/{slug}/vocabulary` | `{"vocabulary": {...}}`, the file as written, or `{"vocabulary": null}` |
| `PUT /api/v1/projects/{slug}/vocabulary` | the body is the file; it is checked, then written, and the answer is the same shape as `GET`. A problem is 422 `invalid` with the JSON pointer in the body. This route works even when the current file is broken |
| `POST /api/v1/projects/{slug}/vocabulary/check` | the body is exactly one of `{"condition": C}`, `{"effects": [E]}`, `{"fact": "<path>"}` or `{"rule_mode": "<name>"}` |

The check answers 200 even for a bad condition, so an editor can call it while a person types:

```json
{"problems": [{"field": "/all/0/gte", "message": "keeper.oil is an int, so the value must be a JSON integer"}],
 "text": "keeper.oil is at least two and errand(fetch_oil).done is true",
 "reads": [{"path": "keeper.oil", "pattern": "keeper.oil", "type": "int", "doc": "...", "ids": []}],
 "shorthand": false}
```

`effects` answers `problems` and `text`; `fact` answers `problems` and `reads`; `rule_mode` answers
`problems`. A project with no vocabulary answers 404 `no_vocabulary`. The MCP server has
`get_vocabulary` and `check_condition` ([MCP server](mcp.md)).

## Keeping it in step with a game

The game owns its vocabulary, so a game's adapter writes this file from the game's own code and
keeps a check that fails when the game and the copy differ. The tool only reads the copy.
