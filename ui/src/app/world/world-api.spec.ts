import { TestBed } from '@angular/core/testing';
import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { studioHeaderInterceptor } from '../studio-header.interceptor';
import { WorldApi } from './world-api';
import { WorldApiError } from './world-models';

describe('WorldApi', () => {
  let api: WorldApi;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideRouter([]), provideHttpClient(withInterceptors([studioHeaderInterceptor])), provideHttpClientTesting()],
    });
    api = TestBed.inject(WorldApi);
    http = TestBed.inject(HttpTestingController);
  });
  afterEach(() => http.verify());

  it('lists projects', () => {
    let got: unknown;
    api.projects().subscribe((p) => (got = p));
    http.expectOne('/api/v1/projects').flush({ projects: [{ slug: 'sample', project_file: '/x' }] });
    expect(got).toEqual([{ slug: 'sample', project_file: '/x' }]);
  });

  it('creates a project, and opens one from its file, with the write header', () => {
    api.createProject({ folder: '/work/sample', slug: 'sample', name: 'Sample' }).subscribe();
    const create = http.expectOne('/api/v1/projects');
    expect(create.request.method).toBe('POST');
    expect(create.request.body).toEqual({ folder: '/work/sample', slug: 'sample', name: 'Sample' });
    expect(create.request.headers.get('X-Studio-Request')).toBe('1');
    create.flush({});

    api.openProject('/work/sample/studio.project.json').subscribe();
    const open = http.expectOne('/api/v1/projects');
    expect(open.request.body).toEqual({ project_file: '/work/sample/studio.project.json' });
    open.flush({});
  });

  it('removes a project by slug', () => {
    api.removeProject('sample').subscribe();
    const req = http.expectOne('/api/v1/projects/sample');
    expect(req.request.method).toBe('DELETE');
    req.flush({ slug: 'sample', removed: true });
  });

  it('puts the project in the path of every call, escaped', () => {
    api.kinds('a b').subscribe();
    http.expectOne('/api/v1/projects/a%20b/kinds').flush({ kinds: [] });
    api.linkTypes('sample').subscribe();
    http.expectOne('/api/v1/projects/sample/link-types').flush({ link_types: [] });
  });

  it('sends the filters of an entity list as query parameters, and none that are empty', () => {
    api.entities('sample', { kind: 'prop', tag: 'lamp', q: 'key', include_archived: true }).subscribe();
    const req = http.expectOne((r) => r.url === '/api/v1/projects/sample/entities');
    expect(req.request.params.get('kind')).toBe('prop');
    expect(req.request.params.get('tag')).toBe('lamp');
    expect(req.request.params.get('q')).toBe('key');
    expect(req.request.params.get('include_archived')).toBe('true');
    req.flush({ entities: [] });

    api.entities('sample').subscribe();
    const bare = http.expectOne('/api/v1/projects/sample/entities');
    expect(bare.request.params.keys()).toEqual([]);
    bare.flush({ entities: [] });
  });

  it('creates an entity and updates it with the revision that was read, adding a note only when there is one', () => {
    api.createEntity('sample', 'prop', { name: 'Key' }).subscribe();
    const create = http.expectOne('/api/v1/projects/sample/entities');
    expect(create.request.body).toEqual({ kind: 'prop', data: { name: 'Key' } });
    create.flush({});

    api.updateEntity('sample', 'e1', 3, { name: 'Key' }, '  tidy  ').subscribe();
    const put = http.expectOne('/api/v1/projects/sample/entities/e1');
    expect(put.request.method).toBe('PUT');
    expect(put.request.body).toEqual({ revision: 3, data: { name: 'Key' }, note: 'tidy' });
    expect(put.request.headers.get('X-Studio-Request')).toBe('1');
    expect(put.request.headers.has('X-Studio-Project')).toBe(false);
    put.flush({});
  });

  it('archives, restores and reverts with the revision', () => {
    api.archiveEntity('p', 'e', 2).subscribe();
    expect(http.expectOne('/api/v1/projects/p/entities/e/archive').request.body).toEqual({ revision: 2 });
    api.restoreEntity('p', 'e', 3).subscribe();
    expect(http.expectOne('/api/v1/projects/p/entities/e/restore').request.body).toEqual({ revision: 3 });
    api.revertEntity('p', 'e', 4, 1).subscribe();
    expect(http.expectOne('/api/v1/projects/p/entities/e/revert').request.body).toEqual({ revision: 4, to: 1 });
    http.match(() => true).forEach((r) => r.flush({}));
  });

  it('reads revisions and links (both directions), and creates and removes links', () => {
    let revisions: unknown;
    api.revisions('p', 'e').subscribe((r) => (revisions = r));
    http.expectOne('/api/v1/projects/p/entities/e/revisions').flush({ revisions: [{ revision: 2 }, { revision: 1 }] });
    expect(revisions).toEqual([{ revision: 2 }, { revision: 1 }]);

    api.links('p', 'e').subscribe();
    const list = http.expectOne((r) => r.url === '/api/v1/projects/p/entities/e/links');
    expect(list.request.params.get('direction')).toBe('both');
    list.flush({ links: [] });

    api.createLink('p', 'belongs_to', 'k', 'c').subscribe();
    expect(http.expectOne('/api/v1/projects/p/links').request.body).toEqual({ type: 'belongs_to', source: 'k', target: 'c' });
    api.removeLink('p', 'l1').subscribe();
    const del = http.expectOne('/api/v1/projects/p/links/l1');
    expect(del.request.method).toBe('DELETE');
    http.match(() => true).forEach((r) => r.flush({}));
  });

  it('turns the API error shape into a WorldApiError', () => {
    let error: unknown;
    api.entity('p', 'e').subscribe({ error: (e) => (error = e) });
    http.expectOne('/api/v1/projects/p/entities/e').flush(
      { error: { status: 409, code: 'revision_conflict', message: 'changed underneath', field: null } },
      { status: 409, statusText: 'Conflict' },
    );
    expect(error).toBeInstanceOf(WorldApiError);
    const e = error as WorldApiError;
    expect([e.status, e.code, e.message, e.field, e.isConflict]).toEqual([409, 'revision_conflict', 'changed underneath', null, true]);
  });

  it('keeps the field of a validation error', () => {
    let error: WorldApiError | undefined;
    api.createEntity('p', 'prop', {}).subscribe({ error: (e) => (error = e) });
    http.expectOne('/api/v1/projects/p/entities').flush(
      { error: { status: 422, code: 'invalid_entity', message: "/data/name: 'name' is a required property", field: '/data/name' } },
      { status: 422, statusText: 'Unprocessable' },
    );
    expect(error?.field).toBe('/data/name');
    expect(error?.isConflict).toBe(false);
  });

  it('still gives a usable error when the answer is not the API shape, or never comes', () => {
    let first: WorldApiError | undefined;
    api.kinds('p').subscribe({ error: (e) => (first = e) });
    http.expectOne('/api/v1/projects/p/kinds').flush('<html>', { status: 502, statusText: 'Bad Gateway' });
    expect(first?.status).toBe(502);
    expect(first?.message).toContain('502');

    let second: WorldApiError | undefined;
    api.kinds('p').subscribe({ error: (e) => (second = e) });
    http.expectOne('/api/v1/projects/p/kinds').error(new ProgressEvent('error'));
    expect(second?.code).toBe('unreachable');
  });

  it('writes notes: JSON for text and pins, the raw image for an upload, all with the write header', () => {
    api.updateNote('p', 'e1', 'n1', { pinned: true }).subscribe();
    const patch = http.expectOne('/api/v1/projects/p/entities/e1/notes/n1');
    expect(patch.request.method).toBe('PATCH');
    expect(patch.request.body).toEqual({ pinned: true });
    expect(patch.request.headers.get('X-Studio-Request')).toBe('1');
    patch.flush({});

    const image = new Blob(['x'], { type: 'image/png' });
    api.uploadNoteImage('p', 'e1', 'n1', image, 'my shot.png').subscribe();
    const upload = http.expectOne('/api/v1/projects/p/entities/e1/notes/n1/attachments');
    expect(upload.request.body).toBe(image);
    expect(upload.request.headers.get('Content-Type')).toBe('image/png');
    expect(upload.request.headers.get('X-File-Name')).toBe('my%20shot.png');
    expect(upload.request.headers.get('X-Studio-Request')).toBe('1');
    upload.flush({});

    expect(api.noteImageUrl('p', 'e1', 'n1', 'a1')).toBe('/api/v1/projects/p/entities/e1/notes/n1/attachments/a1');
  });

  it('reads a trace, with the attempt in the query when one is named, and the statistics', () => {
    api.trace('p', 'e1', 'run 1').subscribe();
    http.expectOne('/api/v1/projects/p/entities/e1/runs/run%201/trace').flush({});
    api.trace('p', 'e1', 'r1', 'a1').subscribe();
    http.expectOne('/api/v1/projects/p/entities/e1/runs/r1/trace?attempt=a1').flush({});
    api.statistics('p').subscribe();
    http.expectOne('/api/v1/projects/p/statistics').flush({});
  });

  it('lists pipelines for a kind of record and the adapters', () => {
    api.pipelines('p', 'prop').subscribe();
    const req = http.expectOne((r) => r.url === '/api/v1/projects/p/pipelines');
    expect(req.request.params.get('entity_kind')).toBe('prop');
    req.flush({ pipelines: [] });
    api.adapters().subscribe();
    http.expectOne('/api/v1/adapters').flush({ adapters: [] });
  });

  it('reads the sources, one source page and an entity\'s feeds', () => {
    api.sources('p').subscribe();
    http.expectOne('/api/v1/projects/p/sources').flush({ sources: [] });
    api.source('p', 'style', 'prop.clay').subscribe();
    http.expectOne('/api/v1/projects/p/sources/style/prop.clay').flush({});
    api.feeds('p', 'e 1').subscribe();
    http.expectOne('/api/v1/projects/p/entities/e%201/sources').flush({ run_id: null, attempt_id: null, sources: [] });
  });

  it('starts a job with the write header and reads it back by id', () => {
    const body = { pipeline: 'prop', prompt: 'a key', choices: { seed: 3 } };
    api.startJob('sample', 'e 1', body).subscribe();
    const start = http.expectOne('/api/v1/projects/sample/entities/e%201/jobs');
    expect(start.request.method).toBe('POST');
    expect(start.request.body).toEqual(body);
    expect(start.request.headers.get('X-Studio-Request')).toBe('1');
    start.flush({});
    api.job('sample', 'j1').subscribe();
    http.expectOne('/api/v1/projects/sample/jobs/j1').flush({});
  });
});
