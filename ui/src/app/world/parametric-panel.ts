import { Component, OnDestroy, effect, inject, input, output, signal, untracked } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { ParametricApi } from './parametric-api';
import { ParametricForm } from './parametric-form';
import { PreviewView, ParamModel, settle, stillUrl } from './parametric-model';
import { WorldApi } from './world-api';
import { Entity, JsonObject } from './world-models';

const WORDS = {
  title: 'Parameters',
  help: 'Move a slider and the picture follows. Save as candidate keeps the picture beside the others; Use this keeps it and sets the fields.',
  rendering: 'Drawing…',
  save: 'Save as candidate',
  use: 'Use this',
  saved: 'Saved as a candidate.',
  used: 'Fields and picture set.',
  gate: (id: string, verdict: string) => `${id}: ${verdict}`,
  failed: 'The preview could not be made:',
};
const DEBOUNCE_MS = 250;

/**
 * The slider page of a parametric record: the form made from the kind's parameters, and a live preview through the
 * render adapter, asked for 250 ms after the last move. Save as candidate keeps the picture as a candidate of the
 * record; Use this also writes the parameters into its fields and chooses the picture.
 */
@Component({
  selector: 'app-parametric-panel',
  imports: [MatButtonModule, ParametricForm],
  template: `
    <section class="panel" data-panel="parametric">
      <h3>{{ w.title }}</h3>
      <p class="hint">{{ w.help }}</p>
      <div class="cols">
        <app-parametric-form [model]="model()" [row]="row()" (rowChange)="move($event)" />
        <div class="shown">
          @if (preview(); as p) {
            <img data-testid="parametric-preview" [attr.data-preview]="p.id" [src]="url(p)" alt="Preview of the current parameters" width="256" height="256" />
            <ul class="gates" data-testid="parametric-gates">
              @for (g of p.gates; track g.id) {
                <li [attr.data-gate]="g.id" [attr.data-verdict]="g.verdict" [class.bad]="g.verdict !== 'pass'" [attr.title]="g.about">{{ w.gate(g.id, g.verdict) }}</li>
              }
            </ul>
          }
          @if (busy()) {
            <p class="hint" data-testid="parametric-busy">{{ w.rendering }}</p>
          }
          @if (error(); as e) {
            <p class="error" role="alert">{{ w.failed }} {{ e }}</p>
          }
        </div>
      </div>
      <div class="actions">
        <button mat-stroked-button type="button" (click)="keep(false)" [disabled]="!preview() || working() || busy()" data-action="param-save">{{ w.save }}</button>
        <button mat-flat-button type="button" (click)="keep(true)" [disabled]="!preview() || working() || busy()" data-action="param-use">{{ w.use }}</button>
        @if (notice(); as n) {
          <span class="hint" data-testid="parametric-notice">{{ n }}</span>
        }
      </div>
    </section>
  `,
  styles: `
    .cols { display: flex; flex-wrap: wrap; align-items: flex-start; gap: 1rem; }
    .cols app-parametric-form { flex: 1 1 24rem; }
    .shown { flex: 0 0 256px; }
    .shown img { border: 1px solid var(--mat-sys-outline-variant); background: #fff; }
    .gates { list-style: none; padding: 0; margin: 0.4rem 0 0; font-size: 0.85rem; }
    .gates .bad { color: var(--mat-sys-error); }
    .actions { display: flex; gap: 0.6rem; align-items: center; margin-top: 0.8rem; }
    .error { color: var(--mat-sys-error); }
  `,
})
export class ParametricPanel implements OnDestroy {
  readonly w = WORDS;
  private readonly api = inject(ParametricApi);
  private readonly world = inject(WorldApi);
  readonly slug = input.required<string>();
  readonly kind = input.required<string>();
  readonly model = input.required<ParamModel>();
  readonly entity = input.required<Entity>();
  /** Fired after the record's fields or candidates changed on the server. */
  readonly changed = output<{ fields: boolean }>();

  readonly row = signal<JsonObject>({});
  readonly preview = signal<PreviewView | null>(null);
  readonly busy = signal(false);
  readonly working = signal(false);
  readonly error = signal<string | null>(null);
  readonly notice = signal<string | null>(null);
  private timer: ReturnType<typeof setTimeout> | null = null;
  private ask = 0;

  constructor() {
    effect(() => {
      const row = settle(this.model(), this.entity().data);
      untracked(() => {
        this.row.set(row);
        this.render(0);
      });
    });
  }

  ngOnDestroy(): void {
    if (this.timer) clearTimeout(this.timer);
  }

  url(p: PreviewView): string {
    return stillUrl(this.slug(), p.id, p.still);
  }

  move(row: JsonObject): void {
    this.row.set(row);
    this.notice.set(null);
    this.render(DEBOUNCE_MS);
  }

  /** Ask for the picture of the current row after MS; an answer to an older ask is dropped. */
  private render(ms: number): void {
    if (this.timer) clearTimeout(this.timer);
    const mine = ++this.ask;
    this.busy.set(true);
    this.timer = setTimeout(() => {
      this.api.preview(this.slug(), this.kind(), this.row()).subscribe({
        next: (p) => {
          if (mine !== this.ask) return;
          this.preview.set(p);
          this.error.set(null);
          this.busy.set(false);
        },
        error: (e: unknown) => {
          if (mine !== this.ask) return;
          this.error.set(e instanceof Error ? e.message : String(e));
          this.busy.set(false);
        },
      });
    }, ms);
  }

  /** Keep the shown picture as a candidate of this record; with USE, also write the row into it and choose the picture. */
  keep(use: boolean): void {
    const slug = this.slug();
    const entity = this.entity();
    this.working.set(true);
    this.api.keep(slug, this.kind(), this.row()).subscribe({
      next: (kept) => {
        this.api.attachRun(slug, entity.id, kept.run_id).subscribe({
          next: () => {
            if (!use) return this.done(WORDS.saved, false);
            this.world.updateEntity(slug, entity.id, entity.revision, settle(this.model(), { ...entity.data, ...this.row() })).subscribe({
              next: () =>
                this.world.choose(slug, entity.id, kept.run_id, kept.candidate, 'main').subscribe({
                  next: () => this.done(WORDS.used, true),
                  error: (e: unknown) => this.fail(e),
                }),
              error: (e: unknown) => this.fail(e),
            });
          },
          error: (e: unknown) => this.fail(e),
        });
      },
      error: (e: unknown) => this.fail(e),
    });
  }

  private done(text: string, fields: boolean): void {
    this.working.set(false);
    this.notice.set(text);
    this.changed.emit({ fields });
  }

  private fail(e: unknown): void {
    this.working.set(false);
    this.error.set(e instanceof Error ? e.message : String(e));
  }
}
