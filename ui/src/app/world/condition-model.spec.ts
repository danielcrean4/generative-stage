import { addLeaf, formatJson, leaf, operand, operatorsFor, parseJson, suggestFacts } from './condition-model';
import { Vocabulary } from './world-models';

const vocabulary: Vocabulary = {
  format: 'generative-stage-vocabulary',
  format_version: 1,
  types: { int: { json: 'integer' }, id: { json: 'string' }, id_set: { json: 'array' } },
  facts: [
    { pattern: 'errand(errand).step', type: 'int', doc: 'The step an errand has reached.' },
    { pattern: 'keeper.oil', type: 'int', doc: 'Litres of oil.' },
    { pattern: 'keeper.seen', type: 'id_set' },
  ],
  operators: {
    gte: { types: ['int'], operand: 'same', text: 'is at least' },
    has: { types: ['id_set'], operand: 'member', text: 'has' },
    in: { types: ['id', 'int'], operand: 'list', text: 'is one of' },
  },
};

describe('condition model', () => {
  it('reads JSON text, empty as no condition', () => {
    expect(parseJson('')).toEqual({ ok: true, value: null });
    expect(parseJson('{"fact": "keeper.oil", "gte": 2}')).toEqual({ ok: true, value: { fact: 'keeper.oil', gte: 2 } });
    const bad = parseJson('{"fact": ');
    expect(bad.ok).toBe(false);
    expect(formatJson(null)).toBe('');
    expect(formatJson({ a: 1 })).toBe('{\n  "a": 1\n}');
  });

  it('suggests patterns by text or description, ids ignored', () => {
    expect(suggestFacts(vocabulary, 'keeper').map((f) => f.pattern)).toEqual(['keeper.oil', 'keeper.seen']);
    expect(suggestFacts(vocabulary, 'errand(fetch_oil).st').map((f) => f.pattern)).toEqual(['errand(errand).step']);
    expect(suggestFacts(vocabulary, 'litres').map((f) => f.pattern)).toEqual(['keeper.oil']);
    expect(suggestFacts(vocabulary, '').length).toBe(3);
  });

  it('offers the operators a type takes', () => {
    expect(operatorsFor(vocabulary, 'int')).toEqual(['gte', 'in']);
    expect(operatorsFor(vocabulary, 'id_set')).toEqual(['has']);
    expect(operatorsFor(vocabulary, null)).toEqual(['gte', 'has', 'in']);
  });

  it('reads a typed value as the fact type needs', () => {
    expect(operand('3', 'integer', false)).toBe(3);
    expect(operand('three', 'integer', false)).toBe('three');
    expect(operand('true', 'boolean', false)).toBe(true);
    expect(operand('1, 2', 'integer', true)).toEqual([1, 2]);
    expect(operand('a, b', 'array', false)).toEqual(['a', 'b']);
    expect(operand(' hall ', 'string', false)).toBe('hall');
  });

  it('adds a leaf to what is there', () => {
    const a = leaf('keeper.oil', 'gte', 2);
    const b = leaf('keeper.seen', 'has', 'cellar');
    expect(addLeaf(null, a)).toEqual(a);
    expect(addLeaf(a, b)).toEqual({ all: [a, b] });
    expect(addLeaf({ all: [a] }, b)).toEqual({ all: [a, b] });
    expect(addLeaf({ any: [a] }, b)).toEqual({ all: [{ any: [a] }, b] });
  });
});
