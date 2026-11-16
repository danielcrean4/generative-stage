import { Adapter, JobRequest, Pipeline, PipelineChoice, RunStatus } from './world-models';

/**
 * The rules behind the Generate panel, with no drawing in them: which adapter kinds a pipeline needs, which adapters
 * can be picked and why one cannot, the form's starting values, the request it makes and the words for a run's state.
 */

/** What a person has chosen so far. A kind with no adapter picked uses this computer's default for it. */
export interface GenerateForm {
  pipeline: string;
  prompt: string;
  adapters: Record<string, string>;
  choices: Record<string, string | number>;
}

const KIND_NAMES: Record<string, string> = {
  image: 'Image model',
  'image-to-mesh': '3D model',
  material: 'Material model',
  rig: 'Rigging',
  motion: 'Motion',
};

export function kindLabel(kind: string): string {
  return KIND_NAMES[kind] ?? kind;
}

/** The order the choices are shown in; a pipeline offers some of these, never others. */
export const CHOICE_ORDER = ['style', 'motif', 'hair_colour', 'seed', 'candidates', 'start_image'];

/** The choice of a picture to start from; it is optional, so it has no default and may be left empty. */
export const START_IMAGE = 'start_image';

/** The adapter kinds a pipeline's stages run, in stage order, each once. */
export function adapterKinds(pipeline: Pipeline): string[] {
  return [...new Set(pipeline.stages.map((s) => s.adapter_kind).filter((k): k is string => k !== null))];
}

/** The choices a pipeline declares, in a fixed order. */
export function choiceList(pipeline: Pipeline): { name: string; spec: PipelineChoice }[] {
  return CHOICE_ORDER.filter((name) => name in pipeline.choices).map((name) => ({ name, spec: pipeline.choices[name] }));
}

/** A new form for a pipeline: every declared choice that has a default at it, no adapter picked. */
export function formFor(pipeline: Pipeline, prompt: string): GenerateForm {
  const choices: Record<string, string | number> = {};
  for (const { name, spec } of choiceList(pipeline)) if (spec.default !== undefined) choices[name] = spec.default;
  return { pipeline: pipeline.id, prompt, adapters: {}, choices };
}

export interface AdapterOption {
  id: string;
  /** What the select shows: the id, "(default)" and, when it cannot run here, the first reason. */
  label: string;
  runnable: boolean;
  reasons: string[];
}

/** The adapters of one kind that can be picked, the default first. An adapter that cannot run here is listed, with why. */
export function adapterOptions(adapters: Adapter[], kind: string): AdapterOption[] {
  return adapters
    .filter((a) => a.kind === kind)
    .sort((a, b) => Number(b.default) - Number(a.default) || a.id.localeCompare(b.id))
    .map((a) => ({
      id: a.id,
      label: `${a.id}${a.default ? ' (default)' : ''}${a.runnable ? '' : ` - cannot run here: ${a.unmet[0] ?? 'unavailable'}`}`,
      runnable: a.runnable,
      reasons: a.unmet,
    }));
}

/** The adapter a stage of this kind will use: the one picked, else this computer's default. */
export function adapterUsed(adapters: Adapter[], form: GenerateForm, kind: string): Adapter | null {
  const picked = form.adapters[kind];
  return adapters.find((a) => a.kind === kind && (picked ? a.id === picked : a.default)) ?? null;
}

/** Sentences for what stops a run starting, in order; none when it can start. */
export function problems(pipeline: Pipeline | null, adapters: Adapter[], form: GenerateForm): string[] {
  if (!pipeline) return ['Choose a pipeline.'];
  const found: string[] = [];
  if (!form.prompt.trim() && !form.choices[START_IMAGE]) found.push('Describe what to make.');
  for (const { name, spec } of choiceList(pipeline)) {
    const value = form.choices[name];
    if (spec.default === undefined && (value === undefined || value === '')) continue; // an optional choice may stay unset
    if (name === START_IMAGE) {
      if (!(spec.slots ?? []).includes(String(value))) found.push(`${spec.label}: choose one of the pictures.`);
    } else if (spec.options) {
      if (!spec.options.includes(String(value))) found.push(`${spec.label}: choose one of the options.`);
    } else if (typeof value !== 'number' || !Number.isInteger(value) || value < (spec.min ?? 0) || value > (spec.max ?? 0)) {
      found.push(`${spec.label}: enter a whole number from ${spec.min} to ${spec.max}.`);
    }
  }
  for (const kind of adapterKinds(pipeline)) {
    const used = adapterUsed(adapters, form, kind);
    if (!used) found.push(`${kindLabel(kind)}: this computer has none set up.`);
    else if (!used.runnable) found.push(`${kindLabel(kind)}: ${used.id} cannot run here (${used.unmet.join('; ') || 'unavailable'}).`);
  }
  return found;
}

/** The request for a form: adapters only for kinds the pipeline runs, every choice the pipeline declares. */
export function requestOf(pipeline: Pipeline, form: GenerateForm): JobRequest {
  const kinds = adapterKinds(pipeline);
  const adapters = Object.fromEntries(Object.entries(form.adapters).filter(([kind, id]) => id && kinds.includes(kind)));
  const choices = Object.fromEntries(
    choiceList(pipeline)
      .filter(({ name }) => form.choices[name] !== undefined && form.choices[name] !== '')
      .map(({ name }) => [name, form.choices[name]]),
  );
  return { pipeline: pipeline.id, prompt: form.prompt.trim(), ...(Object.keys(adapters).length ? { adapters } : {}), choices };
}

/** The text a record gives a prompt to start from: its brief, else its title. */
export function promptFor(title: string, brief: unknown): string {
  return typeof brief === 'string' && brief.trim() ? brief.trim() : title;
}

export function isActive(status: RunStatus | undefined): boolean {
  return status === 'queued' || status === 'running';
}

const STATUS_WORDS: Record<RunStatus, string> = {
  queued: 'Waiting to start',
  running: 'Running',
  succeeded: 'Done',
  failed: 'Failed',
};

export function statusWords(status: RunStatus): string {
  return STATUS_WORDS[status];
}
