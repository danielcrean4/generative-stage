import { Component, OnDestroy, computed, effect, inject, signal, untracked } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { MatButtonModule } from '@angular/material/button';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { combineLatest, map } from 'rxjs';
import { EntityEditor } from './entity-editor';
import { GenerateData } from './generate-data';
import { ParametricPanel } from './parametric-panel';
import { ProfileGenerate } from './profile-generate';
import { NotesData } from './notes-data';
import { ProfileComposer } from './profile-composer';
import { ProfileData } from './profile-data';
import { ProfileFeeds } from './profile-feeds';
import { ProfileFields } from './profile-fields';
import {
  CandidateItem,
  baseName,
  buildStream,
  candidateItems,
  fileKind,
  fitsSlot,
  freshness,
  sameFile,
  traceQuery,
  shortId,
  slotLabel,
  slotsOf,
} from './profile-model';
import { ProfileNote } from './profile-note';
import { ProfileRelated } from './profile-related';
import { ProfileStream } from './profile-stream';
import { ModelViewer } from '../viewer/model-viewer';
import { WorldApi } from './world-api';
import { WorldGate } from './world-gate';
import { Kind } from './world-models';
import { WorldProjectService } from './world-project.service';

/** Every word on this screen. */
const WORDS = {
  back: (plural: string) => `All ${plural.toLowerCase()}`,
  notFound: 'This project has no kind with that name.',
  loading: 'Loading…',
  loadFailed: (label: string) => `Could not open this ${label.toLowerCase()}:`,
  editAll: 'Edit all fields',
  archivedBanner: 'This is archived and cannot be edited here. Open the full form to restore it.',
  conflictTitle: 'Someone else changed this while you were editing.',
  conflictBody: (latest: number | null) => `${latest ? `It is now at revision ${latest}. ` : ''}Your change has not been saved. Reload to see the latest, or keep editing and copy what you need first.`,
  conflictReload: 'Reload the latest',
  conflictKeep: 'Keep editing',
  slots: 'Versions',
  pinnedTitle: 'Pinned notes',
  nothing: 'Nothing is chosen for this yet.',
  nothingHelp: 'Candidates from a run appear below once one is attached. Choose one with Use this.',
  missingFile: 'The file for this version is missing or cannot be shown.',
  model: (name: string) => `3D file: ${name}`,
  download: 'Download the file',
  otherFile: (name: string) => `File: ${name}`,
  status: (run: string, file: string, at: number, now: number) => `Chosen from run ${run}, ${file}, at revision ${at}. The entity is ${now === at ? 'still' : 'now'} at revision ${now}.`,
  stale: (fields: string) => `Fields changed since this was chosen: ${fields}.`,
  staleNone: 'The entity was saved again since this was chosen, with no field changed.',
  openRun: 'See how it was made',
  howMade: 'See how it was made',
  preview: (name: string) => `Previewing ${name}, not the chosen version.`,
  useThis: 'Use this',
  backToChosen: 'Back to the chosen version',
  choosing: 'Choosing…',
  candidatesTitle: 'Candidates',
  candidatesHelp: 'From the runs attached to this, and earlier choices. Click one to preview it.',
  noCandidates: 'No candidates for this version yet.',
  generate: 'Generate',
  generateAgain: 'Generate again',
  current: 'chosen',
  verdict: (v: string) => `Gate verdict: ${v}`,
  candidate: (name: string, current: boolean) => `${name}${current ? ', chosen' : ''}`,
};

/**
 * The page for one entity: what it looks like now (the chosen version per slot), what it is (its
 * fields, edited in place), the candidates to choose from, what it is linked to and what has
 * happened to it. The full form for bulk edits, archiving and links is one click away.
 */
@Component({
  selector: 'app-profile-page',
  imports: [RouterLink, WorldGate, MatButtonModule, ProfileFields, ProfileFeeds, ProfileStream, ProfileRelated, ProfileComposer, ProfileNote, ModelViewer, ProfileGenerate, ParametricPanel],
  templateUrl: './profile-page.html',
  styleUrl: './profile-page.scss',
})
export class ProfilePage implements OnDestroy {
  readonly w = WORDS;
  readonly world = inject(WorldProjectService);
  private readonly api = inject(WorldApi);
  private readonly route = inject(ActivatedRoute);

  private readonly params = toSignal(combineLatest([this.route.paramMap]).pipe(map(([p]) => ({ kind: p.get('kind'), id: p.get('id') }))), {
    initialValue: { kind: null as string | null, id: null as string | null },
  });

  readonly kind = computed<Kind | null>(() => this.world.kind(this.params().kind));
  readonly editor = signal<EntityEditor | null>(null);
  readonly data = signal<ProfileData | null>(null);
  readonly notes = signal<NotesData | null>(null);
  readonly generator = signal<GenerateData | null>(null);
  /** Whether the Generate panel is open. */
  readonly generating = signal(false);

  readonly slot = signal('main');
  /** A candidate being looked at before it is chosen. */
  readonly preview = signal<CandidateItem | null>(null);
  readonly choosing = signal(false);
  readonly chooseError = signal<string | null>(null);
  /** Files that failed to load, by url, so an image that is gone says so instead of showing a broken icon. */
  private readonly failed = signal<ReadonlySet<string>>(new Set());

  constructor() {
    effect(() => {
      const kind = this.kind();
      const slug = this.world.slug();
      const id = this.params().id;
      untracked(() => {
        this.slot.set('main');
        this.preview.set(null);
        this.generator()?.stop();
        this.generating.set(false);
        if (!kind || !slug || !id) {
          this.editor.set(null);
          this.data.set(null);
          this.notes.set(null);
          this.generator.set(null);
          return;
        }
        const editor = new EntityEditor(this.api, slug, kind);
        const data = new ProfileData(this.api, slug, id);
        this.editor.set(editor);
        this.data.set(data);
        const notes = new NotesData(this.api, slug, id);
        this.notes.set(notes);
        this.generator.set(new GenerateData(this.api, slug, id, kind.id, () => void data.loadAll()));
        void notes.load();
        void editor.load(id);
        void data.loadAll();
      });
    });
    // A saved field makes a new revision: read the list again so the history shows it.
    let seen: number | null = null;
    effect(() => {
      const revision = this.editor()?.entity()?.revision ?? null;
      const data = untracked(() => this.data());
      if (revision !== null && seen !== null && revision !== seen) void data?.loadRevisions();
      seen = revision;
    });
  }

  /** The parameter panel saved or chose something: read the record and its candidates again. */
  reloadAfterParameters(id: string, fields: boolean): void {
    if (fields) void this.editor()?.load(id);
    void this.data()?.loadAll();
  }

  ngOnDestroy(): void {
    this.generator()?.stop();
  }

  openGenerate(): void {
    this.generating.set(true);
    const generator = this.generator();
    if (generator && !generator.loaded()) void generator.load();
  }

  readonly slots = computed(() => slotsOf(this.data()?.chosen() ?? {}));
  /** The slots that have a chosen version: a run can start from the picture in one of them. */
  readonly chosenSlots = computed(() => Object.keys(this.data()?.chosen() ?? {}));
  readonly chosenNow = computed(() => this.data()?.chosen()[this.slot()] ?? null);

  private labelOf(): (key: string) => string {
    const fields = this.editor()?.fields() ?? [];
    return (key) => fields.find((f) => f.key === key)?.label ?? key;
  }

  readonly stream = computed(() => {
    const data = this.data();
    if (!data) return [];
    return buildStream(data.revisions(), data.runs(), data.choices(), this.labelOf(), this.notes()?.notes() ?? []);
  });

  readonly candidates = computed(() => {
    const data = this.data();
    if (!data) return [];
    return candidateItems(data.jobs(), data.choices()).filter((c) => fitsSlot(c, this.slot()));
  });

  /** What the hero shows: the previewed candidate, else the chosen version of the slot. */
  readonly shown = computed<{ runId: string; candidate: string; url: string; previewing: boolean } | null>(() => {
    const editor = this.editor();
    const entity = editor?.entity();
    if (!editor || !entity) return null;
    const preview = this.preview();
    if (preview) {
      return { runId: preview.runId, candidate: preview.candidate, url: this.api.candidateFileUrl(editor.slug, entity.id, preview.runId, preview.candidate), previewing: true };
    }
    const choice = this.chosenNow();
    if (!choice) return null;
    const url = `${this.api.chosenFileUrl(editor.slug, entity.id, choice.slot)}?v=${encodeURIComponent(choice.chosen_at)}`;
    return { runId: choice.run_id, candidate: choice.candidate, url, previewing: false };
  });

  readonly shownKind = computed(() => (this.shown() ? fileKind(this.shown()!.candidate) : null));
  readonly shownFailed = computed(() => {
    const s = this.shown();
    return s !== null && this.failed().has(s.url);
  });

  readonly status = computed(() => {
    const choice = this.chosenNow();
    const entity = this.editor()?.entity();
    if (!choice || !entity) return null;
    const found = freshness(choice, entity.revision, this.data()?.revisions() ?? [], this.labelOf());
    return {
      text: WORDS.status(shortId(choice.run_id), baseName(choice.candidate), choice.entity_revision, entity.revision),
      stale: found && found.chosenAt !== found.now ? (found.changed.length ? WORDS.stale(found.changed.map((c) => c.label).join(', ')) : WORDS.staleNone) : null,
      runId: choice.run_id,
      trace: traceQuery(choice.candidate),
    };
  });

  readonly traceQuery = traceQuery;

  label(slot: string): string {
    return slotLabel(slot);
  }

  name(candidate: string): string {
    return baseName(candidate);
  }

  pickSlot(slot: string): void {
    this.slot.set(slot);
    this.preview.set(null);
    this.chooseError.set(null);
  }

  /** The src of a candidate's tile. */
  thumb(item: CandidateItem): string {
    return this.api.candidateFileUrl(this.editor()!.slug, this.editor()!.entity()!.id, item.runId, item.candidate);
  }

  isCurrent(item: CandidateItem): boolean {
    return sameFile(this.chosenNow(), item);
  }

  look(item: CandidateItem): void {
    this.chooseError.set(null);
    this.preview.set(this.isCurrent(item) ? null : item);
  }

  isPreview(item: CandidateItem): boolean {
    const p = this.preview();
    return p !== null && p.runId === item.runId && p.candidate === item.candidate;
  }

  imageFailed(url: string): void {
    this.failed.update((s) => new Set(s).add(url));
  }

  async useThis(): Promise<void> {
    const item = this.preview();
    const data = this.data();
    if (!item || !data) return;
    this.choosing.set(true);
    this.chooseError.set(null);
    const problem = await data.choose(item.runId, item.candidate, this.slot());
    this.choosing.set(false);
    if (problem) this.chooseError.set(problem);
    else this.preview.set(null);
  }
}
