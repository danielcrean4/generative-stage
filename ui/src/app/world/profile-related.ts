import { Component, effect, inject, input, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { fileKind } from './profile-model';
import { toWorldError, WorldApi } from './world-api';
import { Choice, Entity, EntityLink } from './world-models';
import { WorldProjectService } from './world-project.service';

/** Every word in this panel. */
const WORDS = {
  title: 'Related',
  help: 'Everything linked to this, in both directions.',
  none: 'Nothing is linked yet. Add links in the full form.',
  noImage: 'No image',
};

/** At most this many linked entities are asked for their image. */
const MAX_IMAGES = 24;

interface Card {
  link: EntityLink;
  kind: string;
  image: string | null;
}

/** The entities linked to this one, as small cards with their chosen image when they have one. */
@Component({
  selector: 'app-profile-related',
  imports: [RouterLink],
  styles: `
    :host { display: block; min-width: 0; }
    h3 { margin: 0; }
    .hint { margin: 0.1rem 0 0.6rem; font-size: 0.85rem; color: var(--mat-sys-on-surface-variant); }
    .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(10rem, 1fr)); gap: 0.5rem; list-style: none; margin: 0; padding: 0; }
    a.card { display: flex; gap: 0.5rem; align-items: center; padding: 0.4rem; border: 1px solid var(--mat-sys-outline-variant); border-radius: 10px; text-decoration: none; color: inherit; min-width: 0; }
    .mini { width: 44px; height: 44px; flex: none; border-radius: 6px; background: var(--mat-sys-surface-container-high); object-fit: contain; display: block; }
    .text { min-width: 0; overflow-wrap: anywhere; font-size: 0.9rem; }
    .rel { display: block; font-size: 0.75rem; color: var(--mat-sys-on-surface-variant); }
    .error { color: var(--mat-sys-error); }
  `,
  template: `
    <section data-panel="related">
      <h3>{{ w.title }}</h3>
      <p class="hint">{{ w.help }}</p>
      @if (error(); as message) {
        <p class="error" role="alert">{{ message }}</p>
      }
      @if (cards(); as list) {
        @if (list.length === 0) {
          <p class="hint" data-testid="no-related">{{ w.none }}</p>
        } @else {
          <ul class="cards">
            @for (c of list; track c.link.id) {
              <li>
                <a class="card" [routerLink]="['/world', c.link.other.kind, c.link.other.id]" [attr.data-related]="c.link.other.id">
                  @if (c.image; as src) {
                    <img class="mini" loading="lazy" [src]="src" alt="" />
                  } @else {
                    <span class="mini" role="img" [attr.aria-label]="w.noImage"></span>
                  }
                  <span class="text">
                    <span class="rel">{{ c.link.label }} · {{ c.kind }}</span>
                    {{ c.link.other.title }}
                  </span>
                </a>
              </li>
            }
          </ul>
        }
      }
    </section>
  `,
})
export class ProfileRelated {
  readonly w = WORDS;
  private readonly api = inject(WorldApi);
  private readonly world = inject(WorldProjectService);

  readonly slug = input.required<string>();
  readonly entity = input.required<Entity>();
  readonly cards = signal<Card[] | null>(null);
  readonly error = signal<string | null>(null);
  private token = 0;

  constructor() {
    effect(() => {
      const slug = this.slug();
      const id = this.entity().id;
      this.entity().revision;
      void this.load(slug, id);
    });
  }

  private async load(slug: string, id: string): Promise<void> {
    const mine = ++this.token;
    this.error.set(null);
    try {
      const links = await firstValueFrom(this.api.links(slug, id));
      const others = [...new Set(links.map((l) => l.other.id))].slice(0, MAX_IMAGES);
      const chosen = new Map<string, Record<string, Choice>>();
      await Promise.all(
        others.map(async (other) => {
          try {
            chosen.set(other, await firstValueFrom(this.api.chosen(slug, other)));
          } catch {
            chosen.set(other, {});
          }
        }),
      );
      if (mine !== this.token) return;
      this.cards.set(
        links.map((link) => {
          const picks = chosen.get(link.other.id) ?? {};
          const pick = [picks['main'], ...Object.values(picks)].find((c) => c && fileKind(c.candidate) === 'image');
          return {
            link,
            kind: this.world.kind(link.other.kind)?.label ?? link.other.kind,
            image: pick ? `${this.api.chosenFileUrl(slug, link.other.id, pick.slot)}?v=${encodeURIComponent(pick.chosen_at)}` : null,
          };
        }),
      );
    } catch (err) {
      if (mine === this.token) this.error.set(toWorldError(err).message);
    }
  }
}
