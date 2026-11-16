import { Kind, KindFamily, ScriptForm } from './world-models';

/** The families in the order the app lists them, each with its group heading. */
export const FAMILIES: readonly { id: KindFamily; label: string }[] = [
  { id: 'prop', label: 'Props' },
  { id: 'character', label: 'Characters' },
  { id: 'setting', label: 'Settings' },
  { id: 'script', label: 'Scripts' },
  { id: 'stage', label: 'Stages' },
];

/** The heading for kinds that name no family. */
export const OTHER_LABEL = 'Other';

/** The badge a script kind shows for its form, and what the badge means. */
export const FORM_WORDS: Record<ScriptForm, { badge: string; title: string }> = {
  linear: { badge: 'linear', title: 'A linear script: its lines run in order.' },
  branching: { badge: 'branching', title: 'A branching script: choices lead to different lines.' },
};

export interface KindGroup {
  /** The family, or 'other' for kinds with none. */
  id: KindFamily | 'other';
  label: string;
  kinds: Kind[];
}

/** The kinds grouped by family, in family order with Other last. Empty groups are left out; inside a
 * group the kinds keep the order the project lists them in. */
export function groupByFamily(kinds: readonly Kind[]): KindGroup[] {
  const known = new Set<string>(FAMILIES.map((f) => f.id));
  const groups: KindGroup[] = FAMILIES.map((f) => ({ id: f.id, label: f.label, kinds: kinds.filter((k) => k.family === f.id) }));
  groups.push({ id: 'other', label: OTHER_LABEL, kinds: kinds.filter((k) => !k.family || !known.has(k.family)) });
  return groups.filter((g) => g.kinds.length > 0);
}

/** The form badge for a script kind, or null for any other kind. */
export function formBadge(kind: Kind): { badge: string; title: string } | null {
  return kind.family === 'script' && kind.form ? FORM_WORDS[kind.form] ?? null : null;
}
