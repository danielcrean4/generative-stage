import { Component, computed, effect, inject, input, output, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { RouterLink } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { toWorldError, WorldApi } from './world-api';
import { Entity, EntityLink } from './world-models';
import { WorldProjectService } from './world-project.service';

/** Every word in this panel. */
const WORDS = {
  title: 'Links',
  loading: 'Loading…',
  none: 'Nothing is linked yet.',
  locked: 'This is archived. Restore it to change its links.',
  remove: 'Remove link',
  add: 'Add a link',
  typeLabel: 'Link type',
  chooseType: 'Choose a type…',
  searchLabel: 'Find something to link to',
  searchHint: 'Search by title, brief or tag',
  noResults: 'Nothing found.',
  pick: 'Link',
  cancel: 'Cancel',
  noTypes: 'No link types connect this kind to anything.',
  typeOption: (label: string, kinds: string) => `${label} (${kinds})`,
};

interface Option {
  key: string;
  typeId: string;
  direction: 'out' | 'in';
  label: string;
  otherKinds: string[];
}

interface Group {
  key: string;
  label: string;
  links: EntityLink[];
}

@Component({
  selector: 'app-links-panel',
  imports: [RouterLink, MatButtonModule, MatFormFieldModule, MatInputModule],
  styleUrl: './world-pages.scss',
  templateUrl: './links-panel.html',
  styles: `
    .group h4 { margin: 0.5rem 0 0.2rem; font-weight: 500; color: var(--mat-sys-on-surface-variant); }
    .links { list-style: none; margin: 0; padding: 0; }
    .link { display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; padding: 0.15rem 0; }
    .kind-chip { font-size: 0.75rem; opacity: 0.7; margin-left: 0.4rem; }
    .results { list-style: none; margin: 0.25rem 0; padding: 0; max-height: 14rem; overflow: auto; }
    .result { display: flex; align-items: center; justify-content: space-between; padding: 0.1rem 0; }
    .adder { margin-top: 0.75rem; display: flex; flex-direction: column; gap: 0.25rem; }
    select { font: inherit; }
  `,
})
export class LinksPanel {
  readonly w = WORDS;
  private readonly api = inject(WorldApi);
  readonly world = inject(WorldProjectService);

  readonly slug = input.required<string>();
  readonly entity = input.required<Entity>();
  /** Fired after a link is added or removed so the page can refresh anything that shows links. */
  readonly changed = output<void>();

  readonly links = signal<EntityLink[] | null>(null);
  readonly error = signal<string | null>(null);
  readonly adding = signal(false);
  readonly optionKey = signal('');
  readonly search = signal('');
  readonly results = signal<Entity[] | null>(null);
  readonly addError = signal<string | null>(null);
  private timer: ReturnType<typeof setTimeout> | null = null;
  private searchId = 0;

  readonly locked = computed(() => this.entity().archived);

  readonly groups = computed<Group[]>(() => {
    const groups = new Map<string, Group>();
    const ordered = [...(this.links() ?? [])].sort((a, b) => (a.direction === b.direction ? 0 : a.direction === 'out' ? -1 : 1));
    for (const link of ordered) {
      const key = `${link.type}|${link.direction}`;
      const group = groups.get(key) ?? { key, label: link.label, links: [] };
      group.links.push(link);
      groups.set(key, group);
    }
    return [...groups.values()];
  });

  /** The link types that apply to this kind, in each direction it can take part in. */
  readonly options = computed<Option[]>(() => {
    const kind = this.entity().kind;
    const names = (ids: string[]) => ids.map((id) => this.world.kind(id)?.plural_label ?? id).join(', ');
    const out: Option[] = [];
    for (const t of this.world.linkTypes()) {
      if (t.source_kinds.includes(kind)) {
        out.push({ key: `${t.id}|out`, typeId: t.id, direction: 'out', label: WORDS.typeOption(t.label, names(t.target_kinds)), otherKinds: t.target_kinds });
      }
      if (t.target_kinds.includes(kind)) {
        out.push({ key: `${t.id}|in`, typeId: t.id, direction: 'in', label: WORDS.typeOption(t.inverse_label, names(t.source_kinds)), otherKinds: t.source_kinds });
      }
    }
    return out;
  });

  readonly option = computed(() => this.options().find((o) => o.key === this.optionKey()) ?? null);

  constructor() {
    effect(() => {
      const slug = this.slug();
      const id = this.entity().id;
      this.entity().revision;
      void this.load(slug, id);
    });
  }

  kindLabel(id: string): string {
    return this.world.kind(id)?.label ?? id;
  }

  private async load(slug: string, id: string): Promise<void> {
    this.error.set(null);
    try {
      this.links.set(await firstValueFrom(this.api.links(slug, id)));
    } catch (err) {
      this.error.set(toWorldError(err).message);
    }
  }

  startAdding(): void {
    this.adding.set(true);
    this.optionKey.set('');
    this.search.set('');
    this.results.set(null);
    this.addError.set(null);
  }

  stopAdding(): void {
    this.adding.set(false);
  }

  chooseOption(key: string): void {
    this.optionKey.set(key);
    this.results.set(null);
    this.addError.set(null);
    void this.runSearch(this.search());
  }

  setSearch(text: string): void {
    this.search.set(text);
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(() => void this.runSearch(text.trim()), 200);
  }

  private async runSearch(q: string): Promise<void> {
    const option = this.option();
    if (!option) return;
    const id = ++this.searchId;
    try {
      const lists = await Promise.all(option.otherKinds.map((kind) => firstValueFrom(this.api.entities(this.slug(), { kind, q }))));
      if (id !== this.searchId) return;
      this.results.set(lists.flat().filter((e) => e.id !== this.entity().id).slice(0, 30));
    } catch (err) {
      if (id === this.searchId) this.addError.set(toWorldError(err).message);
    }
  }

  async pick(other: Entity): Promise<void> {
    const option = this.option();
    if (!option) return;
    const self = this.entity().id;
    const [source, target] = option.direction === 'out' ? [self, other.id] : [other.id, self];
    this.addError.set(null);
    try {
      await firstValueFrom(this.api.createLink(this.slug(), option.typeId, source, target));
      this.adding.set(false);
      await this.load(this.slug(), self);
      this.changed.emit();
    } catch (err) {
      this.addError.set(toWorldError(err).message);
    }
  }

  async remove(link: EntityLink): Promise<void> {
    this.error.set(null);
    try {
      await firstValueFrom(this.api.removeLink(this.slug(), link.id));
      await this.load(this.slug(), this.entity().id);
      this.changed.emit();
    } catch (err) {
      this.error.set(toWorldError(err).message);
    }
  }
}
