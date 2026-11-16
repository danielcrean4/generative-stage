import { Component, effect, inject, signal, untracked } from '@angular/core';
import { RouterLink } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { typeWord } from './prompt-parts';
import { toWorldError, WorldApi } from './world-api';
import { WorldGate } from './world-gate';
import { SourceItem } from './world-models';
import { WorldProjectService } from './world-project.service';

/** Every word on this screen. */
const WORDS = {
  title: 'Sources',
  intro: 'The shared words prompts are made from. A change to one changes every run that reads it afterwards.',
  loading: 'Loading…',
  loadFailed: 'Could not list the sources:',
  groups: { style: 'Style packs', motif: 'Motifs', contract: 'Contracts' } as Record<string, string>,
  usedBy: (ids: string[]) => `Used by: ${ids.join(', ')}`,
};

/** The index of the shared sources, by kind, each linking to its page. */
@Component({
  selector: 'app-sources-page',
  imports: [RouterLink, WorldGate],
  styles: `
    .sources { display: flex; flex-direction: column; gap: 0.75rem; max-width: 56rem; min-width: 0; }
    h2, h3 { margin: 0; }
    ul { list-style: none; margin: 0.3rem 0 0; padding: 0; display: flex; flex-direction: column; gap: 0.3rem; }
    li { overflow-wrap: anywhere; }
    .hint { color: var(--mat-sys-on-surface-variant); font-size: 0.85rem; margin: 0; }
    .error { color: var(--mat-sys-error); }
    .chip { display: inline-block; padding: 0 0.5rem; font-size: 0.8rem; border: 1px solid var(--mat-sys-outline-variant); border-radius: 999px; }
  `,
  template: `
    <app-world-gate>
      <section class="sources" data-page="sources">
        <h2>{{ w.title }}</h2>
        <p class="hint">{{ w.intro }}</p>
        @if (error(); as message) {
          <p class="error" role="alert">{{ w.loadFailed }} {{ message }}</p>
        } @else if (items(); as list) {
          @for (type of types; track type) {
            <section [attr.data-group]="type">
              <h3>{{ w.groups[type] }}</h3>
              <ul>
                @for (s of byType(list, type); track s.id) {
                  <li>
                    <a [routerLink]="['/sources', s.type, s.id]" [attr.data-source]="s.id">{{ word(s.type) }} {{ s.name }}</a>
                    <span class="chip">{{ s.set }}</span>
                    <span class="hint">{{ w.usedBy(s.pipelines) }}</span>
                  </li>
                }
              </ul>
            </section>
          }
        } @else {
          <p class="hint">{{ w.loading }}</p>
        }
      </section>
    </app-world-gate>
  `,
})
export class SourcesPage {
  readonly w = WORDS;
  readonly world = inject(WorldProjectService);
  private readonly api = inject(WorldApi);
  readonly items = signal<SourceItem[] | null>(null);
  readonly error = signal<string | null>(null);
  readonly types = ['style', 'motif', 'contract'];
  readonly word = typeWord;

  constructor() {
    effect(() => {
      const slug = this.world.slug();
      untracked(() => {
        this.items.set(null);
        this.error.set(null);
        if (slug) void this.load(slug);
      });
    });
  }

  byType(list: SourceItem[], type: string): SourceItem[] {
    return list.filter((s) => s.type === type);
  }

  private async load(slug: string): Promise<void> {
    try {
      this.items.set(await firstValueFrom(this.api.sources(slug)));
    } catch (err) {
      this.error.set(toWorldError(err).message);
    }
  }
}
