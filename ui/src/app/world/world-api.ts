import { HttpClient, HttpErrorResponse, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, catchError, map, throwError } from 'rxjs';
import {
  AttachedRun,
  Choice,
  Entity,
  EntityLink,
  Adapter,
  EntityQuery,
  Feeds,
  JobRequest,
  JobView,
  JsonObject,
  Kind,
  LinkType,
  Note,
  NoteAttachment,
  Pipeline,
  Revision,
  SourceItem,
  SourcePage,
  SourceType,
  Statistics,
  StoryGraph,
  Trace,
  Vocabulary,
  VocabularyCheck,
  VocabularyCheckBody,
  WorldApiError,
  WorldProject,
} from './world-models';

const BASE = '/api/v1';

const WORDS = {
  unreachable: 'The server did not answer.',
  status: (n: number) => `The server answered ${n}.`,
};

/** Turn whatever HttpClient failed with into the one error type pages deal with. */
export function toWorldError(err: unknown): WorldApiError {
  if (err instanceof WorldApiError) {
    return err;
  }
  if (err instanceof HttpErrorResponse) {
    const body = err.error?.error;
    if (body && typeof body === 'object' && typeof body.code === 'string') {
      return new WorldApiError(body.status ?? err.status, body.code, String(body.message ?? ''), body.field ?? null);
    }
    if (err.status === 0) {
      return new WorldApiError(0, 'unreachable', WORDS.unreachable, null);
    }
    return new WorldApiError(err.status, 'unexpected', WORDS.status(err.status), null);
  }
  return new WorldApiError(0, 'unexpected', err instanceof Error ? err.message : String(err), null);
}

function withNote<T extends object>(body: T, note?: string): T & { note?: string } {
  const trimmed = note?.trim();
  return trimmed ? { ...body, note: trimmed } : body;
}

/**
 * Every call to the v1 world-model API. The project is named in the path of each call that
 * belongs to one, so no call can reach another project's data by accident; pages pass the slug
 * they were built for. Writes get their `X-Studio-Request` header from the shared interceptor.
 */
@Injectable({ providedIn: 'root' })
export class WorldApi {
  private readonly http = inject(HttpClient);

  private call<T>(request: Observable<T>): Observable<T> {
    return request.pipe(catchError((err) => throwError(() => toWorldError(err))));
  }

  private p(slug: string, rest = ''): string {
    return `${BASE}/projects/${encodeURIComponent(slug)}${rest}`;
  }

  private e(slug: string, id: string, rest = ''): string {
    return this.p(slug, `/entities/${encodeURIComponent(id)}${rest}`);
  }

  // Projects
  projects(): Observable<WorldProject[]> {
    return this.call(this.http.get<{ projects: WorldProject[] }>(`${BASE}/projects`).pipe(map((r) => r.projects)));
  }

  createProject(body: { folder: string; slug: string; name: string }): Observable<WorldProject> {
    return this.call(this.http.post<WorldProject>(`${BASE}/projects`, body));
  }

  openProject(projectFile: string): Observable<WorldProject> {
    return this.call(this.http.post<WorldProject>(`${BASE}/projects`, { project_file: projectFile }));
  }

  removeProject(slug: string): Observable<{ slug: string; removed: boolean }> {
    return this.call(this.http.delete<{ slug: string; removed: boolean }>(this.p(slug)));
  }

  // Kinds and link types
  kinds(slug: string): Observable<Kind[]> {
    return this.call(this.http.get<{ kinds: Kind[] }>(this.p(slug, '/kinds')).pipe(map((r) => r.kinds)));
  }

  linkTypes(slug: string): Observable<LinkType[]> {
    return this.call(this.http.get<{ link_types: LinkType[] }>(this.p(slug, '/link-types')).pipe(map((r) => r.link_types)));
  }

  // Vocabulary (docs/vocabulary.md)
  /** The project's condition vocabulary, or null when it has none. */
  vocabulary(slug: string): Observable<Vocabulary | null> {
    return this.call(this.http.get<{ vocabulary: Vocabulary | null }>(this.p(slug, '/vocabulary')).pipe(map((r) => r.vocabulary)));
  }

  /** Problems, plain words and reads of a condition (or effects, a fact, a rule mode); problems are data, not errors. */
  checkVocabulary(slug: string, body: VocabularyCheckBody): Observable<VocabularyCheck> {
    return this.call(this.http.post<VocabularyCheck>(this.p(slug, '/vocabulary/check'), body));
  }

  // Story graph (docs/story_graph.md)
  /** Every entity and the story edges between them, or one entity's story nodes in full. */
  story(slug: string, entity?: string): Observable<StoryGraph> {
    const params: Record<string, string> = entity ? { entity } : {};
    return this.call(this.http.get<StoryGraph>(this.p(slug, '/story'), { params }));
  }

  // Entities
  entities(slug: string, query: EntityQuery = {}): Observable<Entity[]> {
    let params = new HttpParams();
    if (query.kind) params = params.set('kind', query.kind);
    if (query.tag) params = params.set('tag', query.tag);
    if (query.q) params = params.set('q', query.q);
    if (query.include_archived) params = params.set('include_archived', 'true');
    return this.call(this.http.get<{ entities: Entity[] }>(this.p(slug, '/entities'), { params }).pipe(map((r) => r.entities)));
  }

  entity(slug: string, id: string): Observable<Entity> {
    return this.call(this.http.get<Entity>(this.e(slug, id)));
  }

  createEntity(slug: string, kind: string, data: JsonObject, note?: string): Observable<Entity> {
    return this.call(this.http.post<Entity>(this.p(slug, '/entities'), withNote({ kind, data }, note)));
  }

  updateEntity(slug: string, id: string, revision: number, data: JsonObject, note?: string): Observable<Entity> {
    return this.call(this.http.put<Entity>(this.e(slug, id), withNote({ revision, data }, note)));
  }

  archiveEntity(slug: string, id: string, revision: number): Observable<Entity> {
    return this.call(this.http.post<Entity>(this.e(slug, id, '/archive'), { revision }));
  }

  restoreEntity(slug: string, id: string, revision: number): Observable<Entity> {
    return this.call(this.http.post<Entity>(this.e(slug, id, '/restore'), { revision }));
  }

  revertEntity(slug: string, id: string, revision: number, to: number): Observable<Entity> {
    return this.call(this.http.post<Entity>(this.e(slug, id, '/revert'), { revision, to }));
  }

  revisions(slug: string, id: string): Observable<Revision[]> {
    return this.call(this.http.get<{ revisions: Revision[] }>(this.e(slug, id, '/revisions')).pipe(map((r) => r.revisions)));
  }

  // Runs, candidates and choices
  runs(slug: string, id: string): Observable<AttachedRun[]> {
    return this.call(this.http.get<{ runs: AttachedRun[] }>(this.e(slug, id, '/runs')).pipe(map((r) => r.runs)));
  }

  /** The current choice per slot. */
  chosen(slug: string, id: string): Observable<Record<string, Choice>> {
    return this.call(this.http.get<{ chosen: Record<string, Choice> }>(this.e(slug, id, '/chosen')).pipe(map((r) => r.chosen)));
  }

  /** Every choice ever made, newest first. */
  choices(slug: string, id: string): Observable<Choice[]> {
    return this.call(this.http.get<{ choices: Choice[] }>(this.e(slug, id, '/choices')).pipe(map((r) => r.choices)));
  }

  /** The jobs made for an entity, each with the candidates it produced. */
  jobs(slug: string, id: string): Observable<JobView[]> {
    return this.call(this.http.get<{ jobs: JobView[] }>(this.e(slug, id, '/jobs')).pipe(map((r) => r.jobs)));
  }

  /** Start a run for an entity. Resolves the new job with its first (queued) run. */
  startJob(slug: string, id: string, request: JobRequest): Observable<JobView> {
    return this.call(this.http.post<JobView>(this.e(slug, id, '/jobs'), request));
  }

  /** One job with its runs (newest first) and candidates; poll it while a run is queued or running. */
  job(slug: string, jobId: string): Observable<JobView> {
    return this.call(this.http.get<JobView>(this.p(slug, `/jobs/${encodeURIComponent(jobId)}`)));
  }

  /** The pipelines a run can use for a kind of record in this project (its generation.json, else the tool's defaults). */
  pipelines(slug: string, entityKind: string): Observable<Pipeline[]> {
    const params = new HttpParams().set('entity_kind', entityKind);
    return this.call(this.http.get<{ pipelines: Pipeline[] }>(this.p(slug, '/pipelines'), { params }).pipe(map((r) => r.pipelines)));
  }

  /** Every shared source prompts are made from. */
  sources(slug: string): Observable<SourceItem[]> {
    return this.call(this.http.get<{ sources: SourceItem[] }>(this.p(slug, '/sources')).pipe(map((r) => r.sources)));
  }

  /** One source's page, with the runs of this project that read it. */
  source(slug: string, type: SourceType, id: string): Observable<SourcePage> {
    return this.call(this.http.get<SourcePage>(this.p(slug, `/sources/${encodeURIComponent(type)}/${encodeURIComponent(id)}`)));
  }

  /** The shared sources an entity's last run read. */
  feeds(slug: string, id: string): Observable<Feeds> {
    return this.call(this.http.get<Feeds>(this.e(slug, id, '/sources')));
  }

  /** The adapters this computer has, with whether each can run here. */
  adapters(): Observable<Adapter[]> {
    return this.call(this.http.get<{ adapters: Adapter[] }>(`${BASE}/adapters`).pipe(map((r) => r.adapters)));
  }

  /** One attempt of an attached run, stage by stage; the newest attempt when none is named. */
  trace(slug: string, id: string, runId: string, attempt?: string): Observable<Trace> {
    const params = attempt ? new HttpParams().set('attempt', attempt) : new HttpParams();
    return this.call(this.http.get<Trace>(this.e(slug, id, `/runs/${encodeURIComponent(runId)}/trace`), { params }));
  }

  /** Figures for a project's runs and assets. */
  statistics(slug: string): Observable<Statistics> {
    return this.call(this.http.get<Statistics>(this.p(slug, '/statistics')));
  }

  choose(slug: string, id: string, runId: string, candidate: string, slot: string, note?: string): Observable<Choice> {
    return this.call(this.http.post<Choice>(this.e(slug, id, '/chosen'), withNote({ run_id: runId, candidate, slot }, note)));
  }

  /** Where the file of the current choice in a slot is served (for an img src or a link). */
  chosenFileUrl(slug: string, id: string, slot: string): string {
    return this.e(slug, id, `/chosen/${encodeURIComponent(slot)}/file`);
  }

  /** Where the file of any candidate of an attached run is served. */
  candidateFileUrl(slug: string, id: string, runId: string, candidate: string): string {
    const path = candidate.split('/').map(encodeURIComponent).join('/');
    return this.e(slug, id, `/runs/${encodeURIComponent(runId)}/files/${path}`);
  }

  // Notes
  notes(slug: string, id: string): Observable<Note[]> {
    return this.call(this.http.get<{ notes: Note[] }>(this.e(slug, id, '/notes')).pipe(map((r) => r.notes)));
  }

  addNote(slug: string, id: string, text: string): Observable<Note> {
    return this.call(this.http.post<Note>(this.e(slug, id, '/notes'), { text }));
  }

  updateNote(slug: string, id: string, noteId: string, change: { text?: string; pinned?: boolean }): Observable<Note> {
    return this.call(this.http.patch<Note>(this.e(slug, id, `/notes/${encodeURIComponent(noteId)}`), change));
  }

  deleteNote(slug: string, id: string, noteId: string): Observable<unknown> {
    return this.call(this.http.delete(this.e(slug, id, `/notes/${encodeURIComponent(noteId)}`)));
  }

  /** An image goes up as the raw body, not JSON; the name travels in a header (ASCII only). */
  uploadNoteImage(slug: string, id: string, noteId: string, file: Blob, name: string): Observable<NoteAttachment> {
    const headers = { 'Content-Type': file.type, 'X-File-Name': encodeURIComponent(name).slice(0, 100) };
    return this.call(this.http.post<NoteAttachment>(this.e(slug, id, `/notes/${encodeURIComponent(noteId)}/attachments`), file, { headers }));
  }

  noteImageUrl(slug: string, id: string, noteId: string, attachmentId: string): string {
    return this.e(slug, id, `/notes/${encodeURIComponent(noteId)}/attachments/${encodeURIComponent(attachmentId)}`);
  }

  // Links
  links(slug: string, id: string): Observable<EntityLink[]> {
    return this.call(
      this.http.get<{ links: EntityLink[] }>(this.e(slug, id, '/links'), { params: { direction: 'both' } }).pipe(map((r) => r.links)),
    );
  }

  createLink(slug: string, type: string, source: string, target: string): Observable<unknown> {
    return this.call(this.http.post(this.p(slug, '/links'), { type, source, target }));
  }

  removeLink(slug: string, linkId: string): Observable<unknown> {
    return this.call(this.http.delete(this.p(slug, `/links/${encodeURIComponent(linkId)}`)));
  }
}
