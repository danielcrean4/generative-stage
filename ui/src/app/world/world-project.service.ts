import { DOCUMENT } from '@angular/common';
import { Injectable, computed, inject, signal } from '@angular/core';
import { NavigationStart, Router } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { PROJECT_KEY } from '../brand';
import { groupByFamily } from './kind-families';
import { WorldApi, toWorldError } from './world-api';
import { Kind, LinkType, WorldApiError, WorldProject } from './world-models';

/** Route that renders nothing. A switch passes through it so every page is destroyed before the
 * project changes and rebuilt after, which keeps one project's entities off another's page. */
export const SWITCHING_ROUTE = 'switching';

export type CatalogStatus = 'idle' | 'loading' | 'ready' | 'error';

/**
 * Which world-model project is current, and what it offers (kinds, link types, entity counts).
 * The project goes in the path of every call, so there is no header to forget.
 */
@Injectable({ providedIn: 'root' })
export class WorldProjectService {
  private readonly api = inject(WorldApi);
  private readonly router = inject(Router);
  private readonly document = inject(DOCUMENT);

  readonly projects = signal<WorldProject[]>([]);
  readonly listStatus = signal<'loading' | 'ready' | 'error'>('loading');
  readonly listError = signal<WorldApiError | null>(null);
  /** The slug of the current project, or null when there is none. */
  readonly slug = signal<string | null>(null);

  readonly kinds = signal<Kind[]>([]);
  /** The kinds grouped by family (Props, Characters, Settings, Scripts, Stages, then Other). */
  readonly kindGroups = computed(() => groupByFamily(this.kinds()));
  readonly linkTypes = signal<LinkType[]>([]);
  readonly counts = signal<Record<string, number>>({});
  readonly catalogStatus = signal<CatalogStatus>('idle');
  /** Why the kinds could not be read (a wrong schema file, for example), word for word from the API. */
  readonly catalogError = signal<WorldApiError | null>(null);

  readonly current = computed(() => this.projects().find((p) => p.slug === this.slug()) ?? null);
  readonly currentName = computed(() => this.current()?.name ?? this.slug());
  readonly usable = computed(() => this.projects().filter((p) => !p.problem));

  private loadToken = 0;
  /** How many navigations have started; a switch uses it to see whether the person went elsewhere meanwhile. */
  private navigationStarts = 0;

  constructor() {
    this.router.events.subscribe((event) => {
      if (event instanceof NavigationStart) this.navigationStarts++;
    });
  }

  kind(id: string | null | undefined): Kind | null {
    return this.kinds().find((k) => k.id === id) ?? null;
  }

  linkType(id: string): LinkType | null {
    return this.linkTypes().find((t) => t.id === id) ?? null;
  }

  /** Read the registry, pick the remembered project (or the first that loads), and read its kinds. */
  async load(): Promise<void> {
    this.listStatus.set('loading');
    this.listError.set(null);
    try {
      const projects = await firstValueFrom(this.api.projects());
      this.projects.set(projects);
      this.listStatus.set('ready');
      const loadable = projects.filter((p) => !p.problem);
      const remembered = this.remembered();
      const pick = loadable.find((p) => p.slug === remembered) ?? loadable[0] ?? null;
      this.slug.set(pick?.slug ?? null);
      await this.loadCatalog();
    } catch (err) {
      this.listError.set(toWorldError(err));
      this.listStatus.set('error');
    }
  }

  /** Re-read the registry after a create, open or remove, without changing the current project. */
  async refreshProjects(): Promise<void> {
    const projects = await firstValueFrom(this.api.projects());
    this.projects.set(projects);
    if (this.slug() && !projects.some((p) => p.slug === this.slug())) {
      this.slug.set(null);
      this.resetCatalog();
    }
  }

  async loadCatalog(): Promise<void> {
    const slug = this.slug();
    const token = ++this.loadToken;
    if (!slug) {
      this.resetCatalog();
      return;
    }
    this.catalogStatus.set('loading');
    this.catalogError.set(null);
    try {
      const [kinds, linkTypes] = await Promise.all([firstValueFrom(this.api.kinds(slug)), firstValueFrom(this.api.linkTypes(slug))]);
      if (token !== this.loadToken) return;
      this.kinds.set(kinds);
      this.linkTypes.set(linkTypes);
      this.catalogStatus.set('ready');
      await this.refreshCounts();
    } catch (err) {
      if (token !== this.loadToken) return;
      this.kinds.set([]);
      this.linkTypes.set([]);
      this.counts.set({});
      this.catalogError.set(toWorldError(err));
      this.catalogStatus.set('error');
    }
  }

  /** The API has no per-kind count, so it is worked out from one list of the live entities. */
  async refreshCounts(): Promise<void> {
    const slug = this.slug();
    if (!slug) return;
    try {
      const entities = await firstValueFrom(this.api.entities(slug));
      if (slug !== this.slug()) return;
      const counts: Record<string, number> = {};
      for (const e of entities) counts[e.kind] = (counts[e.kind] ?? 0) + 1;
      this.counts.set(counts);
    } catch {
      // A count that cannot be read is simply not shown; the lists have their own errors.
    }
  }

  private resetCatalog(): void {
    this.kinds.set([]);
    this.linkTypes.set([]);
    this.counts.set({});
    this.catalogError.set(null);
    this.catalogStatus.set('idle');
  }

  /**
   * Make a project current. Like the older project switch, the page is left first (a blank route),
   * so no page ever shows one project's entities under another's name. Resolves false when a page
   * refused to be left (unsaved changes) and nothing changed.
   */
  async select(slug: string, goTo: string | null = '/projects'): Promise<boolean> {
    if (slug === this.slug() && this.catalogStatus() === 'ready') {
      return true;
    }
    const left = await this.router.navigateByUrl(`/${SWITCHING_ROUTE}`, { skipLocationChange: true });
    if (!left) return false;
    const started = this.navigationStarts;
    this.slug.set(slug);
    this.remember(slug);
    await this.loadCatalog();
    // Loading takes a moment. If the person already went to another page, leave them there.
    if (goTo && this.navigationStarts === started) await this.router.navigateByUrl(goTo, { replaceUrl: true });
    return true;
  }

  async create(body: { folder: string; slug: string; name: string }): Promise<WorldProject> {
    const project = await firstValueFrom(this.api.createProject(body));
    await this.refreshProjects();
    await this.select(project.slug);
    return project;
  }

  async open(projectFile: string): Promise<WorldProject> {
    const project = await firstValueFrom(this.api.openProject(projectFile));
    await this.refreshProjects();
    await this.select(project.slug);
    return project;
  }

  /** Unregister only: the API never touches the folder. */
  async remove(slug: string): Promise<void> {
    await firstValueFrom(this.api.removeProject(slug));
    const wasCurrent = slug === this.slug();
    await this.refreshProjects();
    if (wasCurrent) {
      const next = this.usable()[0];
      if (next) await this.select(next.slug);
    }
  }

  /** One key per address, so two installs on different ports remember their own project. */
  private storageKey(): string {
    return `${PROJECT_KEY}@${this.document.location.origin}`;
  }

  /** The remembered slug, or null. */
  private remembered(): string | null {
    try {
      return this.document.defaultView?.localStorage.getItem(this.storageKey()) ?? null;
    } catch {
      return null;
    }
  }

  private remember(slug: string): void {
    try {
      this.document.defaultView?.localStorage.setItem(this.storageKey(), slug);
    } catch {
      // Storage blocked: the choice just does not survive a reload.
    }
  }
}
