import { MentionRef } from './world-models';

/**
 * The rules behind notes on the profile, with no drawing in them: where a mention is in a text,
 * what a person is typing when they type `@`, and how the readable draft ("@Mechanic") becomes the
 * stored text ("@character/<id>") and back.
 */

export interface EntityRef {
  id: string;
  kind: string;
  title: string;
}

/** A piece of a note: plain text, or a mention (then `text` is empty). */
export interface Segment {
  text: string;
  mention: MentionRef | null;
}

const TOKEN = /@([a-z][a-z0-9_]{0,63})\/([A-Za-z0-9][A-Za-z0-9-]{0,63})/g;

/** A stored text cut into plain pieces and `@kind/id` mentions. */
export function splitMentions(text: string): Segment[] {
  const out: Segment[] = [];
  let last = 0;
  for (const m of text.matchAll(TOKEN)) {
    if (m.index > last) out.push({ text: text.slice(last, m.index), mention: null });
    out.push({ text: '', mention: { kind: m[1], id: m[2] } });
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push({ text: text.slice(last), mention: null });
  return out;
}

export interface Trigger {
  /** Where the `@` is. */
  start: number;
  /** What was typed after it. */
  query: string;
}

/** The `@word` the caret is at the end of, when the `@` starts the text or follows a space. */
export function mentionTrigger(text: string, caret: number): Trigger | null {
  const before = text.slice(0, caret);
  const m = /(^|\s)@([^\s@]*)$/.exec(before);
  return m ? { start: caret - m[2].length - 1, query: m[2] } : null;
}

/** The entities to offer for what was typed: titles starting with it first, then containing it. */
export function matchEntities(all: EntityRef[], query: string, max = 6): EntityRef[] {
  const q = query.toLowerCase();
  const starts = all.filter((e) => e.title.toLowerCase().startsWith(q));
  const inside = all.filter((e) => !e.title.toLowerCase().startsWith(q) && e.title.toLowerCase().includes(q));
  return [...starts, ...inside].slice(0, max);
}

/** The text with the typed `@query` replaced by `@Title `, and where the caret goes. */
export function insertMention(text: string, trigger: Trigger, caret: number, title: string): { text: string; caret: number } {
  const inserted = `@${title} `;
  return { text: text.slice(0, trigger.start) + inserted + text.slice(caret), caret: trigger.start + inserted.length };
}

/** The draft as it is stored: each picked `@Title` becomes `@kind/id`. Longer titles are replaced first. */
export function toStoredText(draft: string, picked: EntityRef[]): string {
  let out = draft;
  for (const p of [...picked].sort((a, b) => b.title.length - a.title.length)) {
    out = out.split(`@${p.title}`).join(`@${p.kind}/${p.id}`);
  }
  return out.trim();
}

/** A stored text as a person edits it: each known `@kind/id` becomes `@Title`. Returns the entities it found. */
export function toDraftText(stored: string, known: Map<string, EntityRef>): { text: string; picked: EntityRef[] } {
  const picked: EntityRef[] = [];
  const text = stored.replace(TOKEN, (token, kind: string, id: string) => {
    const e = known.get(id);
    if (!e || e.kind !== kind) return token;
    if (!picked.includes(e)) picked.push(e);
    return `@${e.title}`;
  });
  return { text, picked };
}

export const IMAGE_TYPES = ['image/png', 'image/jpeg', 'image/webp'];
export const MAX_IMAGE_BYTES = 5 * 1024 * 1024;

/** Why an image cannot be attached, or null. The server checks again. */
export function imageProblem(file: { type: string; size: number }): string | null {
  if (!IMAGE_TYPES.includes(file.type)) return 'Only png, jpeg and webp images can be attached.';
  if (file.size > MAX_IMAGE_BYTES) return 'That image is larger than 5 MB.';
  return null;
}
