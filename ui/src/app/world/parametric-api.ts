import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, catchError, throwError } from 'rxjs';
import { BatchView, ParametricInfo, PreviewView, Triage, TriageVerdict } from './parametric-model';
import { toWorldError } from './world-api';
import { JsonObject } from './world-models';

/** The parametric routes (server/authoring/parametric_api.py). Writes get their header from the shared interceptor. */
@Injectable({ providedIn: 'root' })
export class ParametricApi {
  private readonly http = inject(HttpClient);

  private base(slug: string, rest: string): string {
    return `/api/v1/projects/${encodeURIComponent(slug)}/parametric/${rest}`;
  }

  private call<T>(request: Observable<T>): Observable<T> {
    return request.pipe(catchError((err) => throwError(() => toWorldError(err))));
  }

  info(slug: string, kind: string): Observable<ParametricInfo> {
    return this.call(this.http.get<ParametricInfo>(this.base(slug, encodeURIComponent(kind))));
  }

  preview(slug: string, kind: string, row: JsonObject): Observable<PreviewView> {
    return this.call(this.http.post<PreviewView>(this.base(slug, `${encodeURIComponent(kind)}/preview`), { row }));
  }

  keep(slug: string, kind: string, row: JsonObject): Observable<{ run_id: string; candidate: string }> {
    return this.call(this.http.post<{ run_id: string; candidate: string }>(this.base(slug, `${encodeURIComponent(kind)}/candidates`), { row }));
  }

  makeBatch(slug: string, kind: string, body: { cross: Record<string, string[]>; seed: number; count: number }): Observable<BatchView> {
    return this.call(this.http.post<BatchView>(this.base(slug, `${encodeURIComponent(kind)}/batches`), body));
  }

  batch(slug: string, id: string): Observable<BatchView> {
    return this.call(this.http.get<BatchView>(this.base(slug, `batches/${encodeURIComponent(id)}`)));
  }

  triage(slug: string, id: string, tile: string, verdict: TriageVerdict | null, note: string): Observable<BatchView> {
    return this.call(this.http.put<BatchView>(this.base(slug, `batches/${encodeURIComponent(id)}/triage`), { [tile]: { verdict, note } } satisfies Record<string, { verdict: TriageVerdict | null; note: string }>));
  }

  attachRun(slug: string, entityId: string, runId: string): Observable<unknown> {
    return this.call(this.http.post(`/api/v1/projects/${encodeURIComponent(slug)}/entities/${encodeURIComponent(entityId)}/runs`, { run_id: runId }));
  }
}

export type { Triage };
