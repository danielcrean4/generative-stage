import { around, entityOptions, nodeName, problemCount, short, withStory } from './story-model';
import { StoryGraph, StoryNode } from './world-models';

const node = (id: string, pointer = '', extra: Partial<StoryNode> = {}): StoryNode => ({
  id, entity: id.split('#')[0], kind: 'errand', pointer, label: pointer ? 'step 10' : 'Errand', text: 'Fetch oil', conditions: [], effects: [], ...extra,
});

const graph: StoryGraph = {
  view: 'overview',
  nodes: [node('a'), node('b', '', { kind: 'lamp', text: 'North' }), node('c', '', { text: null })],
  edges: [{ id: 'e0', kind: 'effect', from: 'a', to: 'b', label: 'light', text: null, conditions: [], effects: [] }],
};

describe('story model', () => {
  it('names an entity by its title and an inner node by its label', () => {
    expect(nodeName(node('a'))).toBe('Fetch oil');
    expect(nodeName(node('c', '', { text: null }))).toBe('Errand');
    expect(nodeName(node('a#/steps/10', '/steps/10'))).toBe('step 10');
    expect(short('abcdef', 4)).toBe('abc…');
    expect(short(null, 4)).toBe('');
  });

  it('hides entities outside every story edge unless asked', () => {
    expect(withStory(graph, false).nodes.map((n) => n.id)).toEqual(['a', 'b']);
    expect(withStory(graph, true).nodes.length).toBe(3);
  });

  it('lists edges around a node and entities by kind', () => {
    expect(around(graph, 'b').in.map((e) => e.id)).toEqual(['e0']);
    expect(around(graph, 'b').out).toEqual([]);
    expect(entityOptions(graph, (k) => k.toUpperCase()).map((o) => o.text)).toEqual(['ERRAND: Errand', 'ERRAND: Fetch oil', 'LAMP: North']);
  });

  it('counts problems held by a node or edge', () => {
    const problem = { field: '/x', message: 'bad' };
    expect(problemCount({ conditions: [{ problems: [problem] }], effects: [{ problems: [problem] }], problem: 'missing' })).toBe(3);
    expect(problemCount({ conditions: [], effects: [], problem_count: 4 })).toBe(4);
  });
});
