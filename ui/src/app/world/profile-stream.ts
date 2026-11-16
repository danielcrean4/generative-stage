import { Component, computed, inject, input, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { ProfileNote } from './profile-note';
import { NotesData } from './notes-data';
import { StreamEvent, StreamFilter, filterStream } from './profile-model';
import { WorldApi } from './world-api';
import { formatTime } from './world-format';

/** Every word in this panel. */
const WORDS = {
  title: 'History',
  help: 'Notes, field changes, attached runs and choices, newest first.',
  empty: 'Nothing here yet.',
  note: (text: string) => `Note: ${text}`,
  was: 'was',
  filters: 'Filter the history',
  thumb: 'The image that was chosen',
  thumbMissing: 'The image file is missing.',
};

const FILTERS: { id: StreamFilter; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'note', label: 'Notes' },
  { id: 'change', label: 'Changes' },
  { id: 'run', label: 'Runs and choices' },
];

/** The history of an entity as one list with a filter row. Shows what it is given; loads nothing. */
@Component({
  selector: 'app-profile-stream',
  imports: [RouterLink, ProfileNote],
  styles: `
    :host { display: block; min-width: 0; }
    h3 { margin: 0; }
    .hint { margin: 0.1rem 0 0; font-size: 0.85rem; color: var(--mat-sys-on-surface-variant); }
    .filters { display: flex; gap: 0.4rem; flex-wrap: wrap; margin: 0.6rem 0 0.25rem; }
    .filters button { font: inherit; font-size: 0.85rem; padding: 0.15rem 0.7rem; border-radius: 999px; border: 1px solid var(--mat-sys-outline-variant); background: transparent; color: inherit; cursor: pointer; }
    .filters button[aria-pressed='true'] { background: var(--mat-sys-primary); border-color: var(--mat-sys-primary); color: var(--mat-sys-on-primary); }
    ul { list-style: none; margin: 0; padding: 0; }
    li { padding: 0.6rem 0; border-top: 1px solid var(--mat-sys-outline-variant); min-width: 0; overflow-wrap: anywhere; }
    .meta { font-size: 0.8rem; color: var(--mat-sys-on-surface-variant); }
    .diff { font-size: 0.85rem; margin-top: 0.2rem; }
    .diff del { color: var(--mat-sys-error); }
    .diff ins { text-decoration: none; }
    .thumb { width: 72px; height: 72px; object-fit: contain; margin-top: 0.4rem; border: 1px solid var(--mat-sys-outline-variant); border-radius: 8px; background: var(--mat-sys-surface-container-low); display: block; }
  `,
  template: `
    <section data-panel="history">
      <h3>{{ w.title }}</h3>
      <p class="hint">{{ w.help }}</p>
      <div class="filters" role="group" [attr.aria-label]="w.filters">
        @for (f of filters; track f.id) {
          <button type="button" [attr.aria-pressed]="filter() === f.id" [attr.data-filter]="f.id" (click)="filter.set(f.id)">{{ f.label }}</button>
        }
      </div>
      <ul>
        @for (e of shown(); track e.id) {
          <li [attr.data-event]="e.kind">
            @if (e.noteItem; as n) {
              <app-profile-note [note]="n" [data]="notes()" />
            } @else {
            <div>
              @if (e.kind === 'run') {
                <a [routerLink]="['/world', kind(), entityId(), 'runs', e.id.slice(4)]" data-action="stream-trace">{{ e.title }}</a>
              } @else {
                {{ e.title }}
              }
            </div>
            <div class="meta">{{ when(e.at) }}</div>
            @for (c of e.changes; track c.key) {
              <div class="diff">{{ c.label }}: <del>{{ c.before }}</del> → <ins>{{ c.after }}</ins></div>
            }
            @if (e.note) {
              <div class="meta">{{ w.note(e.note) }}</div>
            }
            @if (e.thumb; as t) {
              @if (missing().has(url(t))) {
                <div class="meta" data-testid="thumb-missing">{{ w.thumbMissing }}</div>
              } @else {
                <img class="thumb" loading="lazy" [src]="url(t)" [alt]="w.thumb" (error)="lost(url(t))" />
              }
            }
            }
          </li>
        } @empty {
          <li class="meta">{{ w.empty }}</li>
        }
      </ul>
    </section>
  `,
})
export class ProfileStream {
  readonly w = WORDS;
  readonly filters = FILTERS;
  private readonly api = inject(WorldApi);

  readonly slug = input.required<string>();
  readonly entityId = input.required<string>();
  readonly kind = input.required<string>();
  readonly events = input.required<StreamEvent[]>();
  readonly notes = input.required<NotesData>();
  /** Thumbnails whose file failed to load, by url. */
  readonly missing = signal<ReadonlySet<string>>(new Set());
  readonly filter = signal<StreamFilter>('all');
  readonly shown = computed(() => filterStream(this.events(), this.filter()));

  when(iso: string): string {
    return formatTime(iso);
  }

  lost(url: string): void {
    this.missing.update((s) => new Set(s).add(url));
  }

  url(t: { runId: string; candidate: string }): string {
    return this.api.candidateFileUrl(this.slug(), this.entityId(), t.runId, t.candidate);
  }
}
