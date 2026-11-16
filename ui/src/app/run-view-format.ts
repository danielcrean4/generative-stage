import { RunFile } from './run-view-api';

export interface KeyValueRow {
  key: string;
  value: string;
}

function scalar(value: unknown): string {
  if (value === null || value === undefined) return 'none';
  if (typeof value === 'string') return value;
  return JSON.stringify(value);
}

/**
 * Flattens nested objects into dotted keys so every field shows as one readable row.
 * Arrays are kept as one compact JSON value. Rows whose last key segment is `prompt` come first.
 */
export function flattenRows(source: unknown, prefix = ''): KeyValueRow[] {
  const rows: KeyValueRow[] = [];
  const isRecord = (v: unknown): v is Record<string, unknown> =>
    typeof v === 'object' && v !== null && !Array.isArray(v);
  if (Array.isArray(source)) {
    return [{ key: prefix || 'value', value: scalar(source) }];
  }
  if (!isRecord(source)) {
    return [{ key: prefix || 'value', value: scalar(source) }];
  }
  for (const [name, value] of Object.entries(source)) {
    const key = prefix ? `${prefix}.${name}` : name;
    if (isRecord(value) && Object.keys(value).length > 0) {
      rows.push(...flattenRows(value, key));
    } else {
      rows.push({ key, value: scalar(value) });
    }
  }
  return rows;
}

export function recipeRows(recipe: Record<string, unknown> | null): KeyValueRow[] {
  const rows = flattenRows(recipe ?? {});
  const isPrompt = (r: KeyValueRow) => r.key.split('.').pop() === 'prompt';
  return [...rows.filter(isPrompt), ...rows.filter((r) => !isPrompt(r))];
}

export function measureRows(measures: Record<string, unknown> | unknown[] | null): KeyValueRow[] {
  if (measures === null || measures === undefined) return [];
  if (Array.isArray(measures)) {
    return measures.map((m, i) => ({ key: `item ${i + 1}`, value: scalar(m) }));
  }
  return flattenRows(measures);
}

export type Verdict = 'pass' | 'review' | 'fail' | 'none';

/** `verdict` is the gate v2 word; a `review` verdict is not a failure, a person has to look at the sheet. */
export function verdictOf(passed: boolean | null, verdict?: string | null): Verdict {
  if (verdict === 'review') return 'review';
  return passed === true ? 'pass' : passed === false ? 'fail' : 'none';
}

export function verdictLabel(passed: boolean | null, verdict?: string | null): string {
  return {
    pass: 'Passed',
    review: 'Needs a person to look (review)',
    fail: 'Failed',
    none: 'No verdict (this report only lists what was checked)',
  }[verdictOf(passed, verdict)];
}

export function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? '' : 's'}`;
}

/** "2m 5s" for the gap between two ISO times; null when either is missing or invalid. */
export function formatDuration(started: string | null, finished: string | null): string | null {
  if (!started || !finished) return null;
  const seconds = Math.round((Date.parse(finished) - Date.parse(started)) / 1000);
  if (!Number.isFinite(seconds) || seconds < 0) return null;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h > 0) return `${h}h ${m}m ${s}s`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

export function formatTime(iso: string | null): string {
  if (!iso) return 'unknown';
  const t = new Date(iso);
  return Number.isNaN(t.getTime()) ? iso : t.toLocaleString();
}

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export type FileKind = 'image' | 'model' | 'text' | 'other';

export function fileKind(file: RunFile): FileKind {
  if (file.media_type.startsWith('image/')) return 'image';
  if (file.name.endsWith('.glb')) return 'model';
  if (file.name.endsWith('.log') || file.name.endsWith('.json') || file.name.endsWith('.txt')) {
    return 'text';
  }
  return 'other';
}
