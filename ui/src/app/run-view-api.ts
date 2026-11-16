import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Observable } from 'rxjs';

/** Response shapes of the read-only run view server (server/docs/run_view.md). */

export interface RunViewHealth {
  ok: boolean;
  runs_root: string;
}

export interface RunSummary {
  run_id: string;
  latest_attempt_id: string | null;
  status: string | null;
  error: string | null;
  started: string | null;
  finished: string | null;
  stages: string[];
  modified: string;
  /** Present when the latest attempt could not be read. */
  problem?: string | null;
}

export interface RunsResponse {
  runs: RunSummary[];
  total: number;
  limit: number;
}

export interface AttemptSummary {
  attempt_id: string;
  status: string | null;
  error: string | null;
  started: string | null;
  finished: string | null;
  seed: number | null;
  stages: string[];
  problem?: string | null;
}

export interface RunFile {
  name: string;
  size: number;
  media_type: string;
  url: string;
}

export interface RunDetailResponse {
  run_id: string;
  latest_attempt_id: string | null;
  attempts: AttemptSummary[];
  root_files: RunFile[];
}

export interface MeshTry {
  try: number;
  seed: number | null;
  report: string | null;
  passed: boolean | null;
  reasons: string[];
}

/** `passed` is null when the report has no verdict of its own (the image check). */
export interface GateReport {
  file: string;
  url: string;
  passed: boolean | null;
  /** Gate v2 reports say `pass`, `review` or `fail`; older reports have none (null). */
  verdict?: string | null;
  reasons: string[];
  /** An object for most gates; the image check lists the images it opened. */
  measures: Record<string, unknown> | unknown[] | null;
  thresholds: Record<string, unknown> | null;
}

export interface StageDetail {
  stage: string;
  recorded: boolean;
  cache_key: string | null;
  reused: boolean | null;
  status: string | null;
  seed: number | null;
  seed_used: number | null;
  tries: MeshTry[] | null;
  recipe: Record<string, unknown> | null;
  gates: GateReport[];
  files: RunFile[];
  /** Sent by the server but not in the documented table. */
  retry_errors?: unknown[];
}

export interface AttemptDetail {
  run_id: string;
  attempt_id: string;
  status: string | null;
  error: string | null;
  started: string | null;
  finished: string | null;
  seed: number | null;
  recipe: Record<string, unknown> | null;
  problem: string | null;
  stages: StageDetail[];
}

export const RUN_VIEW_START_COMMAND = 'uv run python -m authoring.readonly_server --port 8781';

export const RUN_VIEW_BASE = '/api/ro';

/** Turns any failed call to the read-only server (run view and docs view) into a sentence a developer can act on. */
export function describeRunViewError(err: unknown): { message: string; serverDown: boolean } {
  if (err instanceof HttpErrorResponse) {
    if (err.status === 0 || err.status === 502 || err.status === 503 || err.status === 504) {
      return {
        message: 'The read-only Studio server on port 8781 is not reachable.',
        serverDown: true,
      };
    }
    const body = err.error as { error?: string } | string | null;
    const detail = typeof body === 'object' && body && body.error ? body.error : err.statusText;
    return { message: `The read-only Studio server answered ${err.status}: ${detail}`, serverDown: false };
  }
  return { message: err instanceof Error ? err.message : String(err), serverDown: false };
}

/** Every call to the read-only run view server (port 8781, proxied at /api/ro). */
@Injectable({ providedIn: 'root' })
export class RunViewApi {
  private readonly http = inject(HttpClient);

  health(): Observable<RunViewHealth> {
    return this.http.get<RunViewHealth>(`${RUN_VIEW_BASE}/health`);
  }

  runs(limit: number): Observable<RunsResponse> {
    return this.http.get<RunsResponse>(`${RUN_VIEW_BASE}/runs`, { params: { limit } });
  }

  run(runId: string): Observable<RunDetailResponse> {
    return this.http.get<RunDetailResponse>(`${RUN_VIEW_BASE}/runs/${encodeURIComponent(runId)}`);
  }

  attempt(runId: string, attemptId: string): Observable<AttemptDetail> {
    return this.http.get<AttemptDetail>(
      `${RUN_VIEW_BASE}/runs/${encodeURIComponent(runId)}/attempts/${encodeURIComponent(attemptId)}`,
    );
  }

  /** Text of a log or json file, by the `url` the server gave for it. */
  fileText(url: string): Observable<string> {
    return this.http.get(url, { responseType: 'text' });
  }
}
