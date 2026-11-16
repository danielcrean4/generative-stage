import { JsonObject } from './world-models';

/** One parameter of a parametric kind, as the server reads it from the kind's schema (core/parameters.py). */
export interface ParamField {
  name: string;
  label: string;
  about: string;
  type: 'number' | 'integer' | 'enum' | 'boolean' | 'colour';
  min?: number;
  max?: number;
  step?: number | null;
  unit?: string | null;
  values?: string[];
  default: unknown;
  /** The selector values this field belongs to; null for every variant. */
  builders: string[] | null;
  /** The switch that turns this field on; null when it always applies. */
  when: string | null;
}

export interface ParamModel {
  selector: string | null;
  fields: ParamField[];
}

export interface GateResult {
  id: string;
  about: string;
  measure: string;
  value: number | null;
  verdict: 'pass' | 'review' | 'fail';
}

export interface PreviewView {
  id: string;
  row: JsonObject;
  still: string;
  views: string[];
  numbers: Record<string, number>;
  gates: GateResult[];
  verdict: 'pass' | 'review' | 'fail';
  seconds: number;
}

export interface BatchTile {
  id: string;
  cell: Record<string, string>;
  seed: number;
  row: JsonObject;
  still: string;
  numbers: Record<string, number>;
  gates: GateResult[];
  verdict: 'pass' | 'review' | 'fail';
}

export const TRIAGE = ['keep', 'fix', 'improve', 'remove'] as const;
export type TriageVerdict = (typeof TRIAGE)[number];
export type Triage = Record<string, { verdict: TriageVerdict; note: string }>;

export interface BatchView {
  id: string;
  kind: string;
  seed: number;
  count: number;
  dropped: number;
  adapters: Record<string, string>;
  seconds: { rules: number; total: number };
  tiles: BatchTile[];
  triage: Triage;
}

export interface ParametricInfo {
  kind: string;
  parameters: ParamModel;
  has_kit: boolean;
  subject_fields: Record<string, string[] | null>;
  gates: { id: string; about: string; measure: string; verdict: string }[];
  adapters: Record<string, string[]>;
  defaults: Record<string, string | null>;
}

/** The fields that apply to a row: those of its variant whose switch is on (the same rule as the server's). */
export function activeFields(model: ParamModel, row: JsonObject): ParamField[] {
  const variant = model.selector ? row[model.selector] : null;
  const ofVariant = model.fields.filter((f) => f.builders === null || (typeof variant === 'string' && f.builders.includes(variant)));
  const names = new Set(ofVariant.map((f) => f.name));
  return ofVariant.filter((f) => f.when === null || (names.has(f.when) && row[f.when] === true));
}

/** The row with every active field set (from the row, else its default) and every inactive one dropped. Fields that
 *  are not parameters (a name, a brief) are kept. */
export function settle(model: ParamModel, row: JsonObject): JsonObject {
  const next: JsonObject = { ...row };
  for (let pass = 0; pass <= model.fields.length; pass++) {
    for (const f of activeFields(model, next)) {
      if (!(f.name in next)) next[f.name] = f.default;
    }
  }
  const active = new Set(activeFields(model, next).map((f) => f.name));
  for (const f of model.fields) {
    if (!active.has(f.name)) delete next[f.name];
  }
  return next;
}

export function setValue(model: ParamModel, row: JsonObject, name: string, value: unknown): JsonObject {
  return settle(model, { ...row, [name]: value });
}

export function show(f: ParamField, value: unknown): string {
  if (f.type === 'boolean') return value === true ? 'on' : 'off';
  return `${value ?? ''}${f.unit && (f.type === 'number' || f.type === 'integer') ? ` ${f.unit}` : ''}`;
}

export function stillUrl(slug: string, id: string, file = 'still.png'): string {
  return `/api/v1/projects/${encodeURIComponent(slug)}/parametric/previews/${encodeURIComponent(id)}/${file}`;
}

export function tileUrl(slug: string, batch: string, tile: string, file = 'still.png'): string {
  return `/api/v1/projects/${encodeURIComponent(slug)}/parametric/batches/${encodeURIComponent(batch)}/files/tiles/${encodeURIComponent(tile)}/${file}`;
}
