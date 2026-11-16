import { Component, effect, inject, input, signal, untracked } from '@angular/core';
import { RouterLink } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { typeWord } from './prompt-parts';
import { toWorldError, WorldApi } from './world-api';
import { AttachedRun, Feeds } from './world-models';

/** Every word in this panel. */
const WORDS = {
  title: 'Feeds this',
  help: 'The shared words and settings the last run read. Open one to see what else reads it.',
  none: 'No run has been made for this yet.',
  older: 'changed since',
  noPage: 'no page',
};

/** The shared sources the entity's last run read, as chips linking to their pages. */
@Component({
  selector: 'app-profile-feeds',
  imports: [RouterLink],
  styles: `
    :host { display: block; min-width: 0; }
    h3 { margin: 0; }
    .hint { margin: 0.1rem 0 0.6rem; font-size: 0.85rem; color: var(--mat-sys-on-surface-variant); }
    .chips { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: 0.4rem; }
    .chip { display: inline-flex; gap: 0.3rem; align-items: baseline; padding: 0.15rem 0.6rem; border: 1px solid var(--mat-sys-outline-variant); border-radius: 999px; font-size: 0.85rem; text-decoration: none; color: inherit; overflow-wrap: anywhere; }
    a.chip:hover { background: var(--mat-sys-surface-container-high); }
    .kind { font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.03em; color: var(--mat-sys-on-surface-variant); }
    .older { color: var(--mat-sys-error); font-size: 0.75rem; }
    .error { color: var(--mat-sys-error); }
  `,
  template: `
    <section data-panel="feeds">
      <h3>{{ w.title }}</h3>
      <p class="hint">{{ w.help }}</p>
      @if (error(); as message) {
        <p class="error" role="alert">{{ message }}</p>
      }
      @if (feeds(); as f) {
        @if (f.sources.length === 0) {
          <p class="hint" data-testid="no-feeds">{{ w.none }}</p>
        } @else {
          <ul class="chips" data-testid="feeds">
            @for (s of f.sources; track s.type + s.name) {
              <li>
                @if (s.id; as id) {
                  <a class="chip" [routerLink]="['/sources', s.type, id]" [attr.data-source]="id"
                    ><span class="kind">{{ word(s.type) }}</span> {{ s.name }}
                    @if (s.changed) { <span class="older">{{ w.older }}</span> }</a
                  >
                } @else {
                  <span class="chip" [attr.title]="w.noPage"><span class="kind">{{ word(s.type) }}</span> {{ s.name }}</span>
                }
              </li>
            }
          </ul>
        }
      }
    </section>
  `,
})
export class ProfileFeeds {
  readonly w = WORDS;
  private readonly api = inject(WorldApi);
  readonly slug = input.required<string>();
  readonly entityId = input.required<string>();
  /** The attached runs: when they change, a new run has been made, so the panel reads again. */
  readonly runs = input<AttachedRun[]>([]);
  readonly feeds = signal<Feeds | null>(null);
  readonly error = signal<string | null>(null);
  readonly word = typeWord;

  constructor() {
    effect(() => {
      const slug = this.slug();
      const id = this.entityId();
      this.runs();
      untracked(() => void this.load(slug, id));
    });
  }

  private async load(slug: string, id: string): Promise<void> {
    this.error.set(null);
    try {
      this.feeds.set(await firstValueFrom(this.api.feeds(slug, id)));
    } catch (err) {
      this.error.set(toWorldError(err).message);
    }
  }
}
