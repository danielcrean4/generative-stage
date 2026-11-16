import { JsonObject } from './world-models';

/**
 * Turns a kind's JSON Schema into a flat description of form fields, and back into the `data`
 * object the API wants. Pure functions only: the form component draws what these describe.
 *
 * What is supported: strings (single line, or multi-line for the brief field and long ones),
 * numbers and integers, booleans, enums, arrays of strings (tag chips), and objects one level
 * deep (grouped fields). Anything else is marked `unsupported`: its value is kept as it is and
 * shown read-only, never dropped.
 */

export type FieldType = 'string' | 'text' | 'number' | 'integer' | 'boolean' | 'enum' | 'tags' | 'group' | 'unsupported';

export interface FormField {
  key: string;
  /** Keys from the root of `data` to this field. */
  path: string[];
  /** Where an API error about this field points: `/data/name`. */
  pointer: string;
  label: string;
  description: string | null;
  type: FieldType;
  required: boolean;
  enumValues: (string | number)[];
  minimum: number | null;
  maximum: number | null;
  maxLength: number | null;
  children: FormField[];
}

export interface BuildOptions {
  /** The kind's brief field: always a multi-line editor. */
  briefField?: string | null;
  /** Strings with a maxLength above this get a multi-line editor too. */
  longTextFrom?: number;
}

export interface FormErrors {
  /** Message per field pointer. */
  byPointer: Record<string, string>;
  /** What fits no field: shown above the form. */
  general: string | null;
}

type Schema = Record<string, unknown>;

const DEFAULT_LONG_TEXT_FROM = 300;

function isObject(value: unknown): value is Schema {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function escapePointer(segment: string): string {
  return segment.replace(/~/g, '~0').replace(/\//g, '~1');
}

export function pointerOf(path: string[]): string {
  return '/data' + path.map((s) => '/' + escapePointer(s)).join('');
}

/** Follow a local `$ref` such as `#/$defs/size`. Anything that does not resolve is left as it is. */
function resolve(root: Schema, schema: Schema, depth = 0): Schema {
  const ref = schema['$ref'];
  if (typeof ref !== 'string' || !ref.startsWith('#') || depth > 8) {
    return schema;
  }
  let node: unknown = root;
  for (const raw of ref.slice(1).split('/').filter(Boolean)) {
    node = isObject(node) ? node[raw.replace(/~1/g, '/').replace(/~0/g, '~')] : undefined;
  }
  if (!isObject(node)) {
    return schema;
  }
  const { $ref: _ignored, ...rest } = schema;
  return resolve(root, { ...node, ...rest }, depth + 1);
}

function simpleType(schema: Schema): string | null {
  const t = schema['type'];
  if (typeof t === 'string') return t;
  if (Array.isArray(t)) {
    const real = t.filter((x): x is string => typeof x === 'string' && x !== 'null');
    return real.length === 1 ? real[0] : null;
  }
  return null;
}

function numberOrNull(value: unknown): number | null {
  return typeof value === 'number' ? value : null;
}

function humanise(key: string): string {
  const spaced = key.replace(/[_-]+/g, ' ').trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

function buildField(root: Schema, key: string, raw: Schema, parentPath: string[], required: boolean, depth: number, options: BuildOptions): FormField {
  const schema = resolve(root, raw);
  const path = [...parentPath, key];
  const type = simpleType(schema);
  const field: FormField = {
    key,
    path,
    pointer: pointerOf(path),
    label: typeof schema['title'] === 'string' && schema['title'] ? (schema['title'] as string) : humanise(key),
    description: typeof schema['description'] === 'string' ? (schema['description'] as string) : null,
    type: 'unsupported',
    required,
    enumValues: [],
    minimum: numberOrNull(schema['minimum']),
    maximum: numberOrNull(schema['maximum']),
    maxLength: numberOrNull(schema['maxLength']),
    children: [],
  };

  const enumValues = schema['enum'];
  if (Array.isArray(enumValues) && enumValues.every((v) => typeof v === 'string' || typeof v === 'number')) {
    field.type = 'enum';
    field.enumValues = enumValues as (string | number)[];
  } else if (type === 'string') {
    const long = (field.maxLength ?? 0) > (options.longTextFrom ?? DEFAULT_LONG_TEXT_FROM);
    field.type = (key === options.briefField && depth === 0) || long ? 'text' : 'string';
  } else if (type === 'number' || type === 'integer') {
    field.type = type;
  } else if (type === 'boolean') {
    field.type = 'boolean';
  } else if (type === 'array') {
    const items = isObject(schema['items']) ? resolve(root, schema['items']) : null;
    if (items && simpleType(items) === 'string' && !Array.isArray(items['enum'])) {
      field.type = 'tags';
    }
  } else if (type === 'object' && depth === 0 && isObject(schema['properties'])) {
    field.type = 'group';
    field.children = buildProperties(root, schema, path, depth + 1, options);
  }
  return field;
}

function buildProperties(root: Schema, schema: Schema, parentPath: string[], depth: number, options: BuildOptions): FormField[] {
  const props = isObject(schema['properties']) ? schema['properties'] : {};
  const required = new Set(Array.isArray(schema['required']) ? (schema['required'] as string[]) : []);
  return Object.entries(props)
    .filter((entry): entry is [string, Schema] => isObject(entry[1]))
    .map(([key, child]) => buildField(root, key, child, parentPath, required.has(key), depth, options));
}

/** The fields of an object schema, in the schema's own order. */
export function buildFields(schema: JsonObject, options: BuildOptions = {}): FormField[] {
  return buildProperties(schema, resolve(schema, schema), [], 0, options);
}

// Values -----------------------------------------------------------------------------------------

export function getValue(values: JsonObject, path: string[]): unknown {
  let node: unknown = values;
  for (const key of path) {
    if (!isObject(node)) return undefined;
    node = node[key];
  }
  return node;
}

/** A copy of `values` with the value at `path` replaced (or removed, when `value` is undefined). */
export function setValue(values: JsonObject, path: string[], value: unknown): JsonObject {
  const [head, ...rest] = path;
  const next: JsonObject = { ...values };
  if (rest.length === 0) {
    if (value === undefined) delete next[head];
    else next[head] = value;
    return next;
  }
  const child = isObject(next[head]) ? (next[head] as JsonObject) : {};
  next[head] = setValue(child, rest, value);
  return next;
}

function isEmpty(field: FormField, value: unknown): boolean {
  if (value === undefined || value === null) return true;
  if (field.type === 'tags') return Array.isArray(value) && value.length === 0;
  if (field.type === 'string' || field.type === 'text' || field.type === 'enum') return value === '';
  if (field.type === 'number' || field.type === 'integer') return value === '';
  return false;
}

/**
 * The `data` to send. Optional fields left empty are left out (the schemas forbid empty strings
 * in places and unknown properties everywhere); a required field left empty is sent empty so the
 * API answers with an error for exactly that field. Keys the form cannot draw are passed through.
 */
export function toData(fields: FormField[], values: JsonObject): JsonObject {
  const known = new Set(fields.map((f) => f.key));
  const out: JsonObject = {};
  for (const [key, value] of Object.entries(values)) {
    if (!known.has(key)) out[key] = value;
  }
  for (const field of fields) {
    const value = values[field.key];
    if (field.type === 'unsupported') {
      if (value !== undefined) out[field.key] = value;
    } else if (field.type === 'group') {
      const inner = toData(field.children, isObject(value) ? value : {});
      if (Object.keys(inner).length > 0 || (field.required && value !== undefined)) out[field.key] = inner;
    } else if (isEmpty(field, value)) {
      if (field.required && field.type !== 'boolean') out[field.key] = field.type === 'tags' ? [] : '';
    } else {
      out[field.key] = value;
    }
  }
  return out;
}

/** True when the form no longer says what `original` says (empty and absent count as the same). */
export function isDirty(fields: FormField[], original: JsonObject, current: JsonObject): boolean {
  return JSON.stringify(canonical(toData(fields, original))) !== JSON.stringify(canonical(toData(fields, current)));
}

function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical);
  if (isObject(value)) {
    return Object.fromEntries(Object.keys(value).sort().map((k) => [k, canonical(value[k])]));
  }
  return value;
}

/** Read what a person typed into a number box: empty clears it, junk is kept so the API names the field. */
export function parseNumber(text: string, integer: boolean): number | string | undefined {
  const trimmed = text.trim();
  if (trimmed === '') return undefined;
  const n = Number(trimmed);
  if (Number.isNaN(n) || (integer && !Number.isInteger(n))) return trimmed;
  return n;
}

// Errors -----------------------------------------------------------------------------------------

function allFields(fields: FormField[]): FormField[] {
  return fields.flatMap((f) => [f, ...allFields(f.children)]);
}

/**
 * Put an API error on the field it names. The pointer is matched to the deepest field whose
 * pointer it starts with, so `/data/tags/0` lands on `tags`. An error about nothing the form
 * draws (the whole body, a note, a missing connection) becomes the general message.
 */
export function mapError(error: { field: string | null; message: string }, fields: FormField[]): FormErrors {
  const target = error.field;
  let best: FormField | null = null;
  if (target) {
    for (const field of allFields(fields)) {
      const hit = target === field.pointer || target.startsWith(field.pointer + '/');
      if (hit && (!best || field.pointer.length > best.pointer.length)) best = field;
    }
  }
  if (best && target) {
    return { byPointer: { [best.pointer]: stripPointer(error.message, target) }, general: null };
  }
  return { byPointer: {}, general: target ? stripPointer(error.message, target) : error.message };
}

/** Messages arrive as `/data/name: 'name' is a required property`; the field already says where. */
export function stripPointer(message: string, pointer: string): string {
  return message.startsWith(pointer + ': ') ? message.slice(pointer.length + 2) : message;
}
