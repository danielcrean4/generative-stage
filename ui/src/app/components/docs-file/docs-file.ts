import { Component, DestroyRef, ViewChild, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import {
  catchError,
  combineLatest,
  distinctUntilChanged,
  forkJoin,
  map,
  of,
  switchMap,
  tap,
} from 'rxjs';
import { DocFile, DocsViewApi } from '../../docs-view-api';
import { OutlineEntry } from '../../docs-dom';
import { findDocFile } from '../../docs-tree';
import { formatSize, formatTime } from '../../run-view-format';
import { DocsBody } from '../docs-body/docs-body';
import { RunViewProblem } from '../run-view-problem/run-view-problem';

/** One rendered doc: breadcrumb, file facts, the text, and an outline of its headings. */
@Component({
  imports: [RouterLink, DocsBody, RunViewProblem],
  selector: 'app-docs-file',
  styleUrl: './docs-file.scss',
  templateUrl: './docs-file.html',
})
export class DocsFile {
  private readonly api = inject(DocsViewApi);
  private readonly route = inject(ActivatedRoute);
  private readonly destroyRef = inject(DestroyRef);

  @ViewChild(DocsBody) private body?: DocsBody;

  readonly project = signal('');
  readonly path = signal('');
  readonly loading = signal(true);
  readonly error = signal<unknown>(null);
  readonly doc = signal<DocFile | null>(null);
  readonly modified = signal<string | null>(null);
  readonly projectName = signal('');
  readonly outline = signal<OutlineEntry[]>([]);

  readonly fragment = toSignal(this.route.fragment, { initialValue: null });
  readonly line = toSignal(
    this.route.queryParamMap.pipe(
      map((q) => (Number(q.get('line')) > 0 ? Number(q.get('line')) : null)),
    ),
    { initialValue: null },
  );

  readonly folders = computed(() => this.path().split('/').slice(0, -1));

  readonly formatTime = formatTime;
  readonly formatSize = formatSize;

  constructor() {
    const key = combineLatest([this.route.paramMap, this.route.queryParamMap]).pipe(
      map(([p, q]) => ({ project: p.get('project') ?? '', path: q.get('path') ?? '' })),
      distinctUntilChanged((a, b) => a.project === b.project && a.path === b.path),
    );
    key
      .pipe(
        tap(({ project, path }) => {
          this.project.set(project);
          this.projectName.set(project);
          this.path.set(path);
          this.loading.set(true);
          this.error.set(null);
          this.doc.set(null);
          this.outline.set([]);
        }),
        switchMap(({ project, path }) => {
          if (!path)
            return of({
              doc: null as DocFile | null,
              err: new Error('No doc path in the address.') as unknown,
            });
          return this.api.file(project, path).pipe(
            map((doc) => ({ doc: doc as DocFile | null, err: null as unknown })),
            catchError((err: unknown) => of({ doc: null as DocFile | null, err })),
          );
        }),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe(({ doc, err }) => {
        this.doc.set(doc);
        this.error.set(err);
        this.loading.set(false);
        if (doc) this.fillFacts(doc);
      });
  }

  /** The project's display name, and the modified time when the file answer lacks it. */
  private fillFacts(doc: DocFile): void {
    this.modified.set(doc.modified ?? null);
    const project = this.project();
    forkJoin({
      projects: this.api.projects().pipe(catchError(() => of(null))),
      tree: doc.modified ? of(null) : this.api.tree(project).pipe(catchError(() => of(null))),
    })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(({ projects, tree }) => {
        const name = projects?.projects.find((p) => p.slug === project)?.name;
        if (name) this.projectName.set(name);
        const node = tree ? findDocFile(tree.tree, doc.path) : null;
        if (node) this.modified.set(node.modified);
      });
  }

  goTo(event: Event, entry: OutlineEntry): void {
    event.preventDefault();
    this.body?.goToAnchor(entry.id);
  }
}
