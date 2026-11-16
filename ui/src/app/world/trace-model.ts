import { Choice, TraceFile, TraceStage, Verdict } from './world-models';

/**
 * The rules behind the trace page, with no drawing in them: how a stage shows, which of its files
 * can be chosen and for what, and how long things took.
 */

const ORDER: Verdict[] = ['pass', 'review', 'fail'];

/** The worst gate outcome of a stage, or null when it has no gate. */
export function stageOutcome(stage: TraceStage): Verdict | null {
  const found = stage.gates.map((g) => g.outcome).filter((o): o is Verdict => o !== null);
  if (found.length === 0) return null;
  return found.reduce((worst, o) => (ORDER.indexOf(o) > ORDER.indexOf(worst) ? o : worst));
}

/** "45 s", "2 min 05 s", "1 h 03 min"; null when the run did not record a time. */
export function formatSeconds(seconds: number | null): string | null {
  if (seconds === null) return null;
  const whole = Math.round(seconds);
  if (whole < 60) return `${whole} s`;
  const minutes = Math.floor(whole / 60);
  if (minutes < 60) return `${minutes} min ${String(whole % 60).padStart(2, '0')} s`;
  return `${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, '0')} min`;
}

/** The name a stage goes by: its label, with the retry it belongs to when it is not the first try. */
export function stageTitle(stage: TraceStage): string {
  return stage.retry > 0 ? `${stage.label} (retry ${stage.retry})` : stage.label;
}

/** The files of a stage that are pictures or 3D files, in name order. Reports and logs are left out. */
export function shownFiles(stage: TraceStage): TraceFile[] {
  return stage.files.filter((f) => f.kind !== 'other');
}

/** The slots a file can be chosen for: images fill the image or icon slot, 3D files the 3D slot. */
export function slotsFor(file: TraceFile): string[] {
  if (file.kind === 'model') return ['mesh'];
  if (file.kind === 'image') return ['main', 'icon'];
  return [];
}

export function isChosen(file: TraceFile, runId: string, chosen: Record<string, Choice>): string | null {
  const slot = Object.keys(chosen).find((s) => chosen[s].run_id === runId && chosen[s].candidate === file.candidate);
  return slot ?? null;
}

export function folderOf(stage: TraceStage): string {
  return stage.folder ?? stage.id;
}

/** The stage to open first: the first that errored, else the first with a failing or review gate, else the last that ran. */
export function firstToLookAt(stages: TraceStage[]): TraceStage | null {
  const ran = stages.filter((s) => s.status !== 'not_run');
  return (
    ran.find((s) => s.status === 'errored') ??
    ran.find((s) => stageOutcome(s) === 'fail' || stageOutcome(s) === 'review') ??
    ran[ran.length - 1] ??
    stages[0] ??
    null
  );
}

/** A value from a pipeline file as short text for a table cell. */
export function showValue(value: unknown): string {
  if (typeof value === 'string') return value;
  return JSON.stringify(value);
}
