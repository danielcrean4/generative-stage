import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { RunViewApi } from './run-view-api';

describe('RunViewApi', () => {
  let api: RunViewApi;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    api = TestBed.inject(RunViewApi);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('health calls /api/ro/health', () => {
    api.health().subscribe();
    const req = http.expectOne('/api/ro/health');
    expect(req.request.method).toBe('GET');
    req.flush({ ok: true, runs_root: '/x' });
  });

  it('runs calls /api/ro/runs with the limit', () => {
    api.runs(25).subscribe();
    const req = http.expectOne((r) => r.url === '/api/ro/runs');
    expect(req.request.params.get('limit')).toBe('25');
    req.flush({ runs: [], total: 0, limit: 25 });
  });

  it('run calls /api/ro/runs/{run_id}', () => {
    api.run('abc-1').subscribe();
    http.expectOne('/api/ro/runs/abc-1').flush({});
  });

  it('attempt calls /api/ro/runs/{run_id}/attempts/{attempt_id}', () => {
    api.attempt('abc-1', '2026-x').subscribe();
    http.expectOne('/api/ro/runs/abc-1/attempts/2026-x').flush({});
  });

  it('encodes ids so they cannot add path segments', () => {
    api.run('a/b').subscribe();
    http.expectOne('/api/ro/runs/a%2Fb').flush({});
  });

  it('fileText fetches the url the server gave, as text', () => {
    api.fileText('/api/ro/runs/r/attempts/a/files/mesh/step.log').subscribe();
    const req = http.expectOne('/api/ro/runs/r/attempts/a/files/mesh/step.log');
    expect(req.request.responseType).toBe('text');
    req.flush('log line');
  });
});
