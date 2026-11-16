import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { PROJECT_KEY } from '../brand';
import { WorldProjectService } from './world-project.service';

const project = (slug: string) => ({ slug, name: slug, folder: `/work/${slug}`, project_file: `/work/${slug}/studio.project.json`, problem: null });

describe('WorldProjectService remembered project', () => {
  let http: HttpTestingController;
  const origin = window.location.origin;
  const current = `${PROJECT_KEY}@${origin}`;

  async function loadWith(slugs: string[]): Promise<WorldProjectService> {
    await TestBed.configureTestingModule({
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();
    http = TestBed.inject(HttpTestingController);
    const service = TestBed.inject(WorldProjectService);
    const loading = service.load();
    http.expectOne('/api/v1/projects').flush({ projects: slugs.map(project) });
    // the catalog is read for whichever project was picked; answer it so load() finishes
    await vi.waitFor(() => http.expectOne((r) => r.url.endsWith('/kinds'))).then((r) => r.flush({ kinds: [] }));
    http.expectOne((r) => r.url.endsWith('/link-types')).flush({ link_types: [] });
    await vi.waitFor(() => http.expectOne((r) => r.url.endsWith('/entities'))).then((r) => r.flush({ entities: [] }));
    await loading;
    return service;
  }

  beforeEach(() => localStorage.clear());
  afterEach(() => http.verify());

  it('opens the project remembered for this address', async () => {
    localStorage.setItem(current, 'second');
    const service = await loadWith(['first', 'second']);
    expect(service.slug()).toBe('second');
  });

  it('falls back to the first project when nothing is remembered; the key name has no product name in it', async () => {
    const service = await loadWith(['first', 'second']);
    expect(service.slug()).toBe('first');
    expect(PROJECT_KEY.toLowerCase()).not.toContain('generative');
  });
});
