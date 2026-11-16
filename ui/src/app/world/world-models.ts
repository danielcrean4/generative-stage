import type { ParamModel } from './parametric-model';
/** Shapes of the v1 world-model API (docs/api.md). */

export type JsonObject = Record<string, unknown>;

export interface WorldProject {
  slug: string;
  name?: string;
  folder?: string;
  project_file: string;
  /** Set when a registered project cannot be loaded; then only slug, project_file and problem exist. */
  problem?: string | null;
}

/** How the app groups a kind (core/kinds.py FAMILIES); null or missing is listed under Other. */
export type KindFamily = 'prop' | 'character' | 'setting' | 'script' | 'stage';
/** Whether a script kind's lines run in order or branch. */
export type ScriptForm = 'linear' | 'branching';

export interface Kind {
  id: string;
  label: string;
  plural_label: string;
  icon: string;
  family?: KindFamily | null;
  /** Set only on a kind whose family is script. */
  form?: ScriptForm | null;
  title_field: string;
  brief_field: string | null;
  tags_field: string | null;
  schema_file: string;
  schema: JsonObject;
  /** The parameter model when the kind is parametric (core/parameters.py), else null. */
  parameters?: ParamModel | null;
}

export interface LinkType {
  id: string;
  label: string;
  inverse_label: string;
  source_kinds: string[];
  target_kinds: string[];
}

export interface Entity {
  id: string;
  kind: string;
  revision: number;
  archived: boolean;
  title: string;
  data: JsonObject;
  created_at: string;
  updated_at: string;
}

export interface Revision {
  entity_id: string;
  revision: number;
  archived: boolean;
  data: JsonObject;
  note: string | null;
  created_at: string;
}

export interface LinkOther {
  id: string;
  kind: string;
  title: string;
  archived: boolean;
}

export interface EntityLink {
  id: string;
  type: string;
  source: string;
  target: string;
  created_at: string;
  direction: 'out' | 'in';
  label: string;
  other: LinkOther;
}

/** A run attached to an entity (GET .../entities/{id}/runs). */
export interface AttachedRun {
  entity_id: string;
  run_id: string;
  entity_revision: number;
  note: string | null;
  attached_at: string;
}

/** A candidate chosen for a slot of an entity (GET .../chosen and .../choices). */
export interface Choice {
  entity_id: string;
  slot: string;
  run_id: string;
  candidate: string;
  entity_revision: number;
  note: string | null;
  chosen_at: string;
}

export type Verdict = 'pass' | 'review' | 'fail';

/** A candidate a job made (GET .../entities/{id}/jobs). `candidate` is its path inside the run. */
export interface JobCandidate {
  id: string;
  job_id: string;
  candidate: string | null;
  verdict: Verdict | null;
  note: string;
  created_at: string;
}

/** One step of a run (GET .../jobs/{id}): a stage of the pipeline and where it is. */
export interface RunStep {
  id: string;
  label: string;
  status: 'pending' | 'running' | 'succeeded' | 'failed' | 'skipped';
}

export type RunStatus = 'queued' | 'running' | 'succeeded' | 'failed';

export interface JobRun {
  id: string;
  status: RunStatus;
  log_tail: string;
  steps: RunStep[];
}

export interface JobView {
  job: { id: string; entity_id: string; entity_revision: number };
  candidates: JobCandidate[];
  /** Newest first. Absent in older fixtures. */
  runs?: JobRun[];
  /** Whether the job's run is attached to the record, so its trace can be opened. */
  attached?: boolean;
}

/** A choice a pipeline file declares (docs/pipeline_files.md, "Choices"): a pick from `options`, or a number from `min` to `max`. */
export interface PipelineChoice {
  label: string;
  /** Absent for an optional choice (start_image). */
  default?: string | number;
  options?: string[];
  /** start_image: the slots whose chosen picture a run can start from. */
  slots?: string[];
  min?: number;
  max?: number;
}

/** A pipeline a run can use (GET /api/v1/pipelines). `adapter_kind` is null for a stage that runs no model. */
export interface Pipeline {
  id: string;
  name: string;
  kind: string;
  entity_kinds: string[] | null;
  stages: { id: string; label: string; tool: string; adapter_kind: string | null }[];
  choices: Record<string, PipelineChoice>;
}

/** An adapter this computer has (GET /api/v1/adapters). `unmet` says, in sentences, why it cannot run here. */
export interface Adapter {
  id: string;
  kind: string;
  description: string;
  default: boolean;
  runnable: boolean;
  unmet: string[];
}

/** What POST .../entities/{id}/jobs takes. */
export interface JobRequest {
  pipeline: string;
  prompt: string;
  adapters?: Record<string, string>;
  choices?: Record<string, string | number>;
}

export interface EntityQuery {
  kind?: string;
  tag?: string;
  q?: string;
  include_archived?: boolean;
}

/** The one error shape every v1 call answers with. `field` is a JSON pointer into the request body. */
export class WorldApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly field: string | null,
  ) {
    super(message);
    this.name = 'WorldApiError';
  }

  get isConflict(): boolean {
    return this.code === 'revision_conflict';
  }
}

export interface MentionRef {
  kind: string;
  id: string;
}

export interface NoteAttachment {
  id: string;
  name: string;
  media_type: string;
  size: number;
}

/** A note on an entity (docs/api.md, Notes). Not a revision. */
export interface Note {
  id: string;
  created_at: string;
  updated_at: string;
  text: string;
  pinned: boolean;
  mentions: MentionRef[];
  attachments: NoteAttachment[];
}

export type StageStatus = 'completed' | 'errored' | 'running' | 'not_run' | 'supplied';

export interface TraceFile {
  name: string;
  kind: 'image' | 'model' | 'other';
  media_type: string | null;
  size: number;
  /** The path inside the run that choosing takes. */
  candidate: string;
  url: string;
}

export interface NamedValue {
  name: string;
  value: string | number | boolean;
}

export interface TraceGate {
  file: string | null;
  outcome: Verdict | null;
  reasons: string[];
  measures: NamedValue[];
  limits: NamedValue[];
}

/** Where a piece of a prompt came from. `link` is the page that shows it, when there is one. */
export interface PartLink {
  type: 'style' | 'motif' | 'contract' | 'entity';
  id: string;
  /** For an entity link, the kind (the path of its profile). */
  kind?: string;
  /** The file has changed since the run read it. */
  changed?: boolean;
}

export interface PromptPart {
  text: string;
  start: number | null;
  end: number | null;
  source: { kind: string; id?: string; key?: string; version?: number; sha256?: string; link: PartLink | null };
}

export interface TraceStage {
  id: string;
  folder: string | null;
  retry: number;
  label: string;
  tool: string | null;
  status: StageStatus;
  error: string | null;
  reused: boolean;
  reused_from: string | null;
  seconds: number | null;
  started: string | null;
  finished: string | null;
  times: string | null;
  seed: number | null;
  key: string | null;
  adapter: Record<string, string | number | boolean>;
  prompt: string | null;
  negative: string | null;
  /** The prompt as ordered pieces whose text joins to `prompt`; null for a run that did not record them. */
  prompt_parts: PromptPart[] | null;
  negative_parts: PromptPart[] | null;
  params: JsonObject | null;
  reads: JsonObject | null;
  inputs: { name: string; from: string | null; sha256: string | null }[];
  gates: TraceGate[];
  files: TraceFile[];
}

/** A run attempt, stage by stage (GET .../entities/{id}/runs/{run_id}/trace). */
export interface Trace {
  run_id: string;
  attempt_id: string;
  attempts: { attempt_id: string; status: string | null; started: string | null }[];
  status: string | null;
  error: string | null;
  problem: string | null;
  started: string | null;
  finished: string | null;
  seconds: number | null;
  seed: number | null;
  sources: JsonObject | null;
  tries: JsonObject[];
  entity: { id: string; kind: string; title: string };
  candidates: { candidate: string; verdict: Verdict | null }[];
  chosen: Record<string, Choice>;
  stages: TraceStage[];
}

/** The figures of a project's runs (GET .../statistics). */
export interface Statistics {
  runs: { total: number; completed: number; errored: number; other: number; seconds: number };
  by_day: { day: string; completed: number; errored: number; other: number }[];
  by_stage: {
    stage: string;
    ran: number;
    reused: number;
    errored: number;
    total_seconds: number;
    average_seconds: number;
    slowest_seconds: number;
  }[];
  assets: { candidates: number; choices: number; chosen_slots: number; entities: number; entities_with_choice: number };
}

export type SourceType = 'style' | 'motif' | 'contract';

/** A row of the Sources index (GET .../sources). */
export interface SourceItem {
  type: SourceType;
  id: string;
  name: string;
  set: string;
  pipelines: string[];
}

/** One run of this project that read a source (GET .../sources/{type}/{id}, `used_by`). */
export interface SourceReader {
  entity: { id: string; kind: string; title: string };
  run_id: string;
  attempt_id: string;
  started: string | null;
  status: string | null;
  /** The run read an older version of the file. */
  changed: boolean;
  thumbnail: string | null;
}

/** A source's page: its file and words, where it lives, who uses it. */
export interface SourcePage {
  type: SourceType;
  id: string;
  name: string;
  set: string;
  location: string;
  editable: boolean;
  sha256: string;
  content: JsonObject;
  extends: { id: string; name: string }[];
  texts: { label: string; key: string; text: string; from: string }[];
  note: string | null;
  pipelines: { id: string; name: string }[];
  used_by: SourceReader[];
}

/** A source the entity's last run read (GET .../entities/{id}/sources). `id` is null when it has no page. */
export interface FeedRef {
  type: SourceType | 'pipeline';
  id: string | null;
  name: string;
  changed: boolean;
}

export interface Feeds {
  run_id: string | null;
  attempt_id: string | null;
  sources: FeedRef[];
}

/** A project's condition vocabulary file, as written (docs/vocabulary.md). */
export interface VocabularyFact {
  pattern: string;
  type: string;
  doc?: string;
}

export interface VocabularyOperator {
  types: string[];
  operand: 'same' | 'member' | 'list';
  text: string;
}

export interface VocabularyArgument {
  type: string;
  description?: string;
  id_kind?: string;
  [constraint: string]: unknown;
}

export interface VocabularyEffect {
  doc?: string;
  args: Record<string, VocabularyArgument>;
  required?: string[];
}

export interface Vocabulary {
  format: string;
  format_version: number;
  source?: string;
  types: Record<string, { json: string; doc?: string }>;
  facts: VocabularyFact[];
  operators: Record<string, VocabularyOperator>;
  id_kinds?: Record<string, { doc?: string; entity_kinds?: string[]; field?: string }>;
  effects?: { key: string; kinds: Record<string, VocabularyEffect> };
  rule_modes?: Record<string, { doc?: string }>;
  shorthand?: { keys: string[]; doc?: string };
}

/** One fact a condition reads, as the check route reports it. */
export interface FactRead {
  path: string;
  pattern: string;
  type: string;
  doc: string;
  ids: { id_kind: string; id: string }[];
}

/** What the check route answers for a condition, effects, a fact or a rule mode. */
export interface VocabularyCheck {
  problems: { field: string; message: string }[];
  text?: string;
  reads?: FactRead[];
  shorthand?: boolean;
}

export type VocabularyCheckBody =
  | { condition: unknown }
  | { effects: unknown }
  | { fact: unknown }
  | { rule_mode: unknown };

// Story graph (docs/story_graph.md)

/** A condition where it sits in the story, in plain words with what it reads. */
export interface StoryCondition {
  pointer: string;
  json: unknown;
  text: string;
  reads: FactRead[];
  problems: { field: string; message: string }[];
  shorthand: boolean;
}

export interface StoryEffect {
  pointer: string;
  json: unknown;
  text: string;
  problems: { field: string; message: string }[];
}

/** An entity (pointer "") or a marked node inside one (id "<entity>#<pointer>"). */
export interface StoryNode {
  id: string;
  entity: string;
  kind: string;
  pointer: string;
  label: string;
  text: string | null;
  conditions: StoryCondition[];
  effects: StoryEffect[];
  inner?: number;
  condition_count?: number;
  problem_count?: number;
}

export type StoryEdgeKind = 'contains' | 'edge' | 'sequence' | 'ref' | 'effect' | 'reads' | 'link';

export interface StoryEdge {
  id: string;
  kind: StoryEdgeKind;
  from: string;
  to: string | null;
  label: string;
  text: string | null;
  pointer?: string;
  ends?: boolean;
  problem?: string | null;
  count?: number;
  conditions: StoryCondition[];
  effects: StoryEffect[];
}

export interface StoryGraph {
  view: 'overview' | 'focus';
  entity?: string;
  nodes: StoryNode[];
  edges: StoryEdge[];
}
