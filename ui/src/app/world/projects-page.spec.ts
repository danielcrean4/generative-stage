import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { ConfirmOptions, ConfirmService } from './confirm';
import { ProjectsPage } from './projects-page';
import { WorldProjectService } from './world-project.service';

const PROJECT = { slug: 'sample', name: 'Sample Project', folder: '/work/sample', project_file: '/work/sample/studio.project.json', problem: null };
const BROKEN = { slug: 'moved', project_file: '/gone/studio.project.json', problem: 'cannot read the project file' };

describe('ProjectsPage', () => {
  let http: HttpTestingController;
  let asked: ConfirmOptions[];
  let answer: boolean;

  async function setup(projects: unknown[]) {
    localStorage.clear();
    asked = [];
    answer = false;
    await TestBed.configureTestingModule({
      imports: [ProjectsPage],
      providers: [
        provideRouter([{ path: 'switching', children: [] }, { path: 'projects', children: [] }]),
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: ConfirmService, useValue: { ask: async (o: ConfirmOptions) => (asked.push(o), answer) } },
      ],
    }).compileComponents();
    http = TestBed.inject(HttpTestingController);
    const world = TestBed.inject(WorldProjectService);
    const loading = world.load();
    http.expectOne('/api/v1/projects').flush({ projects });
    const first = (projects as { slug: string; problem: string | null }[]).find((p) => !p.problem);
    if (first) {
      await vi.waitFor(() => http.expectOne(`/api/v1/projects/${first.slug}/kinds`)).then((r) => r.flush({ kinds: [] }));
      http.expectOne(`/api/v1/projects/${first.slug}/link-types`).flush({ link_types: [] });
      await vi.waitFor(() => http.expectOne(`/api/v1/projects/${first.slug}/entities`)).then((r) => r.flush({ entities: [] }));
    }
    await loading;
    const fixture = TestBed.createComponent(ProjectsPage);
    fixture.detectChanges();
    return { fixture, el: fixture.nativeElement as HTMLElement, world };
  }

  afterEach(() => http.verify());

  it('says what a project is when there are none, and offers to make or open one', async () => {
    const { el } = await setup([]);
    expect(el.querySelector('[data-testid="no-projects"]')).not.toBeNull();
    expect(el.querySelector('form[data-form="create"]')).not.toBeNull();
    expect(el.querySelector('form[data-form="open"]')).not.toBeNull();
  });

  it('lists projects, marks the current one, and shows a project that cannot load with its problem', async () => {
    const { el } = await setup([PROJECT, BROKEN]);
    const cards = el.querySelectorAll('li.card');
    expect(cards).toHaveLength(2);
    expect(cards[0].textContent).toContain('Sample Project');
    expect(cards[0].textContent).toContain('Current');
    expect(cards[1].textContent).toContain('cannot read the project file');
    expect(cards[1].textContent).not.toContain('Use this project');
    expect(cards[1].textContent).toContain('Remove from list');
  });

  it('states in the confirmation that the folder is not deleted, and removes nothing when the person keeps it', async () => {
    const { fixture, el } = await setup([PROJECT]);
    const remove = Array.from(el.querySelectorAll('button')).find((b) => b.textContent?.includes('Remove from list'))!;
    remove.click();
    await fixture.whenStable();
    expect(asked).toHaveLength(1);
    expect(asked[0].title).toContain('Sample Project');
    expect(asked[0].message).toContain('/work/sample');
    expect(asked[0].message).toContain('stay exactly as they are');
    http.expectNone('/api/v1/projects/sample');
  });

  it('removes the project from the list, with a DELETE, once confirmed', async () => {
    const { fixture, el, world } = await setup([PROJECT]);
    answer = true;
    const remove = Array.from(el.querySelectorAll('button')).find((b) => b.textContent?.includes('Remove from list'))!;
    remove.click();
    const del = await vi.waitFor(() => http.expectOne('/api/v1/projects/sample'));
    expect(del.request.method).toBe('DELETE');
    del.flush({ slug: 'sample', removed: true });
    (await vi.waitFor(() => http.expectOne('/api/v1/projects'))).flush({ projects: [] });
    await vi.waitFor(() => expect(world.slug()).toBeNull());
    fixture.detectChanges();
    expect(el.querySelector('[data-testid="no-projects"]')).not.toBeNull();
  });
});
