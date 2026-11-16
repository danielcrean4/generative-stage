import { computed, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { isActive } from './generate-model';
import { toWorldError, WorldApi } from './world-api';
import { Adapter, JobRequest, JobView, Pipeline } from './world-models';

const POLL_MS = 1500;

/**
 * What the Generate panel reads and does for one entity: the pipelines that serve its kind, the adapters this computer
 * has, and the run it started. `start` queues a job and then reads it every second or so until its run has finished,
 * and calls `finished` once. Every write resolves an error message, or null.
 */
export class GenerateData {
  readonly pipelines = signal<Pipeline[]>([]);
  readonly adapters = signal<Adapter[]>([]);
  readonly loaded = signal(false);
  readonly error = signal<string | null>(null);
  readonly starting = signal(false);
  readonly job = signal<JobView | null>(null);
  /** The newest run of the job being watched. */
  readonly run = computed(() => this.job()?.runs?.[0] ?? null);
  readonly active = computed(() => this.starting() || isActive(this.run()?.status));
  private stopped = false;

  constructor(
    private readonly api: WorldApi,
    readonly slug: string,
    readonly entityId: string,
    readonly entityKind: string,
    private readonly finished: () => void,
    private readonly pollMs = POLL_MS,
  ) {}

  async load(): Promise<void> {
    this.error.set(null);
    try {
      const [pipelines, adapters] = await Promise.all([firstValueFrom(this.api.pipelines(this.slug, this.entityKind)), firstValueFrom(this.api.adapters())]);
      this.pipelines.set(pipelines);
      this.adapters.set(adapters);
      this.loaded.set(true);
    } catch (err) {
      this.error.set(toWorldError(err).message);
    }
  }

  /** Queue a run and watch it. Resolves the API's message when it was refused, else null. */
  async start(request: JobRequest): Promise<string | null> {
    this.starting.set(true);
    this.stopped = false;
    try {
      this.job.set(await firstValueFrom(this.api.startJob(this.slug, this.entityId, request)));
    } catch (err) {
      return toWorldError(err).message;
    } finally {
      this.starting.set(false);
    }
    void this.watch(this.job()!.job.id);
    return null;
  }

  stop(): void {
    this.stopped = true;
  }

  private async watch(jobId: string): Promise<void> {
    while (!this.stopped) {
      await new Promise((resolve) => setTimeout(resolve, this.pollMs));
      if (this.stopped) return;
      try {
        this.job.set(await firstValueFrom(this.api.job(this.slug, jobId)));
      } catch (err) {
        this.error.set(toWorldError(err).message);
        return;
      }
      if (!isActive(this.run()?.status)) {
        this.finished();
        return;
      }
    }
  }
}
