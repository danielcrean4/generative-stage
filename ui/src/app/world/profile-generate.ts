import { Component, computed, effect, input, output, signal, untracked } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { RouterLink } from '@angular/router';
import { GenerateData } from './generate-data';
import { GenerateForm, START_IMAGE, adapterKinds, adapterOptions, choiceList, formFor, kindLabel, problems, promptFor, requestOf, statusWords } from './generate-model';
import { shortId, slotLabel } from './profile-model';

/** Every word in the panel. */
const WORDS = {
  title: 'Generate',
  close: 'Close',
  loading: 'Loading…',
  pipeline: 'What to make',
  prompt: 'Describe it',
  none: 'No pipeline makes this kind of record yet.',
  start: 'Start',
  starting: 'Starting…',
  busy: 'A run is going. You can start another when it ends.',
  kind: kindLabel,
  runLine: (id: string) => `Run ${id}.`,
  made: (n: number) => `${n === 1 ? '1 candidate is' : `${n} candidates are`} in the strip below.`,
  openRun: 'See how it was made',
  openFailed: 'See where it stopped',
  unset: 'Not set',
  noPicture: 'Start from the description',
  noChosen: 'Nothing is chosen yet',
  useDefault: (id: string | null) => (id ? `Default (${id})` : 'Default (none set up)'),
};

/**
 * The panel that starts a run for one record: a pipeline that serves its kind, the adapters it needs (this computer's
 * default unless one is picked; ones that cannot run here say why), the choices the pipeline declares, and then live
 * status of the run with a link to how it was made. What the form may hold, and the request it makes, are the rules in
 * generate-model.ts.
 */
@Component({
  selector: 'app-profile-generate',
  imports: [RouterLink, MatButtonModule],
  templateUrl: './profile-generate.html',
  styleUrl: './profile-generate.scss',
})
export class ProfileGenerate {
  readonly w = WORDS;
  readonly data = input.required<GenerateData>();
  readonly kind = input.required<string>();
  readonly entityId = input.required<string>();
  readonly title = input.required<string>();
  readonly brief = input<unknown>(null);
  /** The slots this record has a chosen picture for: a run can start from one of them. */
  readonly chosenSlots = input<string[]>([]);
  readonly closed = output<void>();

  readonly form = signal<GenerateForm>({ pipeline: '', prompt: '', adapters: {}, choices: {} });
  readonly startError = signal<string | null>(null);
  readonly statusWords = statusWords;
  readonly shortId = shortId;
  readonly startImage = START_IMAGE;
  readonly slotLabel = slotLabel;

  readonly pipeline = computed(() => this.data().pipelines().find((p) => p.id === this.form().pipeline) ?? null);
  readonly choices = computed(() => (this.pipeline() ? choiceList(this.pipeline()!) : []));
  readonly kinds = computed(() => (this.pipeline() ? adapterKinds(this.pipeline()!) : []));
  readonly stopping = computed(() => (this.pipeline() ? problems(this.pipeline(), this.data().adapters(), this.form()) : []));
  readonly canStart = computed(() => this.pipeline() !== null && this.stopping().length === 0 && !this.data().active());

  constructor() {
    // Start from the first pipeline the server lists for this kind, with the record's brief as the prompt.
    effect(() => {
      const first = this.data().pipelines()[0];
      untracked(() => {
        if (first && !this.form().pipeline) this.form.set(formFor(first, promptFor(this.title(), this.brief())));
      });
    });
  }

  /** The slots a start-image choice may name: those the pipeline lists and this record has a picture for. */
  pictureSlots(slots: string[] | undefined): string[] {
    return (slots ?? []).filter((s) => this.chosenSlots().includes(s));
  }

  options(kind: string) {
    return adapterOptions(this.data().adapters(), kind);
  }

  defaultLabel(kind: string): string {
    return WORDS.useDefault(this.data().adapters().find((a) => a.kind === kind && a.default)?.id ?? null);
  }

  pickPipeline(id: string): void {
    const next = this.data().pipelines().find((p) => p.id === id);
    if (!next) return;
    const kept = adapterKinds(next);
    const adapters = Object.fromEntries(Object.entries(this.form().adapters).filter(([kind]) => kept.includes(kind)));
    this.form.set({ ...formFor(next, this.form().prompt), adapters });
    this.startError.set(null);
  }

  setPrompt(value: string): void {
    this.form.update((f) => ({ ...f, prompt: value }));
  }

  setChoice(name: string, value: string): void {
    this.form.update((f) => ({ ...f, choices: { ...f.choices, [name]: value } }));
  }

  setPicture(value: string): void {
    this.form.update((f) => ({ ...f, choices: { ...f.choices, [START_IMAGE]: value } }));
  }

  setNumber(name: string, value: string): void {
    this.form.update((f) => ({ ...f, choices: { ...f.choices, [name]: value.trim() === '' ? Number.NaN : Number(value) } }));
  }

  setAdapter(kind: string, id: string): void {
    this.form.update((f) => ({ ...f, adapters: { ...f.adapters, [kind]: id } }));
  }

  async start(): Promise<void> {
    const pipeline = this.pipeline();
    if (!pipeline || !this.canStart()) return;
    this.startError.set(await this.data().start(requestOf(pipeline, this.form())));
  }
}
