import { Component, DestroyRef, OnInit, computed, inject, input, output, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { Subject, catchError, debounceTime, of, switchMap } from 'rxjs';
import { addLeaf, formatJson, leaf, operand, operatorsFor, parseJson, suggestFacts } from './condition-model';
import { WorldApi } from './world-api';
import { Vocabulary, VocabularyCheck } from './world-models';

const WORDS = {
  label: 'Condition (JSON)',
  checking: 'Checking…',
  fine: 'Fits the vocabulary.',
  empty: 'No condition: it always holds.',
  readsAs: 'Reads as',
  reads: 'Reads',
  shorthand: 'Written in older shorthand keys: the tool shows it as written and cannot say what it reads.',
  add: 'Add a fact',
  fact: 'Fact',
  operator: 'Operator',
  value: 'Value',
  addButton: 'Add',
  unreachable: 'The check could not be made:',
  factHint: 'Type to search; replace each (kind) with an id.',
};

/** What the box reports after each check: the parsed value, and whether the vocabulary accepts it. */
export interface ConditionState {
  value: unknown;
  valid: boolean;
}

/**
 * One condition, edited as JSON and checked against the project's vocabulary as you type (the
 * server answers; this box only shows it): problems with their JSON pointers, the plain words and
 * the facts it reads. A small row adds a leaf from a fact, an operator and a value.
 */
@Component({
  selector: 'app-condition-box',
  imports: [FormsModule],
  styles: `
    :host { display: block; }
    textarea { width: 100%; box-sizing: border-box; font-family: ui-monospace, monospace; font-size: 0.85rem; min-height: 7rem; }
    .row { display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: end; margin: 0.5rem 0; }
    .row label { display: flex; flex-direction: column; font-size: 0.8rem; min-width: 0; }
    .row input, .row select { max-width: 100%; }
    .fact-input { width: min(22rem, 100%); }
    .problems { margin: 0.25rem 0; padding-left: 1.2rem; color: var(--mat-sys-error); }
    .ok { color: var(--mat-sys-primary); margin: 0.25rem 0; }
    .words { margin: 0.25rem 0; overflow-wrap: anywhere; }
    .reads { margin: 0.25rem 0; padding-left: 1.2rem; font-size: 0.85rem; overflow-wrap: anywhere; }
    code { overflow-wrap: anywhere; }
  `,
  template: `
    <label class="hint" [attr.for]="id + '-text'">{{ w.label }}</label>
    <textarea
      [id]="id + '-text'"
      data-testid="condition-text"
      spellcheck="false"
      [ngModel]="text()"
      (ngModelChange)="edit($event)"
    ></textarea>
    <div aria-live="polite" data-testid="condition-status">
      @if (syntax(); as message) {
        <p class="problems" role="alert">{{ message }}</p>
      } @else if (checking()) {
        <p class="hint">{{ w.checking }}</p>
      } @else if (failure(); as message) {
        <p class="problems" role="alert">{{ w.unreachable }} {{ message }}</p>
      } @else if (value() === null) {
        <p class="hint">{{ w.empty }}</p>
      } @else if (result(); as r) {
        @if (r.problems.length) {
          <ul class="problems" data-testid="condition-problems">
            @for (p of r.problems; track $index) {
              <li><code>{{ p.field }}</code> {{ p.message }}</li>
            }
          </ul>
        } @else {
          <p class="ok" data-testid="condition-ok">{{ w.fine }}</p>
        }
        @if (r.text) {
          <p class="words" data-testid="condition-words"><strong>{{ w.readsAs }}:</strong> {{ r.text }}</p>
        }
        @if (r.shorthand) {
          <p class="hint">{{ w.shorthand }}</p>
        }
        @if (r.reads?.length) {
          <ul class="reads" [attr.aria-label]="w.reads">
            @for (read of r.reads; track read.path) {
              <li><code>{{ read.path }}</code> ({{ read.type }}){{ read.doc ? ': ' + read.doc : '' }}</li>
            }
          </ul>
        }
      }
    </div>
    <details>
      <summary>{{ w.add }}</summary>
      <div class="row">
        <label>{{ w.fact }}
          <input class="fact-input" data-testid="add-fact" [attr.list]="id + '-facts'" [ngModel]="factPath()" (ngModelChange)="factPath.set($event)" />
        </label>
        <datalist [id]="id + '-facts'">
          @for (f of suggestions(); track f.pattern) {
            <option [value]="f.pattern">{{ f.type }}{{ f.doc ? ': ' + f.doc : '' }}</option>
          }
        </datalist>
        <label>{{ w.operator }}
          <select data-testid="add-operator" [ngModel]="op()" (ngModelChange)="op.set($event)">
            @for (name of operators(); track name) {
              <option [value]="name">{{ vocabulary().operators[name].text }} ({{ name }})</option>
            }
          </select>
        </label>
        <label>{{ w.value }}
          <input data-testid="add-value" [ngModel]="raw()" (ngModelChange)="raw.set($event)" />
        </label>
        <button type="button" data-testid="add-leaf" (click)="addFromRow()" [disabled]="!factPath() || !op()">{{ w.addButton }}</button>
      </div>
      <p class="hint">{{ w.factHint }}</p>
    </details>
  `,
})
export class ConditionBox implements OnInit {
  private static next = 0;
  readonly w = WORDS;
  readonly id = `condition-${ConditionBox.next++}`;
  private readonly api = inject(WorldApi);
  private readonly destroyRef = inject(DestroyRef);

  readonly slug = input.required<string>();
  readonly vocabulary = input.required<Vocabulary>();
  readonly initial = input<unknown>(null);
  readonly changed = output<ConditionState>();

  readonly text = signal('');
  readonly syntax = signal<string | null>(null);
  readonly value = signal<unknown>(null);
  readonly checking = signal(false);
  readonly result = signal<VocabularyCheck | null>(null);
  readonly failure = signal<string | null>(null);

  readonly factPath = signal('');
  readonly op = signal('');
  readonly raw = signal('');
  readonly suggestions = computed(() => suggestFacts(this.vocabulary(), this.factPath()));
  private readonly chosenType = computed(() => {
    const typed = this.factPath().replace(/\(.*?\)/g, '(');
    return this.vocabulary().facts.find((f) => f.pattern.replace(/\(.*?\)/g, '(') === typed)?.type ?? null;
  });
  readonly operators = computed(() => operatorsFor(this.vocabulary(), this.chosenType()));

  private readonly checks = new Subject<unknown>();

  ngOnInit(): void {
    this.checks
      .pipe(
        debounceTime(250),
        switchMap((value) => {
          if (value === null) return of(null);
          return this.api.checkVocabulary(this.slug(), { condition: value }).pipe(
            catchError((err: Error) => {
              this.failure.set(err.message);
              return of(null);
            }),
          );
        }),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((result) => {
        this.checking.set(false);
        this.result.set(result);
        this.changed.emit({ value: this.value(), valid: this.value() === null || (result !== null && result.problems.length === 0) });
      });
    this.edit(formatJson(this.initial()));
  }

  edit(text: string): void {
    this.text.set(text);
    this.failure.set(null);
    const parsed = parseJson(text);
    if (!parsed.ok) {
      this.syntax.set(parsed.error);
      this.result.set(null);
      this.changed.emit({ value: undefined, valid: false });
      return;
    }
    this.syntax.set(null);
    this.value.set(parsed.value);
    this.checking.set(parsed.value !== null);
    this.checks.next(parsed.value);
  }

  addFromRow(): void {
    const type = this.chosenType();
    const json = (type && this.vocabulary().types[type]?.json) || 'string';
    const operator = this.vocabulary().operators[this.op()];
    const value = operand(this.raw(), operator?.operand === 'member' ? 'string' : json, operator?.operand === 'list');
    this.edit(formatJson(addLeaf(this.syntax() ? null : this.value(), leaf(this.factPath().trim(), this.op(), value))));
  }
}
