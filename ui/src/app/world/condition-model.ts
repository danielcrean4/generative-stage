/**
 * The pure parts of editing a condition as JSON text: reading the text, suggesting fact patterns,
 * building a leaf from three inputs and adding it to what is there. Whether a condition is right is
 * the server's to say (POST .../vocabulary/check); nothing here judges a fact or an operator.
 */
import { JsonObject, Vocabulary, VocabularyFact } from './world-models';

export type Parsed = { ok: true; value: unknown } | { ok: false; error: string };

const WORDS = {
  notJson: (why: string) => `This is not JSON yet: ${why}`,
};

/** The text as JSON; empty text is null (no condition). */
export function parseJson(text: string): Parsed {
  if (!text.trim()) return { ok: true, value: null };
  try {
    return { ok: true, value: JSON.parse(text) };
  } catch (err) {
    return { ok: false, error: WORDS.notJson(err instanceof Error ? err.message : String(err)) };
  }
}

export function formatJson(value: unknown): string {
  return value === null || value === undefined ? '' : JSON.stringify(value, null, 2);
}

/** Fact patterns whose text or description holds what was typed, at most `limit`. */
export function suggestFacts(vocabulary: Vocabulary, typed: string, limit = 30): VocabularyFact[] {
  const needle = typed.trim().toLowerCase().replace(/\(.*?\)/g, '(');
  return vocabulary.facts
    .filter((f) => !needle || f.pattern.replace(/\(.*?\)/g, '(').includes(needle) || (f.doc ?? '').toLowerCase().includes(needle))
    .slice(0, limit);
}

/** Operators that accept a fact type, by name. */
export function operatorsFor(vocabulary: Vocabulary, factType: string | null): string[] {
  return Object.entries(vocabulary.operators)
    .filter(([, op]) => factType === null || op.types.includes(factType))
    .map(([name]) => name);
}

/** A typed value read as the JSON a fact of that JSON type compares with: numbers and true/false become
 * themselves, a list operand is split on commas. */
export function operand(raw: string, jsonType: string, list: boolean): unknown {
  if (list) return raw.split(',').map((part) => operand(part.trim(), jsonType, false));
  const text = raw.trim();
  if (jsonType === 'integer' || jsonType === 'number') {
    const n = Number(text);
    return text !== '' && Number.isFinite(n) ? n : text;
  }
  if (jsonType === 'boolean') return text === 'true' ? true : text === 'false' ? false : text;
  if (jsonType === 'array') return text ? text.split(',').map((part) => part.trim()) : [];
  return text;
}

export function leaf(path: string, op: string, value: unknown): JsonObject {
  return { fact: path, [op]: value };
}

/** Add a leaf to a condition: nothing becomes the leaf, an `all` gains it, anything else is joined with it in an `all`. */
export function addLeaf(current: unknown, added: JsonObject): JsonObject {
  if (current === null || current === undefined) return added;
  if (typeof current === 'object' && !Array.isArray(current) && Array.isArray((current as JsonObject)['all']) && Object.keys(current).length === 1) {
    return { all: [...((current as JsonObject)['all'] as unknown[]), added] };
  }
  return { all: [current, added] };
}
