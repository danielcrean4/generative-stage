import { HttpErrorResponse } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { Observable, of, throwError } from 'rxjs';
import { DocsViewApi } from '../../docs-view-api';
import { PROJECTS, TREE } from '../../docs-view.fixtures';
import { DocsHome } from './docs-home';

async function render(
  opts: { project?: string; projects?: Observable<unknown>; tree?: Observable<unknown> } = {},
) {
  const api = {
    projects: vi.fn().mockReturnValue(opts.projects ?? of({ projects: PROJECTS })),
    tree: vi.fn().mockReturnValue(opts.tree ?? of({ project: 'my-game', count: 3, tree: TREE })),
    search: vi
      .fn()
      .mockReturnValue(of({ docs_matched: 0, total_hits: 0, truncated: false, hits: [] })),
    searchAll: vi.fn(),
  };
  TestBed.configureTestingModule({
    imports: [DocsHome],
    providers: [
      provideRouter([]),
      { provide: DocsViewApi, useValue: api },
      {
        provide: ActivatedRoute,
        useValue: {
          snapshot: { queryParamMap: convertToParamMap({}) },
          paramMap: of(convertToParamMap(opts.project ? { project: opts.project } : {})),
          queryParamMap: of(convertToParamMap({})),
        },
      },
    ],
  });
  const fixture = TestBed.createComponent(DocsHome);
  await fixture.whenStable();
  fixture.detectChanges();
  await fixture.whenStable();
  fixture.detectChanges();
  return { fixture, api, el: fixture.nativeElement as HTMLElement };
}

describe('DocsHome', () => {
  it('lists the registered projects with their doc counts and asks for a choice', async () => {
    const { el, api } = await render();
    const names = Array.from(el.querySelectorAll('nav[aria-label="Projects"] a .name')).map(
      (a) => a.textContent,
    );
    const metas = Array.from(el.querySelectorAll('nav[aria-label="Projects"] a .meta')).map(
      (a) => a.textContent,
    );
    expect(names).toEqual(['My Game', 'My Tools']);
    expect(metas).toEqual(['3 docs', '1 docs']);
    expect(el.textContent).toContain('Choose a project');
    expect(api.tree).not.toHaveBeenCalled();
  });

  it('shows the chosen project as the current page and loads its tree', async () => {
    const { el, api } = await render({ project: 'my-game' });
    expect(api.tree).toHaveBeenCalledWith('my-game');
    expect(
      el.querySelector('nav[aria-label="Projects"] a[aria-current="page"]')?.textContent,
    ).toContain('My Game');
    expect(el.querySelector('h3')?.textContent).toContain('All docs in My Game');
  });

  it('renders nested folders as disclosure widgets and files by title with the path as secondary text', async () => {
    const { el } = await render({ project: 'my-game' });
    const folders = Array.from(el.querySelectorAll('details > summary')).map((s) =>
      s.textContent?.replace(/\s+/g, ' ').trim(),
    );
    expect(folders).toEqual(['docs (2)', 'design (1)']);
    expect(el.querySelectorAll('details details').length).toBe(1);
    const vision = Array.from(el.querySelectorAll('a.file')).find((a) =>
      a.textContent?.includes('Vision'),
    )!;
    expect(vision.querySelector('.title')?.textContent).toBe('Vision');
    expect(vision.querySelector('.path')?.textContent).toBe('docs/design/vision.md');
    expect(vision.getAttribute('href')).toBe('/docs/my-game/file?path=docs%2Fdesign%2Fvision.md');
  });

  it('lets a folder be collapsed with the keyboard-friendly details element', async () => {
    const { el } = await render({ project: 'my-game' });
    const inner = el.querySelectorAll('details')[1] as HTMLDetailsElement;
    expect(inner.open).toBe(false);
    inner.querySelector('summary')!.click();
    expect(inner.tagName).toBe('DETAILS');
  });

  it('says so when the project has no docs', async () => {
    const { el } = await render({
      project: 'my-game',
      tree: of({ project: 'my-game', count: 0, tree: { ...TREE, children: [] } }),
    });
    expect(el.textContent).toContain('no markdown docs');
  });

  it('says so when the project is not registered', async () => {
    const { el } = await render({ project: 'nope' });
    expect(el.querySelector('[role="alert"]')?.textContent).toContain(
      'No registered project is called "nope"',
    );
  });

  it('shows how to start the server when the project list cannot be loaded', async () => {
    const { el } = await render({
      projects: throwError(() => new HttpErrorResponse({ status: 0 })),
    });
    expect(el.textContent).toContain('not reachable');
    expect(el.textContent).toContain('uv run python -m authoring.readonly_server --port 8781');
  });

  it('shows the error from a failed tree load', async () => {
    const { el } = await render({
      project: 'my-game',
      tree: throwError(
        () => new HttpErrorResponse({ status: 404, error: { error: 'unknown project' } }),
      ),
    });
    expect(el.textContent).toContain('answered 404: unknown project');
  });

  it('shows an empty state when no project is registered', async () => {
    const { el } = await render({ projects: of({ projects: [] }) });
    expect(el.textContent).toContain('No project is registered');
  });
});
