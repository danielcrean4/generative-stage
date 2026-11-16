"""The story graph (docs/story_graph.md): a project's story nodes, the edges between them, and the
conditions and effects on each, read from the entities, their links and the kind schemas' marks.

Pure: `build` takes the catalogue, the entities and the links and returns plain data; nothing is
written. Every entity is a root node. Each value a schema marks as an `x-story` node is a node inside
it, with the id `<entity id>#<JSON pointer>`. Edges, by kind:

    contains  an entity, or an enclosing node, holds a node nothing else in the entity leads to
    edge      a marked edge (such as a reply) leads to a node in the same entity; `to` is null where
              the story ends there, or where the named node is missing (then `problem` says so)
    sequence  sibling nodes marked `sequence` follow one another in key order
    ref       a marked reference names another entity (and a node in it, when `at` finds one)
    effect    an effect whose vocabulary kind has a `ref` points at an entity
    reads     a condition reads a fact about another entity
    link      a link between two entities in the project

A condition or effect belongs to the innermost edge or node holding it, and is shown with its plain
text, the facts it reads and any problem the vocabulary finds.
"""

from collections.abc import Callable, Iterable, Mapping
from typing import Any

from core import conditions
from core.annotations import ANY, instances
from core.kinds import Catalogue, Kind
from core.story_marks import Mark
from core.vocabulary import Vocabulary


def node_id(entity_id: str, pointer: str) -> str:
    return f"{entity_id}#{pointer}" if pointer else entity_id


def _unescape(segment: str) -> str:
    return segment.replace("~1", "/").replace("~0", "~")


def _escape(value: object) -> str:
    return str(value).replace("~", "~0").replace("/", "~1")


def _parent(pointer: str) -> str:
    return pointer.rsplit("/", 1)[0]


def _order(pointer: str) -> tuple[int, int | str]:
    last = _unescape(pointer.rsplit("/", 1)[1])
    return (0, int(last)) if last.lstrip("-").isdigit() else (1, last)


def _fill(at: str | None, values: Mapping[str, Any]) -> str | None:
    """`/steps/{step}` with the value's own fields filled in; None when one is missing."""
    if not at:
        return None
    filled = at
    for name, value in values.items():
        filled = filled.replace("{" + name + "}", _escape(value))
    return None if "{" in filled else filled


class _Index:
    """Entity ids by (kind, id field value), to resolve an id kind and an id to an entity."""

    def __init__(self, vocabulary: Vocabulary | None, entities: Iterable[dict[str, Any]]) -> None:
        self.vocabulary = vocabulary
        self.by_kind: dict[str, dict[str, dict[str, str]]] = {}
        for entity in entities:
            self.by_kind.setdefault(entity["kind"], {})[entity["id"]] = {
                key: value for key, value in entity["data"].items() if isinstance(value, str)
            }

    def find(self, id_kind: str, value: object) -> str | None:
        if self.vocabulary is None or not isinstance(value, str):
            return None
        kinds, field = self.vocabulary.entity_kinds(id_kind)
        for kind in kinds:
            for entity_id, fields in self.by_kind.get(kind, {}).items():
                if fields.get(field) == value:
                    return entity_id
        return None


class _Builder:
    def __init__(self, catalogue: Catalogue, entities: list[dict[str, Any]]) -> None:
        self.catalogue = catalogue
        self.vocabulary = catalogue.vocabulary
        self.index = _Index(self.vocabulary, entities)
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: list[dict[str, Any]] = []
        self.pending: list[tuple[dict[str, Any], str, object, str | None]] = []

    # Nodes and in-entity edges

    def _node(self, entity: dict[str, Any], pointer: str, label: str, text: object) -> str:
        key = node_id(entity["id"], pointer)
        self.nodes[key] = {
            "id": key,
            "entity": entity["id"],
            "kind": entity["kind"],
            "pointer": pointer,
            "label": label,
            "text": text if isinstance(text, str) else None,
            "conditions": [],
            "effects": [],
        }
        return key

    def _edge(self, kind: str, source: str, target: str | None, **extra: Any) -> dict[str, Any]:
        edge = {"kind": kind, "from": source, "to": target, "label": "", "text": None, **extra}
        edge.setdefault("conditions", [])
        edge.setdefault("effects", [])
        self.edges.append(edge)
        return edge

    def entity(self, entity: dict[str, Any], kind: Kind) -> None:
        data = entity["data"]
        title = data.get(kind.title_field)
        self._node(entity, "", kind.label, title)
        own: dict[str, str] = {"": entity["id"]}
        sequences: list[list[str]] = []
        for mark in kind.story:
            if mark.role != "node":
                continue
            found = []
            for pointer, value in instances(data, mark.path):
                if not isinstance(value, dict):
                    continue
                label = mark.label
                if mark.path and mark.path[-1] == ANY:
                    label = f"{label} {_unescape(pointer.rsplit('/', 1)[1])}"
                text = value.get(mark.text) if mark.text else None
                own[pointer] = self._node(entity, pointer, label, text)
                found.append(pointer)
            if mark.sequence:
                sequences += self._siblings(found)

        def holder(pointer: str) -> str:
            """The innermost node holding a pointer (not the node at it)."""
            best = ""
            for at in own:
                if at and pointer.startswith(at + "/") and len(at) > len(best):
                    best = at
            return own[best]

        reached: set[str] = set()
        edges_at: dict[str, dict[str, Any]] = {}
        for mark in kind.story:
            if mark.role == "edge":
                for pointer, value in instances(data, mark.path):
                    if isinstance(value, dict):
                        edges_at[pointer] = self._story_edge(
                            entity, mark, pointer, value, own, holder
                        )
                        if edges_at[pointer]["to"]:
                            reached.add(edges_at[pointer]["to"])
            elif mark.role == "ref":
                for pointer, value in instances(data, mark.path):
                    if isinstance(value, dict):
                        edge = self._edge("ref", holder(pointer), None, pointer=pointer)
                        edge["label"] = f"{mark.ref['id_kind']} {value.get(mark.ref['id'])}"
                        self.pending.append(
                            (
                                edge,
                                mark.ref["id_kind"],
                                value.get(mark.ref["id"]),
                                _fill(mark.ref.get("at"), value),
                            )
                        )
        for group in sequences:
            for before, after in zip(group, group[1:], strict=False):
                self._edge("sequence", own[before], own[after], label="then")
                reached.add(own[after])
        for pointer, key in own.items():
            if pointer and key not in reached:
                self._edge("contains", holder(pointer), key)
        self._vocabulary_values(entity, kind, own, holder, edges_at)

    @staticmethod
    def _siblings(pointers: list[str]) -> list[list[str]]:
        groups: dict[str, list[str]] = {}
        for pointer in pointers:
            groups.setdefault(_parent(pointer), []).append(pointer)
        return [sorted(group, key=_order) for group in groups.values()]

    def _story_edge(
        self,
        entity: dict[str, Any],
        mark: Mark,
        pointer: str,
        value: dict[str, Any],
        own: dict[str, str],
        holder: Callable[[str], str],
    ) -> dict[str, Any]:
        goes = value.get(mark.to)
        target, problem = None, None
        if isinstance(goes, str) and goes:
            at = mark.target.replace("{}", _escape(goes))
            target = own.get(at)
            if target is None:
                problem = f"leads to {at}, which this {entity['kind']} does not have"
        text = value.get(mark.text) if mark.text else None
        return self._edge(
            "edge",
            holder(pointer),
            target,
            label=mark.label,
            text=text if isinstance(text, str) else None,
            pointer=pointer,
            ends=target is None and problem is None,
            problem=problem,
        )

    # Conditions and effects

    def _vocabulary_values(
        self,
        entity: dict[str, Any],
        kind: Kind,
        own: dict[str, str],
        holder: Callable[[str], str],
        edges_at: dict[str, dict[str, Any]],
    ) -> None:
        vocabulary = self.vocabulary
        if vocabulary is None:
            return
        for site in kind.sites:
            if site.role not in ("condition", "effects"):
                continue
            for pointer, value in instances(entity["data"], site.path):
                if value is None:
                    continue
                edge = next(
                    (
                        e
                        for at, e in sorted(edges_at.items(), key=lambda p: -len(p[0]))
                        if pointer.startswith(at + "/")
                    ),
                    None,
                )
                owner = edge if edge is not None else self.nodes[holder(pointer)]
                source = edge["from"] if edge is not None else owner["id"]
                if site.role == "condition":
                    owner["conditions"].append(self._condition(vocabulary, pointer, value))
                    self._reads(vocabulary, entity, source, value)
                else:
                    owner["effects"] += self._effects(vocabulary, pointer, value, source)

    def _condition(self, vocabulary: Vocabulary, pointer: str, value: object) -> dict[str, Any]:
        return {
            "pointer": pointer,
            "json": value,
            "text": conditions.text(vocabulary, value),
            "reads": [conditions.read_view(r) for r in conditions.reads(vocabulary, value)],
            "problems": [
                {"field": f, "message": m}
                for f, m in conditions.problems(vocabulary, value, pointer)
            ],
            "shorthand": conditions.is_shorthand(vocabulary, value),
        }

    def _reads(
        self, vocabulary: Vocabulary, entity: dict[str, Any], source: str, value: object
    ) -> None:
        for read in conditions.reads(vocabulary, value):
            for id_kind, read_id in read.ids:
                target = self.index.find(id_kind, read_id)
                if target is not None and target != entity["id"]:
                    self._edge("reads", source, target, label=read.path)

    def _effects(
        self, vocabulary: Vocabulary, pointer: str, value: object, source: str
    ) -> list[dict[str, Any]]:
        problems = [
            {"field": f, "message": m}
            for f, m in conditions.effect_problems(vocabulary, value, pointer)
        ]
        views = []
        for i, effect in enumerate(value if isinstance(value, list) else []):
            at = f"{pointer}/{i}"
            text = conditions.effect_text(vocabulary, effect)
            views.append(
                {
                    "pointer": at,
                    "json": effect,
                    "text": text,
                    "problems": [
                        p for p in problems if p["field"] == at or p["field"].startswith(at + "/")
                    ],
                }
            )
            spec = (
                vocabulary.effects.get(str(effect.get(vocabulary.effect_key or "")))
                if isinstance(effect, dict)
                else None
            )
            ref = (spec or {}).get("ref")
            if ref and isinstance(effect, dict):
                edge = self._edge("effect", source, None, label=text, pointer=at)
                self.pending.append(
                    (edge, ref["id_kind"], effect.get(ref["id"]), _fill(ref.get("at"), effect))
                )
        if not views and problems:
            views.append(
                {
                    "pointer": pointer,
                    "json": value,
                    "text": "(not a list of effects)",
                    "problems": problems,
                }
            )
        return views

    # Across entities

    def resolve(self) -> None:
        for edge, id_kind, target_id, at in self.pending:
            entity_id = self.index.find(id_kind, target_id)
            if entity_id is None:
                edge["problem"] = f"no {id_kind} {target_id!r} in this project"
                continue
            inner = node_id(entity_id, at) if at else None
            edge["to"] = inner if inner in self.nodes else entity_id

    def link(self, link: dict[str, Any]) -> None:
        if link["source"] in self.nodes and link["target"] in self.nodes:
            link_type = self.catalogue.link_types.get(link["type"])
            self._edge(
                "link",
                link["source"],
                link["target"],
                label=link_type.label if link_type else link["type"],
            )


def _numbered(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop repeats of a plain edge (same kind, ends and label) and give every edge an id."""
    seen: set[tuple[str, str, str | None, str]] = set()
    kept: list[dict[str, Any]] = []
    for edge in edges:
        if edge["kind"] in ("reads", "link", "contains", "sequence"):
            key = (edge["kind"], edge["from"], edge["to"], edge["label"])
            if key in seen:
                continue
            seen.add(key)
        kept.append({"id": f"e{len(kept)}", **edge})
    return kept


def build(
    catalogue: Catalogue, entities: list[dict[str, Any]], links: Iterable[dict[str, Any]]
) -> dict[str, Any]:
    """The whole graph: {"nodes": [...], "edges": [...]}. Entities of unknown kinds are left out."""
    builder = _Builder(catalogue, entities)
    for entity in entities:
        kind = catalogue.kinds.get(entity["kind"])
        if kind is not None:
            builder.entity(entity, kind)
    builder.resolve()
    for link in links:
        builder.link(link)
    return {"nodes": list(builder.nodes.values()), "edges": _numbered(builder.edges)}


def _root(nodes: Mapping[str, dict[str, Any]], key: str | None) -> str | None:
    return None if key is None else nodes[key]["entity"]


def overview(graph: dict[str, Any]) -> dict[str, Any]:
    """Entities only: each edge between two entities once per kind, with how many it stands for."""
    nodes = {n["id"]: n for n in graph["nodes"]}
    counted: dict[tuple[str, str, str], dict[str, Any]] = {}
    for edge in graph["edges"]:
        source, target = _root(nodes, edge["from"]), _root(nodes, edge["to"])
        if target is None or source == target or source is None:
            continue
        key = (edge["kind"], source, target)
        if key in counted:
            counted[key]["count"] += 1
        else:
            counted[key] = {
                "id": f"o{len(counted)}",
                "kind": edge["kind"],
                "from": source,
                "to": target,
                "label": edge["label"],
                "text": None,
                "count": 1,
                "conditions": [],
                "effects": [],
            }
    roots = [_summary(n, graph) for n in graph["nodes"] if not n["pointer"]]
    return {"view": "overview", "nodes": roots, "edges": list(counted.values())}


def _summary(node: dict[str, Any], graph: dict[str, Any]) -> dict[str, Any]:
    """A root node with how many inner nodes, conditions and problems its entity has."""
    inner = [n for n in graph["nodes"] if n["entity"] == node["id"]]
    edges = [e for e in graph["edges"] if e["from"] in {n["id"] for n in inner}]
    held = [*inner, *edges]
    return {
        **node,
        "inner": len(inner) - 1,
        "condition_count": sum(len(h["conditions"]) for h in held),
        "problem_count": sum(
            len(c["problems"]) for h in held for c in [*h["conditions"], *h["effects"]]
        )
        + sum(1 for e in edges if e.get("problem")),
    }


def focus(graph: dict[str, Any], entity_id: str) -> dict[str, Any]:
    """One entity's nodes and edges in full, with the entities they touch as single nodes."""
    nodes = {n["id"]: n for n in graph["nodes"]}
    if entity_id not in nodes:
        return {"view": "focus", "entity": entity_id, "nodes": [], "edges": []}
    own = [n for n in graph["nodes"] if n["entity"] == entity_id]
    edges, others = [], {}
    for edge in graph["edges"]:
        source, target = nodes.get(edge["from"]), nodes.get(edge["to"]) if edge["to"] else None
        mine_from = source is not None and source["entity"] == entity_id
        mine_to = target is not None and target["entity"] == entity_id
        if not (mine_from or mine_to):
            continue
        shown = dict(edge)
        for end, node, mine in (("from", source, mine_from), ("to", target, mine_to)):
            if node is not None and not mine:
                shown[end] = node["entity"]
                others[node["entity"]] = nodes[node["entity"]]
        edges.append(shown)
    return {"view": "focus", "entity": entity_id, "nodes": [*own, *others.values()], "edges": edges}
