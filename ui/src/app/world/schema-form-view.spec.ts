import { ComponentFixture, TestBed } from '@angular/core/testing';
import { FieldChange, SchemaFormView } from './schema-form-view';
import { buildFields } from './schema-form';

const SCHEMA = {
  type: 'object',
  required: ['name'],
  properties: {
    name: { type: 'string' },
    brief: { type: 'string' },
    count: { type: 'integer' },
    lit: { type: 'boolean', title: 'Lit at night' },
    size: { type: 'string', enum: ['small', 'large'] },
    tags: { type: 'array', items: { type: 'string' } },
    address: { type: 'object', title: 'Where', properties: { street: { type: 'string' } } },
    grid: { type: 'array', items: { type: 'array', items: { type: 'number' } } },
  },
};

describe('SchemaFormView', () => {
  let fixture: ComponentFixture<SchemaFormView>;
  let el: HTMLElement;
  let changes: FieldChange[];

  function setup(values: Record<string, unknown>, errors: Record<string, string> = {}, readonly = false): void {
    TestBed.configureTestingModule({ imports: [SchemaFormView] });
    fixture = TestBed.createComponent(SchemaFormView);
    changes = [];
    fixture.componentInstance.valueChange.subscribe((c) => changes.push(c));
    fixture.componentRef.setInput('fields', buildFields(SCHEMA, { briefField: 'brief' }));
    fixture.componentRef.setInput('values', values);
    fixture.componentRef.setInput('errors', errors);
    fixture.componentRef.setInput('readonly', readonly);
    fixture.detectChanges();
    el = fixture.nativeElement;
  }
  const at = (pointer: string) => el.querySelector(`[data-field="${pointer}"]`) as HTMLElement;

  it('draws every supported field type from the schema', () => {
    setup({ name: 'Lamp', tags: ['a', 'b'], size: 'large', lit: true, address: { street: 'Main Street' }, grid: [[1]] });
    expect(at('/data/name').querySelector('input[type="text"]')).not.toBeNull();
    expect(at('/data/brief').querySelector('textarea')).not.toBeNull();
    expect(at('/data/count').querySelector('input[type="number"]')).not.toBeNull();
    expect(at('/data/lit').textContent).toContain('Lit at night');
    expect(at('/data/size').querySelectorAll('option')).toHaveLength(3);
    expect((at('/data/size').querySelector('select') as HTMLSelectElement).value).toBe('large');
    expect(Array.from(at('/data/tags').querySelectorAll('mat-chip-row')).map((c) => c.textContent?.replace('×', '').trim())).toEqual(['a', 'b']);
    expect(at('/data/address').querySelector('legend')?.textContent).toBe('Where');
    expect((at('/data/address/street').querySelector('input') as HTMLInputElement).value).toBe('Main Street');
    expect(at('/data/grid').querySelector('pre')?.textContent).toContain('[');
  });

  it('always offers a blank choice, so a required list that is not set does not look set', () => {
    TestBed.configureTestingModule({ imports: [SchemaFormView] });
    const f = TestBed.createComponent(SchemaFormView);
    f.componentRef.setInput('fields', buildFields({ type: 'object', required: ['size'], properties: { size: { type: 'string', enum: ['small', 'large'] } } }));
    f.componentRef.setInput('values', {});
    f.detectChanges();
    const select = f.nativeElement.querySelector('select') as HTMLSelectElement;
    expect(select.options).toHaveLength(3);
    expect(select.value).toBe('');
  });

  it('marks a required field and not an optional one', () => {
    setup({});
    expect(at('/data/name').querySelector('input')?.hasAttribute('required')).toBe(true);
    expect(at('/data/brief').querySelector('textarea')?.hasAttribute('required')).toBe(false);
  });

  it('shows an error under the field it belongs to and nowhere else', () => {
    setup({}, { '/data/name': "'name' is a required property" });
    expect(at('/data/name').querySelector('.field-error')?.textContent).toContain('required property');
    expect(el.querySelectorAll('.field-error')).toHaveLength(1);
  });

  it('emits an edit with the path and the typed value, parsing numbers and choices', () => {
    setup({ name: '' });
    const name = at('/data/name').querySelector('input') as HTMLInputElement;
    name.value = 'Lamp';
    name.dispatchEvent(new Event('input'));
    const count = at('/data/count').querySelector('input') as HTMLInputElement;
    count.value = '7';
    count.dispatchEvent(new Event('input'));
    const size = at('/data/size').querySelector('select') as HTMLSelectElement;
    size.value = 'small';
    size.dispatchEvent(new Event('change'));
    const street = at('/data/address/street').querySelector('input') as HTMLInputElement;
    street.value = 'Main Street';
    street.dispatchEvent(new Event('input'));
    expect(changes).toEqual([
      { path: ['name'], value: 'Lamp' },
      { path: ['count'], value: 7 },
      { path: ['size'], value: 'small' },
      { path: ['address', 'street'], value: 'Main Street' },
    ]);
  });

  it('adds and removes tags', () => {
    setup({ tags: ['a'] });
    const view = fixture.componentInstance;
    const field = view.fields().find((f) => f.key === 'tags')!;
    view.addTag(field, { value: ' b ', chipInput: { clear: () => undefined } } as never);
    view.addTag(field, { value: 'a', chipInput: { clear: () => undefined } } as never);
    view.removeTag(field, 'a');
    expect(changes).toEqual([
      { path: ['tags'], value: ['a', 'b'] },
      { path: ['tags'], value: [] },
    ]);
  });

  it('is read-only when asked: no tag box, no remove buttons, fields not editable', () => {
    setup({ name: 'Lamp', tags: ['a'] }, {}, true);
    expect(at('/data/tags').querySelector('input')).toBeNull();
    expect(at('/data/tags').querySelector('button[matChipRemove]')).toBeNull();
    expect(at('/data/name').querySelector('input')?.hasAttribute('readonly')).toBe(true);
    expect(at('/data/size').querySelector('select')?.disabled).toBe(true);
  });
});
