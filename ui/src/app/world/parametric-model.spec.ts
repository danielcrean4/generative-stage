import { ParamModel, activeFields, setValue, settle, show } from './parametric-model';

const model: ParamModel = {
  selector: 'shade',
  fields: [
    { name: 'shade', label: 'Shade', about: '', type: 'enum', values: ['drum', 'cone'], default: 'drum', builders: null, when: null },
    { name: 'height', label: 'Height', about: '', type: 'number', min: 30, max: 200, step: 5, unit: 'cm', default: 115, builders: null, when: null },
    { name: 'has_arm', label: 'Arm', about: '', type: 'boolean', default: false, builders: null, when: null },
    { name: 'reach', label: 'Reach', about: '', type: 'number', min: 5, max: 60, step: 5, unit: 'cm', default: 30, builders: null, when: 'has_arm' },
    { name: 'drum', label: 'Drum', about: '', type: 'number', min: 8, max: 40, step: 1, unit: 'cm', default: 24, builders: ['drum'], when: null },
    { name: 'cone', label: 'Cone', about: '', type: 'number', min: 4, max: 20, step: 1, unit: 'cm', default: 12, builders: ['cone'], when: null },
  ],
};

const names = (row: Record<string, unknown>) => activeFields(model, row).map((f) => f.name);

describe('parametric model', () => {
  it('shows only the fields of the chosen variant', () => {
    expect(names({ shade: 'drum' })).toEqual(['shade', 'height', 'has_arm', 'drum']);
    expect(names({ shade: 'cone' })).toEqual(['shade', 'height', 'has_arm', 'cone']);
  });

  it('shows a conditional field only while its switch is on', () => {
    expect(names({ shade: 'drum', has_arm: true })).toContain('reach');
    expect(names({ shade: 'drum', has_arm: false })).not.toContain('reach');
  });

  it('settles a row: defaults for what appears, nothing for what goes', () => {
    const row = settle(model, { name: 'Lamp', shade: 'drum', height: 80 });
    expect(row).toEqual({ name: 'Lamp', shade: 'drum', height: 80, has_arm: false, drum: 24 });
    const cone = setValue(model, row, 'shade', 'cone');
    expect(cone['drum']).toBeUndefined();
    expect(cone['cone']).toBe(12);
    const arm = setValue(model, cone, 'has_arm', true);
    expect(arm['reach']).toBe(30);
    expect(setValue(model, arm, 'has_arm', false)['reach']).toBeUndefined();
    expect(cone['name']).toBe('Lamp');
  });

  it('writes a value with its unit', () => {
    expect(show(model.fields[1], 80)).toBe('80 cm');
    expect(show(model.fields[2], true)).toBe('on');
  });
});
