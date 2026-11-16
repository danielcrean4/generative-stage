import { Component, computed, effect, inject, signal, untracked } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { MatButtonModule } from '@angular/material/button';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { firstValueFrom, map } from 'rxjs';
import { formBadge } from './kind-families';
import { toWorldError, WorldApi } from './world-api';
import { excerpt, formatTime } from './world-format';
import { Entity, Kind } from './world-models';
import { WorldGate } from './world-gate';
import { WorldProjectService } from './world-project.service';

/** Every word on this screen. */
const WORDS = {
  notFound: 'This project has no kind with that name.',
  batch: 'Make a batch',
  create: (kind: string) => `New ${kind.toLowerCase()}`,
  about: 'About this kind',
  searchLabel: 'Search',
  searchHint: 'Title, brief or tag',
  tagLabel: 'Tag',
  anyTag: 'Any tag',
  archivedToggle: 'Show archived',
  loading: 'Loading…',
  emptyTitle: (plural: string) => `No ${plural.toLowerCase()} yet.`,
  emptyHelp: (label: string, what: string) =>
    `${what ? what + ' ' : ''}Each ${label.toLowerCase()} gets a title, a brief and any other fields this kind has, and can be linked to the other things in your world.`,
  noMatch: 'Nothing matches. Clear the search or the tag.',
  colUpdated: 'Updated',
  archivedBadge: 'Archived',
  noBrief: 'No brief yet.',
  archive: 'Archive',
  restore: 'Restore',
  changedUnderneath: (label: string) => `That ${label.toLowerCase()} was changed by someone else just now. The list has been reloaded; try again.`,
};

@Component({
  selector: 'app-entity-list-page',
  imports: [RouterLink, WorldGate, MatButtonModule, MatCheckboxModule, MatFormFieldModule, MatInputModule],
  styleUrl: './world-pages.scss',
  templateUrl: './entity-list-page.html',
  styles: `
    .filters { display: flex; gap: 1rem; align-items: center; flex-wrap: wrap; }
    .filters mat-form-field { width: 16rem; }
    .row-title { font-weight: 600; font-size: 1.05rem; color: inherit; }
    .excerpt { margin: 0; color: var(--mat-sys-on-surface-variant); }
    .tags { display: flex; gap: 0.35rem; flex-wrap: wrap; margin-top: 0.2rem; }
    .tag { font-size: 0.75rem; padding: 0 0.5rem; border-radius: 999px; border: 1px solid var(--mat-sys-outline-variant); background: transparent; color: inherit; cursor: pointer; }
    .archived-card { opacity: 0.7; }
    select { font: inherit; }
  `,
})
export class EntityListPage {
  readonly w = WORDS;
  readonly formBadge = formBadge;
  readonly world = inject(WorldProjectService);
  private readonly api = inject(WorldApi);
  private readonly route = inject(ActivatedRoute);
  private readonly kindId = toSignal(this.route.paramMap.pipe(map((p) => p.get('kind'))), { initialValue: null });

  readonly kind = computed<Kind | null>(() => this.world.kind(this.kindId()));
  readonly what = computed(() => {
    const d = this.kind()?.schema['description'];
    return typeof d === 'string' ? d : '';
  });

  readonly search = signal('');
  readonly tag = signal('');
  readonly showArchived = signal(false);

  readonly everything = signal<Entity[] | null>(null);
  readonly shown = signal<Entity[] | null>(null);
  readonly error = signal<string | null>(null);
  readonly notice = signal<string | null>(null);

  readonly tags = computed(() => {
    const field = this.kind()?.tags_field;
    if (!field) return [];
    const all = new Set<string>();
    for (const e of this.everything() ?? []) {
      const t = e.data[field];
      if (Array.isArray(t)) t.forEach((x) => all.add(String(x)));
    }
    return [...all].sort((a, b) => a.localeCompare(b));
  });

  private debounced = signal('');
  private timer: ReturnType<typeof setTimeout> | null = null;
  private requestId = 0;

  constructor() {
    // A different kind or project starts the page afresh.
    effect(() => {
      this.kindId();
      this.world.slug();
      untracked(() => {
        this.search.set('');
        this.debounced.set('');
        this.tag.set('');
        this.showArchived.set(false);
        this.everything.set(null);
        this.shown.set(null);
        this.notice.set(null);
      });
    });
    effect(() => {
      const kind = this.kind();
      const slug = this.world.slug();
      const q = this.debounced();
      const tag = this.tag();
      const archived = this.showArchived();
      if (kind && slug) void this.reload(slug, kind.id, q, tag, archived);
    });
  }

  setSearch(text: string): void {
    this.search.set(text);
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(() => this.debounced.set(text.trim()), 200);
  }

  setTag(value: string): void {
    this.tag.set(value);
  }

  private async reload(slug: string, kind: string, q: string, tag: string, archived: boolean): Promise<void> {
    const id = ++this.requestId;
    this.error.set(null);
    try {
      // The unfiltered list is what the tag choices and the empty state are worked out from.
      const everything = await firstValueFrom(this.api.entities(slug, { kind, include_archived: archived }));
      const filtered = q || tag ? await firstValueFrom(this.api.entities(slug, { kind, q, tag, include_archived: archived })) : everything;
      if (id !== this.requestId) return;
      this.everything.set(everything);
      this.shown.set(filtered);
    } catch (err) {
      if (id !== this.requestId) return;
      this.error.set(toWorldError(err).message);
    }
  }

  brief(e: Entity): string {
    const field = this.kind()?.brief_field;
    return excerpt(field ? e.data[field] : '');
  }

  entityTags(e: Entity): string[] {
    const field = this.kind()?.tags_field;
    const t = field ? e.data[field] : null;
    return Array.isArray(t) ? t.map(String) : [];
  }

  when(e: Entity): string {
    return formatTime(e.updated_at);
  }

  async toggleArchive(e: Entity): Promise<void> {
    const slug = this.world.slug();
    const kind = this.kind();
    if (!slug || !kind) return;
    this.notice.set(null);
    try {
      await firstValueFrom(e.archived ? this.api.restoreEntity(slug, e.id, e.revision) : this.api.archiveEntity(slug, e.id, e.revision));
    } catch (err) {
      const error = toWorldError(err);
      this.notice.set(error.isConflict ? WORDS.changedUnderneath(kind.label) : error.message);
    }
    await this.reload(slug, kind.id, this.debounced(), this.tag(), this.showArchived());
    void this.world.refreshCounts();
  }
}
