import { signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { toWorldError, WorldApi } from './world-api';
import { AttachedRun, Choice, JobView, Revision } from './world-models';

/**
 * What the profile page reads about one entity besides its fields: the choice per slot, every
 * choice, the attached runs, the jobs with their candidates and the revisions. Each list is a
 * signal; `loadAll` reads them together and `loadRevisions` reads that list alone (after a save).
 */
export class ProfileData {
  readonly chosen = signal<Record<string, Choice>>({});
  readonly choices = signal<Choice[]>([]);
  readonly runs = signal<AttachedRun[]>([]);
  readonly jobs = signal<JobView[]>([]);
  readonly revisions = signal<Revision[]>([]);
  readonly loaded = signal(false);
  readonly error = signal<string | null>(null);

  constructor(
    private readonly api: WorldApi,
    readonly slug: string,
    readonly entityId: string,
  ) {}

  async loadAll(): Promise<void> {
    this.error.set(null);
    try {
      const [chosen, choices, runs, jobs, revisions] = await Promise.all([
        firstValueFrom(this.api.chosen(this.slug, this.entityId)),
        firstValueFrom(this.api.choices(this.slug, this.entityId)),
        firstValueFrom(this.api.runs(this.slug, this.entityId)),
        firstValueFrom(this.api.jobs(this.slug, this.entityId)),
        firstValueFrom(this.api.revisions(this.slug, this.entityId)),
      ]);
      this.chosen.set(chosen);
      this.choices.set(choices);
      this.runs.set(runs);
      this.jobs.set(jobs);
      this.revisions.set(revisions);
      this.loaded.set(true);
    } catch (err) {
      this.error.set(toWorldError(err).message);
    }
  }

  async loadRevisions(): Promise<void> {
    try {
      this.revisions.set(await firstValueFrom(this.api.revisions(this.slug, this.entityId)));
    } catch (err) {
      this.error.set(toWorldError(err).message);
    }
  }

  /** Make a candidate the choice for a slot, then read the choices again. Resolves an error message, or null. */
  async choose(runId: string, candidate: string, slot: string, note?: string): Promise<string | null> {
    try {
      await firstValueFrom(this.api.choose(this.slug, this.entityId, runId, candidate, slot, note));
      const [chosen, choices, runs] = await Promise.all([
        firstValueFrom(this.api.chosen(this.slug, this.entityId)),
        firstValueFrom(this.api.choices(this.slug, this.entityId)),
        firstValueFrom(this.api.runs(this.slug, this.entityId)),
      ]);
      this.chosen.set(chosen);
      this.choices.set(choices);
      this.runs.set(runs);
      return null;
    } catch (err) {
      return toWorldError(err).message;
    }
  }
}
