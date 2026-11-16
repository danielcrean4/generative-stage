import { Component, DestroyRef, computed, inject, input, signal } from '@angular/core';
import { takeUntilDestroyed, toObservable } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import {
  Observable,
  catchError,
  combineLatest,
  debounce,
  distinctUntilChanged,
  map,
  of,
  startWith,
  switchMap,
  tap,
  timer,
} from 'rxjs';
import { DocsViewApi, SearchResponse } from '../../docs-view-api';
import { RunViewProblem } from '../run-view-problem/run-view-problem';

export const SEARCH_DEBOUNCE_MS = 300;

export interface TextPart {
  text: string;
  hit: boolean;
}

/** Splits an excerpt so every case-insensitive occurrence of the query can be marked. */
export function markParts(excerpt: string, query: string): TextPart[] {
  const q = query.trim().toLowerCase();
  if (!q) return [{ text: excerpt, hit: false }];
  const parts: TextPart[] = [];
  const lower = excerpt.toLowerCase();
  let at = 0;
  for (;;) {
    const i = lower.indexOf(q, at);
    if (i < 0) break;
    if (i > at) parts.push({ text: excerpt.slice(at, i), hit: false });
    parts.push({ text: excerpt.slice(i, i + q.length), hit: true });
    at = i + q.length;
  }
  if (at < excerpt.length) parts.push({ text: excerpt.slice(at), hit: false });
  return parts;
}

type SearchState =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'done'; query: string; response: SearchResponse }
  | { kind: 'error'; error: unknown };

/** Search box, "all projects" switch and the results. The query and switch live in the URL. */
@Component({
  imports: [RouterLink, RunViewProblem],
  selector: 'app-docs-search',
  styleUrl: './docs-search.scss',
  templateUrl: './docs-search.html',
})
export class DocsSearch {
  private readonly api = inject(DocsViewApi);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);

  /** The chosen project; empty on the project picker page, where only "all projects" makes sense. */
  readonly project = input('');

  readonly term = signal(this.route.snapshot.queryParamMap.get('q') ?? '');
  private readonly allChosen = signal(this.route.snapshot.queryParamMap.get('all') === '1');
  readonly all = computed(() => this.allChosen() || !this.project());
  readonly state = signal<SearchState>({ kind: 'idle' });

  readonly markParts = markParts;

  constructor() {
    let first = true;
    combineLatest([toObservable(this.term), toObservable(this.all), toObservable(this.project)])
      .pipe(
        // The first value (a deep link) goes straight out; typing waits for a pause.
        debounce(() => {
          const wait = first ? 0 : SEARCH_DEBOUNCE_MS;
          first = false;
          return timer(wait);
        }),
        map(([term, all, project]) => ({ q: term.trim(), all, project })),
        distinctUntilChanged((a, b) => a.q === b.q && a.all === b.all && a.project === b.project),
        tap((req) => this.syncUrl(req.q, req.all)),
        switchMap((req) => this.run(req)),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((state) => this.state.set(state));
  }

  setAll(value: boolean): void {
    this.allChosen.set(value);
  }

  private run(req: { q: string; all: boolean; project: string }): Observable<SearchState> {
    if (!req.q) return of<SearchState>({ kind: 'idle' });
    const call = req.all ? this.api.searchAll(req.q) : this.api.search(req.project, req.q);
    return call.pipe(
      map((response): SearchState => ({ kind: 'done', query: req.q, response })),
      catchError((error: unknown) => of<SearchState>({ kind: 'error', error })),
      startWith<SearchState>({ kind: 'loading' }),
    );
  }

  private syncUrl(q: string, all: boolean): void {
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { q: q || null, all: all && this.project() ? 1 : null },
      queryParamsHandling: 'merge',
      replaceUrl: true,
    });
  }
}
