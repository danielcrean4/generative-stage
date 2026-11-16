/**
 * Lays a story graph out in layers from left to right, for the story page's SVG (docs/story_graph.md).
 * Pure: nodes and edges in, positions and edge paths out.
 *
 * - Edges that would close a loop (a reply back to an earlier line) are set aside while layering,
 *   then drawn as curves like the rest.
 * - Each node sits one layer after the furthest node leading to it (longest path).
 * - Within a layer, nodes are ordered by the mean place of their neighbours, sweeping forward and
 *   back a few times, which keeps most edges short and uncrossed.
 */

export interface LayoutInput {
  nodes: { id: string }[];
  edges: { id: string; from: string; to: string | null }[];
}

export interface PlacedNode {
  id: string;
  x: number;
  y: number;
  layer: number;
}

export interface PlacedEdge {
  id: string;
  path: string;
  back: boolean; // drawn against the flow (it closes a loop)
}

export interface Layout {
  width: number;
  height: number;
  nodes: PlacedNode[];
  edges: PlacedEdge[];
}

export const NODE_WIDTH = 200;
export const NODE_HEIGHT = 56;
const GAP_X = 72;
const GAP_Y = 20;
const MARGIN = 16;
const SWEEPS = 4;

/** Edges that close a loop, found by a depth-first walk in node order. */
function backEdges(ids: string[], out: Map<string, { id: string; to: string }[]>): Set<string> {
  const state = new Map<string, 'open' | 'done'>();
  const back = new Set<string>();
  const visit = (start: string): void => {
    const stack: { node: string; next: number }[] = [{ node: start, next: 0 }];
    state.set(start, 'open');
    while (stack.length) {
      const top = stack[stack.length - 1];
      const edges = out.get(top.node) ?? [];
      if (top.next >= edges.length) {
        state.set(top.node, 'done');
        stack.pop();
        continue;
      }
      const edge = edges[top.next++];
      const seen = state.get(edge.to);
      if (seen === 'open') back.add(edge.id);
      else if (!seen) {
        state.set(edge.to, 'open');
        stack.push({ node: edge.to, next: 0 });
      }
    }
  };
  for (const id of ids) if (!state.has(id)) visit(id);
  return back;
}

function layers(ids: string[], forward: { from: string; to: string }[]): Map<string, number> {
  const incoming = new Map(ids.map((id) => [id, 0]));
  const out = new Map<string, string[]>();
  for (const e of forward) {
    incoming.set(e.to, (incoming.get(e.to) ?? 0) + 1);
    out.set(e.from, [...(out.get(e.from) ?? []), e.to]);
  }
  const layer = new Map(ids.map((id) => [id, 0]));
  const ready = ids.filter((id) => incoming.get(id) === 0);
  while (ready.length) {
    const id = ready.shift()!;
    for (const to of out.get(id) ?? []) {
      layer.set(to, Math.max(layer.get(to)!, layer.get(id)! + 1));
      incoming.set(to, incoming.get(to)! - 1);
      if (incoming.get(to) === 0) ready.push(to);
    }
  }
  return layer;
}

function order(columns: string[][], forward: { from: string; to: string }[]): void {
  const place = new Map<string, number>();
  const remember = () => columns.forEach((column) => column.forEach((id, i) => place.set(id, i)));
  remember();
  const before = new Map<string, string[]>();
  const after = new Map<string, string[]>();
  for (const e of forward) {
    after.set(e.from, [...(after.get(e.from) ?? []), e.to]);
    before.set(e.to, [...(before.get(e.to) ?? []), e.from]);
  }
  const mean = (id: string, near: Map<string, string[]>): number => {
    const others = near.get(id) ?? [];
    return others.length ? others.reduce((sum, o) => sum + place.get(o)!, 0) / others.length : place.get(id)!;
  };
  for (let sweep = 0; sweep < SWEEPS; sweep++) {
    const near = sweep % 2 === 0 ? before : after;
    const range = sweep % 2 === 0 ? columns.keys() : [...columns.keys()].reverse();
    for (const c of range) {
      const scored = columns[c].map((id) => ({ id, score: mean(id, near) }));
      scored.sort((a, b) => a.score - b.score);
      columns[c] = scored.map((s) => s.id);
      remember();
    }
  }
}

function curve(a: PlacedNode, b: PlacedNode): string {
  const x1 = a.x + NODE_WIDTH;
  const y1 = a.y + NODE_HEIGHT / 2;
  const x2 = b.x;
  const y2 = b.y + NODE_HEIGHT / 2;
  const bend = Math.max(40, Math.abs(x2 - x1) / 2);
  return `M${x1},${y1} C${x1 + bend},${y1} ${x2 - bend},${y2} ${x2},${y2}`;
}

export function layout(graph: LayoutInput): Layout {
  const ids = graph.nodes.map((n) => n.id);
  const known = new Set(ids);
  const drawn = graph.edges.filter((e): e is { id: string; from: string; to: string } => e.to !== null && known.has(e.from) && known.has(e.to) && e.from !== e.to);
  const out = new Map<string, { id: string; to: string }[]>();
  for (const e of drawn) out.set(e.from, [...(out.get(e.from) ?? []), { id: e.id, to: e.to }]);
  const back = backEdges(ids, out);
  const forward = drawn.filter((e) => !back.has(e.id));
  const layerOf = layers(ids, forward);
  const columns: string[][] = [];
  for (const id of ids) (columns[layerOf.get(id)!] ??= []).push(id);
  order(columns, forward);
  const placed = new Map<string, PlacedNode>();
  columns.forEach((column, layer) =>
    column.forEach((id, i) =>
      placed.set(id, { id, layer, x: MARGIN + layer * (NODE_WIDTH + GAP_X), y: MARGIN + i * (NODE_HEIGHT + GAP_Y) }),
    ),
  );
  const tallest = Math.max(0, ...columns.map((c) => c.length));
  return {
    width: MARGIN * 2 + Math.max(0, columns.length * (NODE_WIDTH + GAP_X) - GAP_X),
    height: MARGIN * 2 + Math.max(0, tallest * (NODE_HEIGHT + GAP_Y) - GAP_Y),
    nodes: ids.map((id) => placed.get(id)!),
    edges: drawn.map((e) => ({ id: e.id, back: back.has(e.id), path: curve(placed.get(e.from)!, placed.get(e.to)!) })),
  };
}
