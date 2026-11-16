import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { DocsViewApi } from './docs-view-api';

describe('DocsViewApi', () => {
  let api: DocsViewApi;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    api = TestBed.inject(DocsViewApi);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('projects calls /api/ro/projects', () => {
    api.projects().subscribe();
    const req = http.expectOne('/api/ro/projects');
    expect(req.request.method).toBe('GET');
    req.flush({ projects: [] });
  });

  it('tree calls /api/ro/projects/{slug}/docs', () => {
    api.tree('my-game').subscribe();
    http.expectOne('/api/ro/projects/my-game/docs').flush({});
  });

  it('file sends the path as a query parameter', () => {
    api.file('my-game', 'docs/a b.md').subscribe();
    const req = http.expectOne((r) => r.url === '/api/ro/projects/my-game/docs/file');
    expect(req.request.params.get('path')).toBe('docs/a b.md');
    req.flush({});
  });

  it('source sends path, line and window', () => {
    api.source('my-game', 'ui/hint.gd', 40, 100).subscribe();
    const req = http.expectOne((r) => r.url === '/api/ro/projects/my-game/source');
    expect(req.request.params.get('path')).toBe('ui/hint.gd');
    expect(req.request.params.get('line')).toBe('40');
    expect(req.request.params.get('window')).toBe('100');
    req.flush({});
  });

  it('source leaves the line out when there is none', () => {
    api.source('my-game', 'ui/hint.gd').subscribe();
    const req = http.expectOne((r) => r.url === '/api/ro/projects/my-game/source');
    expect(req.request.params.has('line')).toBe(false);
    req.flush({});
  });

  it('search one project calls its docs/search route', () => {
    api.search('my-game', 'gpu lock').subscribe();
    const req = http.expectOne((r) => r.url === '/api/ro/projects/my-game/docs/search');
    expect(req.request.params.get('q')).toBe('gpu lock');
    expect(req.request.params.get('limit')).toBe('50');
    req.flush({});
  });

  it('searchAll calls /api/ro/docs/search', () => {
    api.searchAll('gpu lock').subscribe();
    const req = http.expectOne((r) => r.url === '/api/ro/docs/search');
    expect(req.request.params.get('q')).toBe('gpu lock');
    req.flush({});
  });

  it('encodes the project slug so it cannot add path segments', () => {
    api.tree('a/b').subscribe();
    http.expectOne('/api/ro/projects/a%2Fb/docs').flush({});
  });
});
