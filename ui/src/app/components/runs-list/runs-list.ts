import { Component, DestroyRef, inject, signal, computed } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { RunSummary, RunViewApi } from '../../run-view-api';
import { formatDuration, formatTime } from '../../run-view-format';
import { RunViewProblem } from '../run-view-problem/run-view-problem';

export const RUN_LIMITS = [25, 50, 100, 250, 500];

@Component({
  imports: [RouterLink, RunViewProblem],
  selector: 'app-runs-list',
  styleUrl: './runs-list.scss',
  templateUrl: './runs-list.html',
})
export class RunsList {
  private readonly api = inject(RunViewApi);
  private readonly destroyRef = inject(DestroyRef);

  readonly limits = RUN_LIMITS;
  readonly limit = signal(50);
  readonly filter = signal('');
  readonly loading = signal(true);
  readonly error = signal<unknown>(null);
  readonly runs = signal<RunSummary[]>([]);
  readonly total = signal(0);

  readonly visible = computed(() => {
    const needle = this.filter().trim().toLowerCase();
    return needle ? this.runs().filter((r) => r.run_id.toLowerCase().includes(needle)) : this.runs();
  });

  readonly formatTime = formatTime;
  readonly formatDuration = formatDuration;

  constructor() {
    this.load();
  }

  setLimit(value: string): void {
    this.limit.set(Number(value));
    this.load();
  }

  load(): void {
    this.loading.set(true);
    this.error.set(null);
    this.api
      .runs(this.limit())
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          this.runs.set(res.runs);
          this.total.set(res.total);
          this.loading.set(false);
        },
        error: (err) => {
          this.error.set(err);
          this.loading.set(false);
        },
      });
  }
}
