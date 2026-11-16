# Story graph

The story graph shows how a project's story fits together: which steps follow which, which lines
lead where, what each rule checks and what it changes. It is read-only. It is built from the
project's entities, their links and two kinds of mark in the kind schemas, each time it is asked
for, so it never goes stale.

## Marking a kind's fields

A kind schema marks an object with `x-story` to say it is part of a story. JSON Schema ignores the
keyword, so the schema validates as before.

```json
"step":  {"x-story": {"node": "step", "text": "note", "sequence": true}, "type": "object", ...}
"reply": {"x-story": {"edge": "reply", "text": "say", "to": "goto", "target": "/lines/{}"}, ...}
"hook":  {"x-story": {"ref": {"id_kind": "errand", "id": "key", "at": "/steps/{step}"}}, ...}
```

- **node**: each value here is a node. `node` names it; under `additionalProperties` or `items` the
  key or index is added (`step 10`). `text` names the field people read. `sequence: true` makes
  sibling nodes follow one another in key order (numbers in number order).
- **edge**: each value here leads to a node in the same entity. `to` names the field holding the
  next node's name, and `target` is the JSON pointer to that node with `{}` for the name. A missing
  or null `to` ends the story there.
- **ref**: each value here names another entity. `id_kind` is an id kind from the
  [vocabulary](vocabulary.md), which says which kinds it names and which field holds the id; `id`
  is the field holding the id. `at`, with `{field}` filled from the value's own fields, points at a
  node in that entity; without it, or when nothing is there, the edge goes to the entity itself.

A mark may sit inside another (a step holds replies). A mark in the wrong shape makes the kinds
fail to load with the schema file and pointer, as any other schema problem does.

## What the graph holds

Every entity is a node. Each marked node is a node too, with the id `<entity id>#<JSON pointer>`.
Edges have a `kind`:

| kind | from, to |
|---|---|
| `contains` | an entity or enclosing node, to a node nothing else in the entity leads to |
| `edge` | a marked edge, to the node it names; `to` is null where it ends (`ends`) or where the node is missing (`problem`) |
| `sequence` | a node, to the next sibling in a sequence |
| `ref` | a marked reference, to the entity or node it names, or null with a `problem` |
| `effect` | an effect whose kind has a `ref` in the vocabulary, to what it points at |
| `reads` | a condition, to an entity whose fact it reads (facts about the entity itself are left out) |
| `link` | a link between two entities |

Values marked `x-vocabulary` belong to the innermost edge or node holding them. A condition is
shown with its plain words, the facts it reads, any problems and whether it is older shorthand
(whose reads the tool cannot know). An effect is shown with its words and any problems.

## Route

`GET /api/v1/projects/{slug}/story` gives the overview: every entity as a node (with `inner`, the
number of story nodes in it, `condition_count` and `problem_count`) and the edges between entities,
one per kind and pair with a `count`.

`GET /api/v1/projects/{slug}/story?entity=<id>` gives one entity in full: its nodes and edges, with
each entity they touch as a single node. An unknown id answers 404 `entity_not_found`.

```json
{"view": "focus", "entity": "e-1",
 "nodes": [{"id": "e-1#/lines/oil", "entity": "e-1", "kind": "talk", "pointer": "/lines/oil",
            "label": "line oil", "text": "Two litres, please.", "conditions": [], "effects": []}],
 "edges": [{"id": "e4", "kind": "edge", "from": "e-1#/opening", "to": "e-1#/lines/oil",
            "label": "reply", "text": "Need oil?", "pointer": "/opening/replies/0",
            "ends": false, "problem": null,
            "conditions": [{"pointer": "/opening/replies/0/requires", "json": {...},
                            "text": "lamp(north).lit is true", "reads": [...], "problems": [],
                            "shorthand": false}],
            "effects": []}]}
```

## In the app

The **Story graph** page (at `/story`; the **Scripts** family in the left list holds the script records themselves) draws the overview, or one entity when picked, as layers from left to right. Picking
a node shows its words, its conditions in plain words with what they read, and its effects, with a
link to the entity's profile. Below 600 px wide, and whenever asked, the same graph is a list.
