import { formBadge, groupByFamily } from './kind-families';
import { Kind } from './world-models';

const kind = (id: string, extra: Partial<Kind> = {}): Kind => ({
  id, label: id, plural_label: id + 's', icon: '', title_field: 'name', brief_field: null, tags_field: null, schema_file: '', schema: {}, ...extra,
});

describe('kind families', () => {
  it('groups kinds in family order with Other last, keeping each kind in its place', () => {
    const kinds = [
      kind('place', { family: 'setting' }),
      kind('hint'),
      kind('scene', { family: 'script', form: 'branching' }),
      kind('cup', { family: 'prop' }),
      kind('room', { family: 'setting' }),
      kind('chair', { family: 'prop' }),
      kind('rule', { family: null }),
    ];
    expect(groupByFamily(kinds).map((g) => [g.label, g.kinds.map((k) => k.id)])).toEqual([
      ['Props', ['cup', 'chair']],
      ['Settings', ['place', 'room']],
      ['Scripts', ['scene']],
      ['Other', ['hint', 'rule']],
    ]);
  });

  it('leaves out empty groups', () => {
    expect(groupByFamily([])).toEqual([]);
    expect(groupByFamily([kind('a')]).map((g) => g.id)).toEqual(['other']);
  });

  it('badges a script kind with its form and nothing else', () => {
    expect(formBadge(kind('scene', { family: 'script', form: 'linear' }))?.badge).toBe('linear');
    expect(formBadge(kind('talk', { family: 'script', form: 'branching' }))?.badge).toBe('branching');
    expect(formBadge(kind('scene', { family: 'script' }))).toBeNull();
    expect(formBadge(kind('cup', { family: 'prop' }))).toBeNull();
  });
});
