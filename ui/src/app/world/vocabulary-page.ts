import { Component, computed, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { firstValueFrom } from 'rxjs';
import { ConditionBox } from './condition-box';
import { suggestFacts } from './condition-model';
import { WorldApi } from './world-api';
import { WorldGate } from './world-gate';
import { Vocabulary } from './world-models';
import { WorldProjectService } from './world-project.service';

const WORDS = {
  title: 'Vocabulary',
  intro: 'The words this project\'s conditions and effects may use. The game supplies them as data (vocabulary.json in the project\'s kinds folder); the tool only reads them.',
  none: 'This project has no vocabulary. A game\'s adapter writes vocabulary.json into the project\'s kinds folder.',
  loading: 'Loading…',
  source: 'Made by',
  try: 'Try a condition',
  tryHint: 'Checked against the vocabulary as you type. Nothing is saved.',
  facts: 'Facts',
  filter: 'Filter facts',
  colPattern: 'Fact',
  colType: 'Type',
  colDoc: 'What it is',
  operators: 'Operators',
  takes: (types: string[]) => `on ${types.join(', ')}`,
  effects: 'Effects',
  args: (names: string[]) => (names.length ? names.join(', ') : 'no arguments'),
  modes: 'Rule modes',
  shorthand: 'Older shorthand keys',
  shown: (n: number, of: number) => `${n} of ${of}`,
};

/** The project's condition vocabulary, read-only, with a condition box to try it. */
@Component({
  selector: 'app-vocabulary-page',
  imports: [WorldGate, ConditionBox, FormsModule],
  styleUrl: './world-pages.scss',
  styles: `
    .table-wrap { overflow-x: auto; max-width: 100%; }
    table { border-collapse: collapse; width: 100%; }
    td, th { text-align: left; padding: 0.25rem 0.5rem; vertical-align: top; border-bottom: 1px solid var(--mat-sys-outline-variant); }
    code { overflow-wrap: anywhere; }
    .plain { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.25rem; }
  `,
  template: `
    <app-world-gate>
      <section class="world-page" data-page="vocabulary">
        <header class="page-head"><h2>{{ w.title }}</h2></header>
        <p class="intro">{{ w.intro }}</p>
        @if (status() === 'loading') {
          <p class="muted">{{ w.loading }}</p>
        } @else if (error(); as e) {
          <p class="error" role="alert">{{ e }}</p>
        } @else if (vocabulary(); as v) {
          @if (v.source) { <p class="hint">{{ w.source }}: {{ v.source }}</p> }
          <h3>{{ w.try }}</h3>
          <p class="hint">{{ w.tryHint }}</p>
          <app-condition-box [slug]="slug()" [vocabulary]="v" />

          <h3>{{ w.facts }} <span class="hint">{{ w.shown(facts().length, v.facts.length) }}</span></h3>
          <input type="search" [attr.aria-label]="w.filter" [placeholder]="w.filter" [ngModel]="filter()" (ngModelChange)="filter.set($event)" />
          <div class="table-wrap">
            <table data-testid="facts">
              <thead><tr><th>{{ w.colPattern }}</th><th>{{ w.colType }}</th><th>{{ w.colDoc }}</th></tr></thead>
              <tbody>
                @for (f of facts(); track f.pattern) {
                  <tr><td><code>{{ f.pattern }}</code></td><td>{{ f.type }}</td><td>{{ f.doc }}</td></tr>
                }
              </tbody>
            </table>
          </div>

          <h3>{{ w.operators }}</h3>
          <ul class="plain">
            @for (op of operators(); track op[0]) {
              <li><code>{{ op[0] }}</code> "{{ op[1].text }}" {{ w.takes(op[1].types) }}</li>
            }
          </ul>

          @if (effects().length) {
            <h3>{{ w.effects }}</h3>
            <ul class="plain" data-testid="effects">
              @for (e of effects(); track e[0]) {
                <li><code>{{ e[0] }}</code>: {{ w.args(argNames(e[1].args)) }}{{ e[1].doc ? ' (' + e[1].doc + ')' : '' }}</li>
              }
            </ul>
          }
          @if (modes().length) {
            <h3>{{ w.modes }}</h3>
            <ul class="plain">
              @for (m of modes(); track m[0]) {
                <li><code>{{ m[0] }}</code>{{ m[1].doc ? ': ' + m[1].doc : '' }}</li>
              }
            </ul>
          }
          @if (v.shorthand?.keys?.length) {
            <h3>{{ w.shorthand }}</h3>
            <p>{{ v.shorthand!.keys.join(', ') }}</p>
            @if (v.shorthand!.doc) { <p class="hint">{{ v.shorthand!.doc }}</p> }
          }
        } @else {
          <p class="empty" data-testid="no-vocabulary">{{ w.none }}</p>
        }
      </section>
    </app-world-gate>
  `,
})
export class VocabularyPage {
  readonly w = WORDS;
  private readonly api = inject(WorldApi);
  private readonly world = inject(WorldProjectService);
  readonly slug = computed(() => this.world.slug() ?? '');
  readonly status = signal<'loading' | 'ready'>('loading');
  readonly error = signal<string | null>(null);
  readonly vocabulary = signal<Vocabulary | null>(null);
  readonly filter = signal('');
  readonly facts = computed(() => {
    const v = this.vocabulary();
    return v ? suggestFacts(v, this.filter(), v.facts.length) : [];
  });
  readonly operators = computed(() => Object.entries(this.vocabulary()?.operators ?? {}));
  readonly effects = computed(() => Object.entries(this.vocabulary()?.effects?.kinds ?? {}));
  readonly modes = computed(() => Object.entries(this.vocabulary()?.rule_modes ?? {}));

  constructor() {
    effect(() => {
      const slug = this.world.slug();
      if (slug && this.world.catalogStatus() === 'ready') void this.load(slug);
    });
  }

  argNames(args: Record<string, unknown>): string[] {
    return Object.keys(args);
  }

  private async load(slug: string): Promise<void> {
    this.status.set('loading');
    this.error.set(null);
    try {
      this.vocabulary.set(await firstValueFrom(this.api.vocabulary(slug)));
    } catch (err) {
      this.error.set(err instanceof Error ? err.message : String(err));
    }
    this.status.set('ready');
  }
}
