import { Component, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { switchMap, tap } from 'rxjs';
import { AttemptDetail, RunViewApi } from '../../run-view-api';
import { formatDuration, formatTime, recipeRows } from '../../run-view-format';
import { RunViewProblem } from '../run-view-problem/run-view-problem';
import { StagePanel } from '../stage-panel/stage-panel';

@Component({
  imports: [RouterLink, RunViewProblem, StagePanel],
  selector: 'app-attempt-view',
  styleUrl: './attempt-view.scss',
  templateUrl: './attempt-view.html',
})
export class AttemptView {
  private readonly api = inject(RunViewApi);
  private readonly route = inject(ActivatedRoute);
  private readonly destroyRef = inject(DestroyRef);

  readonly runId = signal('');
  readonly attemptId = signal('');
  readonly loading = signal(true);
  readonly error = signal<unknown>(null);
  readonly attempt = signal<AttemptDetail | null>(null);

  readonly formatTime = formatTime;
  readonly formatDuration = formatDuration;
  readonly recipeRows = recipeRows;

  constructor() {
    this.route.paramMap
      .pipe(
        tap((params) => {
          this.runId.set(params.get('runId') ?? '');
          this.attemptId.set(params.get('attemptId') ?? '');
          this.loading.set(true);
          this.error.set(null);
          this.attempt.set(null);
        }),
        switchMap((params) => this.api.attempt(params.get('runId') ?? '', params.get('attemptId') ?? '')),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({ next: (a) => this.done(a, null), error: (e) => this.done(null, e) });
  }

  private done(attempt: AttemptDetail | null, err: unknown): void {
    this.attempt.set(attempt);
    this.error.set(err);
    this.loading.set(false);
  }
}
