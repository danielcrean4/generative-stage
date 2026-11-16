import { Component, computed, effect, inject, signal, untracked } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { MatButtonModule } from '@angular/material/button';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { combineLatest, firstValueFrom, map } from 'rxjs';
import { firstToLookAt, folderOf, formatSeconds, isChosen, shownFiles, showValue, slotsFor, stageOutcome, stageTitle } from './trace-model';
import { baseName, shortId, slotLabel } from './profile-model';
import { ModelViewer } from '../viewer/model-viewer';
import { PromptView } from './prompt-view';
import { toWorldError, WorldApi } from './world-api';
import { formatTime } from './world-format';
import { WorldGate } from './world-gate';
import { Trace, TraceFile, TraceStage } from './world-models';
import { WorldProjectService } from './world-project.service';

/** Every word on this screen. */
const WORDS = {
  back: (title: string) => `Back to ${title}`,
  title: (run: string) => `Run ${run}`,
  loading: 'Loading…',
  loadFailed: 'Could not open this run:',
  attempt: 'Attempt',
  status: 'Status',
  started: 'Started',
  took: 'Took',
  seed: 'Seed',
  sources: 'Shared inputs',
  filmstrip: 'Stages, in the order they ran',
  noStages: 'This attempt has no stages yet.',
  statuses: { completed: 'Completed', errored: 'Errored', running: 'Running', not_run: 'Not run', supplied: 'Supplied' } as Record<string, string>,
  reused: 'Reused',
  reusedFrom: (from: string) => `Reused from ${from}`,
  gate: (v: string) => `Gate: ${v}`,
  noOutputs: 'No pictures or 3D files.',
  model: '3D file',
  view3d: 'View in 3D',
  open: (title: string) => `Open ${title}`,
  detail: 'Details',
  outputs: 'Outputs',
  otherFiles: 'Other files',
  prompt: 'Prompt',
  negative: 'Negative prompt',
  noPrompt: 'This stage has no prompt.',
  context: 'Settings and shared values it read',
  inputs: 'Inputs',
  noInputs: 'No inputs recorded.',
  adapter: 'Model and adapter',
  noAdapter: 'No model identity recorded.',
  timing: 'Time',
  gates: 'Gate',
  noGate: 'This stage has no gate.',
  measure: 'Measure',
  value: 'Value',
  limit: 'Limit',
  reasons: 'Reasons',
  error: 'Error',
  cacheKey: 'Cache key',
  stageSeed: 'Seed used',
  compare: 'Compare and choose',
  compareHelp: 'The file you picked next to what is chosen now.',
  thisFile: 'This file',
  chosenNow: 'Chosen now',
  nothingChosen: 'Nothing is chosen in this slot yet.',
  slot: 'Choose it as',
  useThis: 'Use this',
  choosing: 'Choosing…',
  isChosen: (slot: string) => `Already the choice for ${slot}.`,
  close: 'Close',
  candidate: 'candidate',
  chosenTag: 'chosen',
  download: 'Download the file',
  missing: 'The file is missing or cannot be shown.',
  problem: 'The run record could not be read:',
};

/**
 * One run attempt as a filmstrip: a column per stage, in order, with its outputs, time, status and
 * gate. A stage opens to its full detail, and any picture or 3D file can be compared with what is
 * chosen now and made the choice, with the same call the profile page makes.
 */
@Component({
  selector: 'app-trace-page',
  imports: [RouterLink, WorldGate, MatButtonModule, ModelViewer, PromptView],
  templateUrl: './trace-page.html',
  styleUrl: './trace-page.scss',
})
export class TracePage {
  readonly w = WORDS;
  readonly world = inject(WorldProjectService);
  private readonly api = inject(WorldApi);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

  private readonly params = toSignal(
    combineLatest([this.route.paramMap, this.route.queryParamMap]).pipe(
      map(([p, q]) => ({ kind: p.get('kind'), id: p.get('id'), runId: p.get('runId'), attempt: q.get('attempt'), stage: q.get('stage') })),
    ),
    { initialValue: { kind: null as string | null, id: null as string | null, runId: null as string | null, attempt: null as string | null, stage: null as string | null } },
  );

  readonly trace = signal<Trace | null>(null);
  readonly loadError = signal<string | null>(null);
  readonly loading = signal(false);
  /** The file picked for comparing, with the slot to choose it for. */
  readonly picked = signal<{ file: TraceFile; slot: string } | null>(null);
  readonly choosing = signal(false);
  readonly chooseError = signal<string | null>(null);
  private readonly failed = signal<ReadonlySet<string>>(new Set());

  /** What to load: opening another stage of the same attempt must not load again. */
  private readonly target = computed(
    () => {
      const { id, runId, attempt } = this.params();
      return { id, runId, attempt };
    },
    { equal: (a, b) => a.id === b.id && a.runId === b.runId && a.attempt === b.attempt },
  );

  constructor() {
    effect(() => {
      const slug = this.world.slug();
      const { id, runId, attempt } = this.target();
      untracked(() => {
        this.picked.set(null);
        if (!slug || !id || !runId) return;
        void this.load(slug, id, runId, attempt);
      });
    });
  }

  private async load(slug: string, id: string, runId: string, attempt: string | null): Promise<void> {
    this.loading.set(true);
    this.loadError.set(null);
    try {
      this.trace.set(await firstValueFrom(this.api.trace(slug, id, runId, attempt ?? undefined)));
    } catch (err) {
      this.trace.set(null);
      this.loadError.set(toWorldError(err).message);
    }
    this.loading.set(false);
  }

  readonly selected = computed<TraceStage | null>(() => {
    const trace = this.trace();
    if (!trace) return null;
    const wanted = this.params().stage;
    return trace.stages.find((s) => folderOf(s) === wanted) ?? firstToLookAt(trace.stages);
  });

  readonly current = computed(() => {
    const picked = this.picked();
    return picked ? (this.trace()?.chosen[picked.slot] ?? null) : null;
  });

  readonly currentUrl = computed(() => {
    const choice = this.current();
    const slug = this.world.slug();
    const trace = this.trace();
    if (!choice || !slug || !trace) return null;
    return `${this.api.chosenFileUrl(slug, trace.entity.id, choice.slot)}?v=${encodeURIComponent(choice.chosen_at)}`;
  });

  readonly alreadyChosen = computed(() => {
    const picked = this.picked();
    const trace = this.trace();
    if (!picked || !trace) return null;
    const choice = trace.chosen[picked.slot];
    return choice && choice.run_id === trace.run_id && choice.candidate === picked.file.candidate ? picked.slot : null;
  });

  readonly base = baseName;
  readonly shortRun = shortId;
  readonly slotLabel = slotLabel;
  readonly outcome = stageOutcome;
  readonly title = stageTitle;
  readonly files = shownFiles;
  readonly slotsFor = slotsFor;
  readonly show = showValue;

  seconds(s: number | null): string | null {
    return formatSeconds(s);
  }

  when(iso: string | null): string {
    return iso ? formatTime(iso) : '';
  }

  folder(stage: TraceStage): string {
    return folderOf(stage);
  }

  isSelected(stage: TraceStage): boolean {
    return this.selected() === stage;
  }

  entries(value: Record<string, unknown> | null): [string, unknown][] {
    return value ? Object.entries(value) : [];
  }

  isCandidate(file: TraceFile): boolean {
    return this.trace()?.candidates.some((c) => c.candidate === file.candidate) ?? false;
  }

  chosenSlot(file: TraceFile): string | null {
    const trace = this.trace();
    return trace ? isChosen(file, trace.run_id, trace.chosen) : null;
  }

  isPicked(file: TraceFile): boolean {
    return this.picked()?.file.candidate === file.candidate;
  }

  fileFailed(url: string): boolean {
    return this.failed().has(url);
  }

  imageFailed(url: string): void {
    this.failed.update((s) => new Set(s).add(url));
  }

  name(file: TraceFile): string {
    return baseName(file.candidate);
  }

  openStage(stage: TraceStage): void {
    void this.router.navigate([], { queryParams: { stage: this.folder(stage) }, queryParamsHandling: 'merge', replaceUrl: true });
  }

  pickAttempt(attempt: string): void {
    void this.router.navigate([], { queryParams: { attempt, stage: null }, queryParamsHandling: 'merge' });
  }

  pick(stage: TraceStage, file: TraceFile): void {
    this.chooseError.set(null);
    if (this.selected() !== stage) this.openStage(stage);
    const slots = slotsFor(file);
    if (slots.length === 0) return;
    this.picked.set(this.isPicked(file) ? null : { file, slot: slots[0] });
  }

  setSlot(slot: string): void {
    const picked = this.picked();
    if (picked) this.picked.set({ ...picked, slot });
  }

  async useThis(): Promise<void> {
    const picked = this.picked();
    const slug = this.world.slug();
    const trace = this.trace();
    if (!picked || !slug || !trace) return;
    this.choosing.set(true);
    this.chooseError.set(null);
    try {
      await firstValueFrom(this.api.choose(slug, trace.entity.id, trace.run_id, picked.file.candidate, picked.slot));
      const chosen = await firstValueFrom(this.api.chosen(slug, trace.entity.id));
      this.trace.set({ ...trace, chosen });
    } catch (err) {
      this.chooseError.set(toWorldError(err).message);
    }
    this.choosing.set(false);
  }
}
