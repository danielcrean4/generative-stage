"""The story graph route, GET /api/v1/projects/<slug>/story (docs/story_graph.md).

    GET .../story                 the overview: every entity, and the story edges between them
    GET .../story?entity=<id>     one entity's story nodes in full, with the entities it touches

Read-only: the graph is built from the project's entities, links and kind schemas on each request.
Archived entities are left out.
"""

from typing import Any

from core import story
from core.world import World


def graph(world: World, entity: str | None) -> dict[str, Any]:
    entities = world.list_entities()
    links = [link for e in entities for link in world.links(e["id"], "out")]
    whole = story.build(world.catalogue, entities, links)
    if entity:
        world.get_entity(entity)  # an unknown id is a 404
        return story.focus(whole, entity)
    return story.overview(whole)
