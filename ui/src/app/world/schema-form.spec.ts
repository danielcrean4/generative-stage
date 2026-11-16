import { FormField, buildFields, isDirty, mapError, parseNumber, pointerOf, setValue, toData } from './schema-form';

/** A schema with one of everything the form supports, plus things it does not. */
const SCHEMA = {
  $schema: 'https://json-schema.org/draft/2020-12/schema',
  type: 'object',
  required: ['name', 'address'],
  properties: {
    name: { type: 'string', title: 'Name', maxLength: 100 },
    brief: { type: 'string', description: 'What it is.' },
    notes: { type: 'string', maxLength: 2000 },
    count: { type: 'integer', minimum: 0, maximum: 9 },
    weight: { type: 'number' },
    lit: { type: 'boolean', title: 'Lit at night' },
    size: { type: 'string', enum: ['small', 'large'] },
    level: { type: 'integer', enum: [1, 2, 3] },
    tags: { type: 'array', items: { type: 'string' } },
    address: {
      type: 'object',
      title: 'Where',
      required: ['street'],
      properties: {
        street: { type: 'string' },
        floor: { type: 'integer' },
        deeper: { type: 'object', properties: { x: { type: 'string' } } },
      },
    },
    shape: { $ref: '#/$defs/shape' },
    matrix: { type: 'array', items: { type: 'array', items: { type: 'number' } } },
    either: { oneOf: [{ type: 'string' }, { type: 'number' }] },
    maybe: { type: ['string', 'null'] },
  },
  $defs: { shape: { type: 'string', enum: ['round', 'square'] } },
};

const byKey = (fields: FormField[]) => Object.fromEntries(fields.map((f) => [f.key, f]));

describe('buildFields', () => {
  const fields = buildFields(SCHEMA, { briefField: 'brief' });
  const f = byKey(fields);

  it('keeps the schema order and uses the title, or a readable form of the key', () => {
    expect(fields.map((x) => x.key).slice(0, 3)).toEqual(['name', 'brief', 'notes']);
    expect(f['name'].label).toBe('Name');
    expect(f['lit'].label).toBe('Lit at night');
    expect(f['count'].label).toBe('Count');
  });

  it('draws a plain string as one line, and the brief field as long text', () => {
    expect(f['name'].type).toBe('string');
    expect(f['brief'].type).toBe('text');
    expect(f['brief'].description).toBe('What it is.');
  });

  it('draws a string with a long maxLength as long text too', () => {
    expect(f['notes'].type).toBe('text');
  });

  it('knows numbers, integers and their limits', () => {
    expect(f['weight'].type).toBe('number');
    expect(f['count'].type).toBe('integer');
    expect(f['count'].minimum).toBe(0);
    expect(f['count'].maximum).toBe(9);
  });

  it('knows booleans', () => {
    expect(f['lit'].type).toBe('boolean');
  });

  it('turns an enum into a choice, strings or numbers', () => {
    expect(f['size'].type).toBe('enum');
    expect(f['size'].enumValues).toEqual(['small', 'large']);
    expect(f['level'].enumValues).toEqual([1, 2, 3]);
  });

  it('turns an array of strings into tags', () => {
    expect(f['tags'].type).toBe('tags');
  });

  it('marks required fields, at the top and inside a group', () => {
    expect(f['name'].required).toBe(true);
    expect(f['brief'].required).toBe(false);
    const address = f['address'];
    expect(address.required).toBe(true);
    expect(byKey(address.children)['street'].required).toBe(true);
    expect(byKey(address.children)['floor'].required).toBe(false);
  });

  it('groups an object one level deep, with pointers into data', () => {
    const address = f['address'];
    expect(address.type).toBe('group');
    expect(address.label).toBe('Where');
    expect(address.children.map((c) => c.pointer)).toEqual(['/data/address/street', '/data/address/floor', '/data/address/deeper']);
  });

  it('does not nest deeper than one level: the next object is kept read-only', () => {
    expect(byKey(f['address'].children)['deeper'].type).toBe('unsupported');
  });

  it('resolves a local $ref', () => {
    expect(f['shape'].type).toBe('enum');
    expect(f['shape'].enumValues).toEqual(['round', 'square']);
  });

  it('marks what it cannot draw as unsupported instead of dropping it', () => {
    expect(f['matrix'].type).toBe('unsupported');
    expect(f['either'].type).toBe('unsupported');
  });

  it('treats a nullable string as a string', () => {
    expect(f['maybe'].type).toBe('string');
  });

  it('escapes pointer segments', () => {
    expect(pointerOf(['a/b', 'c~d'])).toBe('/data/a~1b/c~0d');
  });
});

describe('values to data', () => {
  const fields = buildFields(SCHEMA, { briefField: 'brief' });

  it('leaves out optional fields that are empty, so the schema never sees empty strings', () => {
    const data = toData(fields, { name: 'Lamp', brief: '', tags: [], size: '', count: undefined, address: { street: 'Main Street', floor: undefined } });
    expect(data).toEqual({ name: 'Lamp', address: { street: 'Main Street' } });
  });

  it('keeps false, zero and non-empty values', () => {
    const data = toData(fields, { name: 'Lamp', lit: false, count: 0, tags: ['a'], address: { street: 's' } });
    expect(data).toEqual({ name: 'Lamp', lit: false, count: 0, tags: ['a'], address: { street: 's' } });
  });

  it('sends a required field that is empty as empty, so the API names that field', () => {
    expect(toData(fields, {})['name']).toBe('');
    expect(toData(fields, { name: 'x', address: {} })['address']).toEqual({ street: '' });
  });

  it('passes through values the form cannot draw, and keys it does not know', () => {
    const data = toData(fields, { name: 'x', address: { street: 's' }, matrix: [[1]], extra: 5 });
    expect(data['matrix']).toEqual([[1]]);
    expect(data['extra']).toBe(5);
  });

  it('setValue changes one place and leaves the original alone', () => {
    const before = { name: 'a', address: { street: 's' } };
    const after = setValue(before, ['address', 'floor'], 3);
    expect(after).toEqual({ name: 'a', address: { street: 's', floor: 3 } });
    expect(before).toEqual({ name: 'a', address: { street: 's' } });
    expect(setValue(after, ['name'], undefined)).toEqual({ address: { street: 's', floor: 3 } });
  });

  it('reads what is typed into a number box', () => {
    expect(parseNumber('', false)).toBeUndefined();
    expect(parseNumber(' 4 ', true)).toBe(4);
    expect(parseNumber('4.5', false)).toBe(4.5);
    expect(parseNumber('4.5', true)).toBe('4.5');
    expect(parseNumber('abc', false)).toBe('abc');
  });
});

describe('isDirty', () => {
  const fields = buildFields(SCHEMA, { briefField: 'brief' });
  const saved = { name: 'Lamp', address: { street: 'Main Street' } };

  it('is clean for the same data, and when an optional field is typed into and cleared again', () => {
    expect(isDirty(fields, saved, saved)).toBe(false);
    expect(isDirty(fields, saved, { ...saved, brief: '' })).toBe(false);
  });

  it('is dirty after a real change', () => {
    expect(isDirty(fields, saved, { ...saved, name: 'Other' })).toBe(true);
    expect(isDirty(fields, saved, { ...saved, tags: ['x'] })).toBe(true);
    expect(isDirty(fields, saved, { ...saved, address: { street: 'Main Street', floor: 2 } })).toBe(true);
  });

  it('ignores the order of keys', () => {
    expect(isDirty(fields, { name: 'a', address: { street: 'b' } }, { address: { street: 'b' }, name: 'a' })).toBe(false);
  });
});

describe('mapError', () => {
  const fields = buildFields(SCHEMA, { briefField: 'brief' });

  it('puts an error on the field its pointer names, without the pointer in the message', () => {
    const result = mapError({ field: '/data/name', message: "/data/name: '' should be non-empty" }, fields);
    expect(result.byPointer).toEqual({ '/data/name': "'' should be non-empty" });
    expect(result.general).toBeNull();
  });

  it('puts an error about one array item on the array field', () => {
    const result = mapError({ field: '/data/tags/0', message: "/data/tags/0: '' should be non-empty" }, fields);
    expect(Object.keys(result.byPointer)).toEqual(['/data/tags']);
  });

  it('finds a field inside a group', () => {
    const result = mapError({ field: '/data/address/street', message: "/data/address/street: 'street' is a required property" }, fields);
    expect(Object.keys(result.byPointer)).toEqual(['/data/address/street']);
  });

  it('does not mistake a longer key for a field that shares its start', () => {
    const result = mapError({ field: '/data/names', message: '/data/names: nope' }, fields);
    expect(result.byPointer).toEqual({});
    expect(result.general).toBe('nope');
  });

  it('makes an error about the whole body, or with no field, a general message', () => {
    const body = mapError({ field: '/data', message: "/data: Additional properties are not allowed ('zzz' was unexpected)" }, fields);
    expect(body.byPointer).toEqual({});
    expect(body.general).toBe("Additional properties are not allowed ('zzz' was unexpected)");
    const none = mapError({ field: null, message: 'Something broke.' }, fields);
    expect(none.general).toBe('Something broke.');
  });
});
