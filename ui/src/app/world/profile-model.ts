import { excerpt } from './world-format';
import { AttachedRun, Choice, JobView, JsonObject, Note, Revision, Verdict } from './world-models';

/**
 * The rules behind the profile page, with no drawing in them: what kind of file a candidate is,
 * which candidates to offer, what changed between two revisions and how revisions, attached runs
 * and choices merge into one stream.
 */

export type FileKind = 'image' | 'model' | 'other';

const IMAGE = /\.(png|jpe?g|gif)$/i;
const MODEL = /\.glb$/i;

/** What a candidate is, from its file name; the slot does not say. */
export function fileKind(candidate: string): FileKind {
  if (IMAGE.test(candidate)) return 'image';
  if (MODEL.test(candidate)) return 'model';
  return 'other';
}

const SLOT_NAMES: Record<string, string> = { main: 'Image', mesh: '3D', icon: 'Icon' };

export function slotLabel(slot: string): string {
  if (SLOT_NAMES[slot]) return SLOT_NAMES[slot];
  const spaced = slot.replace(/_/g, ' ');
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

const BASE_SLOTS = ['main', 'mesh', 'icon'];

/** The slots to show tabs for: the usual three, then any other slot that has a choice, by name. */
export function slotsOf(chosen: Record<string, Choice>): string[] {
  return [...BASE_SLOTS, ...Object.keys(chosen).filter((s) => !BASE_SLOTS.includes(s)).sort()];
}

/** The start of an id, enough to tell runs apart. */
export function shortId(id: string): string {
  return id.length > 8 ? `${id.slice(0, 8)}…` : id;
}

/** The file name at the end of a candidate path. */
export function baseName(candidate: string): string {
  return candidate.slice(candidate.lastIndexOf('/') + 1);
}

/** The trace page's query for a candidate path (`attempts/<attempt>/<stage>/<file>`): that attempt and stage, else nothing. */
export function traceQuery(candidate: string): { attempt?: string; stage?: string } {
  const parts = candidate.split('/');
  return parts.length >= 4 && parts[0] === 'attempts' ? { attempt: parts[1], stage: parts[2] } : {};
}

export interface CandidateItem {
  runId: string;
  candidate: string;
  kind: FileKind;
  verdict: Verdict | null;
  /** The slot it was chosen for, when it is known only from a choice (no job lists it). */
  slot?: string;
  /** When the candidate was made or last chosen; newest sorts first. */
  at: string;
}

/**
 * The candidates to offer: everything the entity's jobs made, plus anything chosen before whose
 * run is attached (a run attached by hand has no job to list its files), for the slot they were
 * chosen for. One entry per file.
 */
export function candidateItems(jobs: JobView[], choices: Choice[]): CandidateItem[] {
  const found = new Map<string, CandidateItem>();
  for (const { job, candidates } of jobs) {
    for (const c of candidates) {
      if (!c.candidate) continue;
      found.set(`${job.id}|${c.candidate}`, {
        runId: job.id,
        candidate: c.candidate,
        kind: fileKind(c.candidate),
        verdict: c.verdict,
        at: c.created_at,
      });
    }
  }
  for (const c of choices) {
    const key = `${c.run_id}|${c.candidate}`;
    if (!found.has(key)) found.set(key, { runId: c.run_id, candidate: c.candidate, kind: fileKind(c.candidate), verdict: null, slot: c.slot, at: c.chosen_at });
  }
  return [...found.values()].sort((a, b) => b.at.localeCompare(a.at));
}

/**
 * Whether a candidate can fill a slot: a 3D slot takes models, every other slot takes images. One
 * known only from a choice is offered for the slot it was chosen for.
 */
export function fitsSlot(item: CandidateItem, slot: string): boolean {
  if (item.slot !== undefined) return item.slot === slot;
  return slot === 'mesh' ? item.kind === 'model' : item.kind === 'image';
}

export function sameFile(a: { run_id: string; candidate: string } | null, b: CandidateItem): boolean {
  return a !== null && a.run_id === b.runId && a.candidate === b.candidate;
}

export interface FieldDiff {
  key: string;
  label: string;
  before: string;
  after: string;
}

function show(value: unknown): string {
  if (value === undefined || value === null || value === '') return 'empty';
  if (typeof value === 'string') return excerpt(value, 60);
  return excerpt(JSON.stringify(value), 60);
}

/** The top-level fields whose value differs between two versions of an entity's data. */
export function changedFields(before: JsonObject, after: JsonObject, labelOf: (key: string) => string): FieldDiff[] {
  const keys = [...new Set([...Object.keys(before), ...Object.keys(after)])];
  return keys
    .filter((key) => JSON.stringify(before[key]) !== JSON.stringify(after[key]))
    .map((key) => ({ key, label: labelOf(key), before: show(before[key]), after: show(after[key]) }));
}

export type StreamKind = 'change' | 'run' | 'choice' | 'note';

export interface StreamEvent {
  id: string;
  kind: StreamKind;
  at: string;
  title: string;
  note: string | null;
  changes: FieldDiff[];
  /** The image a choice made, when there is one to show. */
  thumb: { runId: string; candidate: string } | null;
  /** The note itself, for a note event. */
  noteItem: Note | null;
}

export type StreamFilter = 'all' | 'change' | 'run' | 'note';

/** Revisions, attached runs, choices and notes as one list, newest first. */
export function buildStream(
  revisions: Revision[],
  runs: AttachedRun[],
  choices: Choice[],
  labelOf: (key: string) => string,
  notes: Note[] = [],
): StreamEvent[] {
  const events: StreamEvent[] = [];
  const ordered = [...revisions].sort((a, b) => a.revision - b.revision);
  ordered.forEach((rev, i) => {
    const prev = i > 0 ? ordered[i - 1] : null;
    let title = `Revision ${rev.revision} saved`;
    if (!prev) title = `Created at revision ${rev.revision}`;
    else if (rev.archived && !prev.archived) title = `Revision ${rev.revision}: archived`;
    else if (!rev.archived && prev.archived) title = `Revision ${rev.revision}: restored`;
    events.push({
      id: `revision-${rev.revision}`,
      kind: 'change',
      at: rev.created_at,
      title,
      note: rev.note,
      changes: prev ? changedFields(prev.data, rev.data, labelOf) : [],
      thumb: null,
      noteItem: null,
    });
  });
  for (const run of runs) {
    events.push({
      id: `run-${run.run_id}`,
      kind: 'run',
      at: run.attached_at,
      title: `Run ${shortId(run.run_id)} attached`,
      note: run.note,
      changes: [],
      thumb: null,
      noteItem: null,
    });
  }
  for (const c of choices) {
    events.push({
      id: `choice-${c.slot}-${c.chosen_at}`,
      kind: 'choice',
      at: c.chosen_at,
      title: `Chose ${baseName(c.candidate)} from run ${shortId(c.run_id)} as ${slotLabel(c.slot).toLowerCase()}`,
      note: c.note,
      changes: [],
      thumb: fileKind(c.candidate) === 'image' ? { runId: c.run_id, candidate: c.candidate } : null,
      noteItem: null,
    });
  }
  for (const n of notes) {
    events.push({ id: `note-${n.id}`, kind: 'note', at: n.created_at, title: '', note: null, changes: [], thumb: null, noteItem: n });
  }
  return events.sort((a, b) => (a.at === b.at ? b.id.localeCompare(a.id) : b.at.localeCompare(a.at)));
}

export function filterStream(events: StreamEvent[], filter: StreamFilter): StreamEvent[] {
  if (filter === 'all') return events;
  if (filter === 'run') return events.filter((e) => e.kind === 'run' || e.kind === 'choice');
  return events.filter((e) => e.kind === filter);
}

export interface Freshness {
  chosenAt: number;
  now: number;
  /** Fields that differ between the revision the choice was made at and now. */
  changed: FieldDiff[];
}

/** How the entity has moved on since a choice. Null when the revision the choice names is not in the list. */
export function freshness(choice: Choice, current: number, revisions: Revision[], labelOf: (key: string) => string): Freshness | null {
  const then = revisions.find((r) => r.revision === choice.entity_revision);
  const now = revisions.find((r) => r.revision === current);
  if (!then || !now) return null;
  return { chosenAt: choice.entity_revision, now: current, changed: changedFields(then.data, now.data, labelOf) };
}
