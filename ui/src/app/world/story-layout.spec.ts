import { layout, NODE_HEIGHT, NODE_WIDTH } from './story-layout';

const node = (id: string) => ({ id });
const edge = (id: string, from: string, to: string | null) => ({ id, from, to });

describe('story layout', () => {
  it('puts each node one layer after the furthest node leading to it', () => {
    const placed = layout({
      nodes: ['a', 'b', 'c', 'd'].map(node),
      edges: [edge('1', 'a', 'b'), edge('2', 'b', 'c'), edge('3', 'a', 'c'), edge('4', 'c', null)],
    });
    const layer = Object.fromEntries(placed.nodes.map((n) => [n.id, n.layer]));
    expect(layer).toEqual({ a: 0, b: 1, c: 2, d: 0 });
    expect(placed.edges.map((e) => e.id)).toEqual(['1', '2', '3']);
    expect(placed.width).toBeGreaterThan(3 * NODE_WIDTH);
    expect(placed.height).toBeGreaterThanOrEqual(2 * NODE_HEIGHT);
  });

  it('sets a loop-closing edge aside while layering and marks it', () => {
    const placed = layout({
      nodes: ['a', 'b', 'c'].map(node),
      edges: [edge('1', 'a', 'b'), edge('2', 'b', 'c'), edge('3', 'c', 'a')],
    });
    expect(placed.nodes.map((n) => n.layer)).toEqual([0, 1, 2]);
    expect(placed.edges.find((e) => e.id === '3')?.back).toBe(true);
    expect(placed.edges.find((e) => e.id === '1')?.back).toBe(false);
  });

  it('orders a layer by where its neighbours sit, so edges do not cross', () => {
    const placed = layout({
      nodes: ['a', 'b', 'y', 'x'].map(node),
      edges: [edge('1', 'a', 'x'), edge('2', 'b', 'y')],
    });
    const y = Object.fromEntries(placed.nodes.map((n) => [n.id, n.y]));
    expect(y['x']).toBeLessThan(y['y']);
  });

  it('draws nothing for an empty graph and skips edges to unknown nodes', () => {
    expect(layout({ nodes: [], edges: [] })).toEqual({ width: 32, height: 32, nodes: [], edges: [] });
    expect(layout({ nodes: [node('a')], edges: [edge('1', 'a', 'z')] }).edges).toEqual([]);
  });
});
