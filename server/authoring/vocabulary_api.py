"""The vocabulary routes under /api/v1/projects/<slug>/vocabulary (docs/vocabulary.md).

    GET  .../vocabulary          the project's vocabulary file, or null when it has none
    PUT  .../vocabulary          replace it (the body is the file); checked before it is written
    POST .../vocabulary/check    {"condition": C} | {"effects": [E]} | {"fact": path} | {"rule_mode": m}
                                 -> every problem, the text people read and the facts it reads

The check route never raises for a bad condition: an editor calls it as a person types, so problems
come back as data (200) with the JSON pointer inside the value sent. Only a request that is not one
of those shapes is refused.
"""

from pathlib import Path
from typing import Any

from authoring.replies import BadRequest
from core import conditions
from core.errors import Invalid, NotFound
from core.vocabulary import Vocabulary, load_vocabulary, write_vocabulary

type Reply = tuple[int, Any]
CHECKS = ("condition", "effects", "fact", "rule_mode")


def route(schema_dir: Path, method: str, rest: list[str], body: dict[str, Any]) -> Reply:
    """`rest` is the path after .../vocabulary."""
    if not rest:
        if method == "GET":
            vocabulary = load_vocabulary(schema_dir)
            return 200, {"vocabulary": vocabulary.describe() if vocabulary else None}
        if method == "PUT":
            return 200, {"vocabulary": write_vocabulary(schema_dir, body).describe()}
        raise BadRequest(405, "method_not_allowed", f"{method} is not allowed here")
    if rest == ["check"]:
        if method != "POST":
            raise BadRequest(405, "method_not_allowed", f"{method} is not allowed here")
        vocabulary = load_vocabulary(schema_dir)
        if vocabulary is None:
            raise NotFound("the project has no vocabulary", "no_vocabulary")
        return 200, check(vocabulary, body)
    raise BadRequest(404, "route_not_found", "no such route")


def check(vocabulary: Vocabulary, body: dict[str, Any]) -> dict[str, Any]:
    if len(body) != 1 or next(iter(body)) not in CHECKS:
        raise Invalid(f"give exactly one of {', '.join(CHECKS)}", field="/")
    ((what, value),) = body.items()
    if what == "condition":
        reads = conditions.reads(vocabulary, value)
        return {
            "problems": _problems(conditions.problems(vocabulary, value)),
            "text": conditions.text(vocabulary, value),
            "reads": [conditions.read_view(r) for r in reads],
            "shorthand": conditions.is_shorthand(vocabulary, value),
        }
    if what == "effects":
        texts = (
            [conditions.effect_text(vocabulary, e) for e in value]
            if isinstance(value, list)
            else []
        )
        return {
            "problems": _problems(conditions.effect_problems(vocabulary, value)),
            "text": "; ".join(texts),
        }
    if what == "fact":
        read = vocabulary.read(value)
        return {
            "problems": _problems(conditions.fact_problems(vocabulary, value)),
            "reads": [conditions.read_view(read)] if read else [],
        }
    return {"problems": _problems(conditions.rule_mode_problems(vocabulary, value))}


def _problems(found: list[tuple[str, str]]) -> list[dict[str, str]]:
    return [{"field": field or "/", "message": message} for field, message in found]
