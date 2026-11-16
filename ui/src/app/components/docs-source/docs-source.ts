import { Component, DestroyRef, Injector, afterNextRender, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { catchError, combineLatest, distinctUntilChanged, map, of, switchMap, tap } from 'rxjs';
import { DocsViewApi, SourceWindow } from '../../docs-view-api';
import { SOURCE_BLOCKED_NOTE } from '../../docs-markdown';
import { RunViewProblem } from '../run-view-problem/run-view-problem';
import { HttpErrorResponse } from '@angular/common/http';

interface Row {
  n: number;
  text: string;
  target: boolean;
}

/** A read-only window onto one source file a doc links to, with line numbers. */
@Component({
  imports: [RouterLink, RunViewProblem],
  selector: 'app-docs-source',
  styleUrl: './docs-source.scss',
  templateUrl: './docs-source.html',
})
export class DocsSource {
  private readonly api = inject(DocsViewApi);
  private readonly route = inject(ActivatedRoute);
  private readonly destroyRef = inject(DestroyRef);
  private readonly injector = inject(Injector);

  readonly project = signal('');
  readonly path = signal('');
  readonly line = signal<number | null>(null);
  readonly loading = signal(false);
  readonly error = signal<unknown>(null);
  /** True when the file is outside the allowlist (the doc link said so, or the server refused it). */
  readonly blocked = signal(false);
  readonly window = signal<SourceWindow | null>(null);

  readonly note = SOURCE_BLOCKED_NOTE;

  readonly rows = computed<Row[]>(() => {
    const w = this.window();
    if (!w) return [];
    return w.lines.map((text, i) => ({
      n: w.start + i,
      text,
      target: w.start + i === this.line(),
    }));
  });

  constructor() {
    combineLatest([this.route.paramMap, this.route.queryParamMap])
      .pipe(
        map(([p, q]) => ({
          project: p.get('project') ?? '',
          path: q.get('path') ?? '',
          line: Number(q.get('line')) > 0 ? Number(q.get('line')) : null,
          blocked: q.get('blocked') === '1',
        })),
        distinctUntilChanged((a, b) => JSON.stringify(a) === JSON.stringify(b)),
        tap((r) => {
          this.project.set(r.project);
          this.path.set(r.path);
          this.line.set(r.line);
          this.error.set(null);
          this.window.set(null);
          this.blocked.set(r.blocked);
          this.loading.set(!r.blocked && !!r.path);
        }),
        switchMap((r) => {
          if (r.blocked || !r.path) return of(null);
          return this.api.source(r.project, r.path, r.line).pipe(
            map((window) => ({ window })),
            catchError((error: unknown) => of({ error })),
          );
        }),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((res) => {
        this.loading.set(false);
        if (!res) return;
        if ('window' in res) {
          this.window.set(res.window);
          afterNextRender(() => this.scrollToTarget(), { injector: this.injector });
        } else if (res.error instanceof HttpErrorResponse && res.error.status === 404) {
          // The server answers 404 for a missing file and for one outside the allowlist alike.
          this.blocked.set(true);
        } else {
          this.error.set(res.error);
        }
      });
  }

  private scrollToTarget(): void {
    document.getElementById('ws-source-target')?.scrollIntoView?.({ block: 'center' });
  }
}
