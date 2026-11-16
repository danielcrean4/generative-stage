import { Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed, toObservable, toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { catchError, map, of, switchMap, tap } from 'rxjs';
import { DocsProject, DocsTreeResponse, DocsViewApi } from '../../docs-view-api';
import { DocsSearch } from '../docs-search/docs-search';
import { DocsTree } from '../docs-tree/docs-tree';
import { RunViewProblem } from '../run-view-problem/run-view-problem';

/** The docs entry page: pick a project, search, or browse that project's docs tree. */
@Component({
  imports: [RouterLink, DocsSearch, DocsTree, RunViewProblem],
  selector: 'app-docs-home',
  styleUrl: './docs-home.scss',
  templateUrl: './docs-home.html',
})
export class DocsHome {
  private readonly api = inject(DocsViewApi);
  private readonly route = inject(ActivatedRoute);
  private readonly destroyRef = inject(DestroyRef);

  readonly project = toSignal(this.route.paramMap.pipe(map((p) => p.get('project') ?? '')), {
    initialValue: '',
  });
  /** True while a search term is in the URL: the results take the place of the tree. */
  readonly searching = toSignal(this.route.queryParamMap.pipe(map((q) => !!q.get('q')?.trim())), {
    initialValue: false,
  });

  readonly projectsLoading = signal(true);
  readonly projectsError = signal<unknown>(null);
  readonly projects = signal<DocsProject[]>([]);

  readonly treeLoading = signal(false);
  readonly treeError = signal<unknown>(null);
  readonly tree = signal<DocsTreeResponse | null>(null);

  readonly chosen = computed(() => this.projects().find((p) => p.slug === this.project()) ?? null);

  constructor() {
    this.loadProjects();
    toObservable(this.project)
      .pipe(
        tap(() => {
          this.tree.set(null);
          this.treeError.set(null);
          this.treeLoading.set(true);
        }),
        switchMap((slug) =>
          slug
            ? this.api.tree(slug).pipe(
                map((tree) => ({ tree: tree as DocsTreeResponse | null, err: null as unknown })),
                catchError((err: unknown) => of({ tree: null as DocsTreeResponse | null, err })),
              )
            : of({ tree: null as DocsTreeResponse | null, err: null as unknown }),
        ),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe(({ tree, err }) => {
        this.tree.set(tree);
        this.treeError.set(err);
        this.treeLoading.set(false);
      });
  }

  loadProjects(): void {
    this.projectsLoading.set(true);
    this.projectsError.set(null);
    this.api
      .projects()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          this.projects.set(res.projects);
          this.projectsLoading.set(false);
        },
        error: (err) => {
          this.projectsError.set(err);
          this.projectsLoading.set(false);
        },
      });
  }
}
