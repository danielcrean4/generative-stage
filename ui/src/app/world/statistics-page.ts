import { Component, computed, effect, inject, signal, untracked } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { barPercent, busiestDay, duration, longestStage, shortDay } from './statistics-model';
import { toWorldError, WorldApi } from './world-api';
import { WorldGate } from './world-gate';
import { Statistics } from './world-models';
import { WorldProjectService } from './world-project.service';

/** Every word on this screen. */
const WORDS = {
  title: 'Statistics',
  intro: 'Figures from the runs of this project, read from the run files. A run here is one attempt of a pipeline.',
  loading: 'Loading…',
  loadFailed: 'Could not read the statistics:',
  empty: 'No runs yet. Attach a run to something in this project and its figures appear here.',
  runs: 'Runs',
  completed: 'Completed',
  errored: 'Errored',
  other: 'Still running or no record',
  assets: 'Assets made',
  candidates: 'Candidates made',
  choices: 'Choices made',
  chosenNow: 'Chosen now',
  withChoice: (n: number, total: number) => `${n} of ${total} have a choice`,
  total: 'Total time',
  overTime: 'Runs over time',
  overTimeHelp: 'Runs started each day (UTC).',
  split: 'Completed against errored',
  perStage: 'Time per stage',
  perStageHelp: 'Total time in each stage across all runs. Stages reused from an earlier run take no time and are counted apart.',
  stage: 'Stage',
  ran: 'Ran',
  reused: 'Reused',
  errors: 'Errored',
  average: 'Average',
  slowest: 'Slowest',
  day: 'Day',
  asTable: 'Show the numbers',
  dayLabel: (day: string, c: number, e: number, o: number) => `${day}: ${c} completed, ${e} errored${o ? `, ${o} other` : ''}`,
};

/**
 * The project's run figures: runs over time, completed against errored, time per stage and the
 * assets made. The charts are plain bars with the numbers written beside them and a table of the
 * same numbers under each, so nothing depends on colour.
 */
@Component({
  selector: 'app-statistics-page',
  imports: [WorldGate],
  templateUrl: './statistics-page.html',
  styleUrl: './statistics-page.scss',
})
export class StatisticsPage {
  readonly w = WORDS;
  readonly world = inject(WorldProjectService);
  private readonly api = inject(WorldApi);

  readonly stats = signal<Statistics | null>(null);
  readonly error = signal<string | null>(null);
  readonly loading = signal(false);

  constructor() {
    effect(() => {
      const slug = this.world.slug();
      untracked(() => {
        this.stats.set(null);
        if (slug) void this.load(slug);
      });
    });
  }

  private async load(slug: string): Promise<void> {
    this.loading.set(true);
    this.error.set(null);
    try {
      this.stats.set(await firstValueFrom(this.api.statistics(slug)));
    } catch (err) {
      this.error.set(toWorldError(err).message);
    }
    this.loading.set(false);
  }

  readonly busiest = computed(() => (this.stats() ? busiestDay(this.stats()!) : 0));
  readonly longest = computed(() => (this.stats() ? longestStage(this.stats()!) : 0));

  readonly percent = barPercent;
  readonly day = shortDay;
  readonly time = duration;
}
