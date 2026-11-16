import { Component, computed, effect, inject, signal, untracked } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { MatButtonModule } from '@angular/material/button';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { Observable, map } from 'rxjs';
import { ParametricApi } from './parametric-api';
import { BatchTile, BatchView, ParametricInfo, TRIAGE, Triage, TriageVerdict, tileUrl } from './parametric-model';
import { WorldApi } from './world-api';
import { WorldGate } from './world-gate';
import { WorldProjectService } from './world-project.service';

const WORDS = {
  title: (kind: string) => `Batch of ${kind.toLowerCase()} variants`,
  help: 'The rules stage makes seeded variants from the kit table: no model, no network. Choose what to cross, make a batch, then mark each tile.',
  count: 'Variants per combination',
  seed: 'Seed',
  make: 'Make a batch',
  making: 'Making…',
  noKit: 'This project has no kit table for this kind (parametric/<kind>.kit.json).',
  sheet: 'Contact sheet',
  summary: (n: number, seconds: number, dropped: number) => `${n} variants in ${seconds} s; ${dropped} forbidden combinations were redrawn.`,
  note: 'Note',
  create: 'Create records from the kept tiles',
  creating: 'Creating…',
  created: (n: number) => `${n} record${n === 1 ? '' : 's'} created, each with its picture chosen.`,
  verdicts: { keep: 'Keep', fix: 'Fix', improve: 'Improve', remove: 'Remove' } as Record<TriageVerdict, string>,
  failed: 'Something went wrong:',
};

/**
 * The batch screen of a parametric kind: pick what to cross, make a batch, then triage its contact sheet. The sheet is
 * this kind's run view: each tile shows its picture, its measured numbers and gates; keep, fix, improve or remove is
 * saved with a note as you click. Kept tiles become records with their picture chosen, exportable like any record.
 */
@Component({
  selector: 'app-parametric-batch-page',
  imports: [RouterLink, WorldGate, MatButtonModule],
  templateUrl: './parametric-batch-page.html',
  styleUrl: './parametric-batch-page.scss',
})
export class ParametricBatchPage {
  readonly w = WORDS;
  readonly triage = TRIAGE;
  readonly world = inject(WorldProjectService);
  private readonly api = inject(ParametricApi);
  private readonly worldApi = inject(WorldApi);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

  private readonly params = toSignal(this.route.paramMap.pipe(map((p) => ({ kind: p.get('kind'), batch: p.get('batchId') }))), {
    initialValue: { kind: null as string | null, batch: null as string | null },
  });
  readonly kind = computed(() => this.world.kind(this.params().kind));
  readonly info = signal<ParametricInfo | null>(null);
  readonly batch = signal<BatchView | null>(null);
  readonly crossed = signal<Record<string, string[]>>({});
  readonly count = signal(5);
  readonly seed = signal(1);
  readonly busy = signal(false);
  readonly error = signal<string | null>(null);
  readonly notice = signal<string | null>(null);
  /** The two subject fields that are crossed: the first two the kit names. */
  readonly crossFields = computed(() => Object.entries(this.info()?.subject_fields ?? {}).filter(([, v]) => v).slice(0, 2));
  readonly counts = computed(() => {
    const tally = { keep: 0, fix: 0, improve: 0, remove: 0 };
    for (const mark of Object.values(this.batch()?.triage ?? {})) tally[mark.verdict]++;
    return tally;
  });

  constructor() {
    effect(() => {
      const slug = this.world.slug();
      const { kind, batch } = this.params();
      if (!slug || !kind) return;
      untracked(() => {
        this.error.set(null);
        this.api.info(slug, kind).subscribe({
          next: (info) => {
            this.info.set(info);
            this.crossed.set(Object.fromEntries(Object.entries(info.subject_fields).filter(([, v]) => v).slice(0, 2).map(([k, v]) => [k, [...(v ?? [])]])));
          },
          error: (e: Error) => this.error.set(e.message),
        });
        if (batch) this.api.batch(slug, batch).subscribe({ next: (b) => this.batch.set(b), error: (e: Error) => this.error.set(e.message) });
        else this.batch.set(null);
      });
    });
  }

  isCrossed(field: string, value: string): boolean {
    return this.crossed()[field]?.includes(value) ?? false;
  }

  toggle(field: string, value: string): void {
    const now = this.crossed()[field] ?? [];
    this.crossed.set({ ...this.crossed(), [field]: now.includes(value) ? now.filter((v) => v !== value) : [...now, value] });
  }

  setNumber(which: 'count' | 'seed', event: Event): void {
    const n = Math.trunc(Number((event.target as HTMLInputElement).value));
    (which === 'count' ? this.count : this.seed).set(Number.isFinite(n) ? n : 0);
  }

  make(): void {
    const slug = this.world.slug();
    const kind = this.params().kind;
    if (!slug || !kind) return;
    this.busy.set(true);
    this.error.set(null);
    const cross = Object.fromEntries(Object.entries(this.crossed()).filter(([, v]) => v.length));
    this.api.makeBatch(slug, kind, { cross, seed: this.seed(), count: this.count() }).subscribe({
      next: (b) => {
        this.busy.set(false);
        void this.router.navigate(['/world', kind, 'batch', b.id]);
      },
      error: (e: Error) => {
        this.busy.set(false);
        this.error.set(e.message);
      },
    });
  }

  url(tile: BatchTile): string {
    return tileUrl(this.world.slug() ?? '', this.batch()!.id, tile.id);
  }

  mark(tile: BatchTile): { verdict: TriageVerdict; note: string } | null {
    return this.batch()?.triage[tile.id] ?? null;
  }

  label(tile: BatchTile): string {
    return Object.values(tile.cell).join(' · ');
  }

  /** Click a verdict on a tile; the same verdict again clears it. The mark is saved at once. */
  set(tile: BatchTile, verdict: TriageVerdict): void {
    const was = this.mark(tile);
    this.save(tile, was?.verdict === verdict ? null : verdict, was?.note ?? '');
  }

  setNote(tile: BatchTile, note: string): void {
    const was = this.mark(tile);
    if (was) this.save(tile, was.verdict, note);
  }

  private save(tile: BatchTile, verdict: TriageVerdict | null, note: string): void {
    const slug = this.world.slug();
    const batch = this.batch();
    if (!slug || !batch) return;
    this.api.triage(slug, batch.id, tile.id, verdict, note).subscribe({
      next: (b) => this.batch.set({ ...batch, triage: b.triage as Triage }),
      error: (e: Error) => this.error.set(e.message),
    });
  }

  /** Each kept tile becomes a record of the kind with its picture chosen and its note kept as a note. */
  createKept(): void {
    const slug = this.world.slug();
    const batch = this.batch();
    const kind = this.params().kind;
    if (!slug || !batch || !kind) return;
    const kept = batch.tiles.filter((t) => batch.triage[t.id]?.verdict === 'keep');
    this.busy.set(true);
    this.error.set(null);
    void (async () => {
      try {
        for (const tile of kept) {
          const record = await firstValue(this.worldApi.createEntity(slug, kind, tile.row, `Kept from batch ${batch.id}, tile ${tile.id}`));
          await firstValue(this.api.attachRun(slug, record.id, batch.id));
          await firstValue(this.worldApi.choose(slug, record.id, batch.id, `tiles/${tile.id}/${tile.still}`, 'main', batch.triage[tile.id].note || undefined));
          const note = batch.triage[tile.id].note;
          if (note) await firstValue(this.worldApi.addNote(slug, record.id, `Triage: keep. ${note}`));
        }
        this.notice.set(WORDS.created(kept.length));
      } catch (e) {
        this.error.set(e instanceof Error ? e.message : String(e));
      } finally {
        this.busy.set(false);
      }
    })();
  }
}

function firstValue<T>(source: Observable<T>): Promise<T> {
  return new Promise((resolve, reject) => source.subscribe({ next: resolve, error: reject }));
}
