import { Statistics } from './world-models';

/** The rules behind the statistics page, with no drawing in them. */

/** A bar's length as a whole percent of the longest (at least 2 for a value above zero, so it can be seen). */
export function barPercent(value: number, max: number): number {
  if (value <= 0 || max <= 0) return 0;
  return Math.max(2, Math.round((value / max) * 100));
}

/** The day and month of an ISO day (2026-11-05 becomes 5 Nov), in the person's language. */
export function shortDay(day: string): string {
  const date = new Date(`${day}T00:00:00`);
  if (Number.isNaN(date.getTime())) return day;
  return date.toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
}

/** Seconds as a short length of time: "45 s", "2.5 min", "1.2 h". */
export function duration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)} s`;
  if (seconds < 3600) return `${trim(seconds / 60)} min`;
  return `${trim(seconds / 3600)} h`;
}

function trim(value: number): string {
  return String(Math.round(value * 10) / 10);
}

/** The most runs in one day, for the height of the day bars. */
export function busiestDay(stats: Statistics): number {
  return Math.max(0, ...stats.by_day.map((d) => d.completed + d.errored + d.other));
}

/** The longest total stage time, for the stage bars. */
export function longestStage(stats: Statistics): number {
  return Math.max(0, ...stats.by_stage.map((s) => s.total_seconds));
}
