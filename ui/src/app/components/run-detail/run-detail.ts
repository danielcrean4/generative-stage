import { Component, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { switchMap, tap } from 'rxjs';
import { RunDetailResponse, RunViewApi } from '../../run-view-api';
import { formatDuration, formatSize, formatTime } from '../../run-view-format';
import { RunViewProblem } from '../run-view-problem/run-view-problem';

@Component({
  imports: [RouterLink, RunViewProblem],
  selector: 'app-run-detail',
  styleUrl: './run-detail.scss',
  templateUrl: './run-detail.html',
})
export class RunDetail {
  private readonly api = inject(RunViewApi);
  private readonly route = inject(ActivatedRoute);
  private readonly destroyRef = inject(DestroyRef);

  readonly runId = signal('');
  readonly loading = signal(true);
  readonly error = signal<unknown>(null);
  readonly run = signal<RunDetailResponse | null>(null);

  readonly formatTime = formatTime;
  readonly formatDuration = formatDuration;
  readonly formatSize = formatSize;

  constructor() {
    this.route.paramMap
      .pipe(
        tap((params) => {
          this.runId.set(params.get('runId') ?? '');
          this.loading.set(true);
          this.error.set(null);
          this.run.set(null);
        }),
        switchMap((params) => this.api.run(params.get('runId') ?? '')),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({ next: (r) => this.done(r, null), error: (e) => this.done(null, e) });
  }

  private done(run: RunDetailResponse | null, err: unknown): void {
    this.run.set(run);
    this.error.set(err);
    this.loading.set(false);
  }

  isImage(mediaType: string): boolean {
    return mediaType.startsWith('image/');
  }
}
