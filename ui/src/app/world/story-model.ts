import { StoryEdge, StoryEdgeKind, StoryGraph, StoryNode } from './world-models';

/** The story page's words for each edge kind (docs/story_graph.md). */
export const EDGE_WORDS: Record<StoryEdgeKind, string> = {
  contains: 'holds',
  edge: 'leads to',
  sequence: 'then',
  ref: 'refers to',
  effect: 'changes',
  reads: 'reads',
  link: 'linked',
};

export function short(text: string | null | undefined, limit: number): string {
  if (!text) return '';
  return text.length <= limit ? text : `${text.slice(0, limit - 1)}…`;
}

/** What a node is called: an entity by its title, a node inside one by its label. */
export function nodeName(node: StoryNode): string {
  return node.pointer ? node.label : node.text || node.label;
}

/** The overview without entities that take part in no story edge, unless all are wanted. */
export function withStory(graph: StoryGraph, all: boolean): StoryGraph {
  if (all) return graph;
  const touched = new Set(graph.edges.flatMap((e) => (e.to ? [e.from, e.to] : [e.from])));
  return { ...graph, nodes: graph.nodes.filter((n) => touched.has(n.id) || (n.inner ?? 0) > 0) };
}

/** The edges leaving and reaching a node. */
export function around(graph: StoryGraph, id: string): { out: StoryEdge[]; in: StoryEdge[] } {
  return { out: graph.edges.filter((e) => e.from === id), in: graph.edges.filter((e) => e.to === id) };
}

/** Entities to pick from, by kind then name. */
export function entityOptions(graph: StoryGraph, kindLabel: (kind: string) => string): { id: string; text: string }[] {
  return graph.nodes
    .filter((n) => !n.pointer)
    .map((n) => ({ id: n.id, kind: kindLabel(n.kind), name: nodeName(n) }))
    .sort((a, b) => a.kind.localeCompare(b.kind) || a.name.localeCompare(b.name))
    .map((o) => ({ id: o.id, text: `${o.kind}: ${o.name}` }));
}

/** How many problems a node or edge carries, its own and its conditions' and effects'. */
export function problemCount(item: { conditions: { problems: unknown[] }[]; effects: { problems: unknown[] }[]; problem?: string | null; problem_count?: number }): number {
  if (item.problem_count !== undefined) return item.problem_count;
  const held = [...item.conditions, ...item.effects].reduce((sum, c) => sum + c.problems.length, 0);
  return held + (item.problem ? 1 : 0);
}
