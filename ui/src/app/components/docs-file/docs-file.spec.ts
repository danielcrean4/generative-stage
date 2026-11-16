import { HttpErrorResponse } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router, convertToParamMap, provideRouter } from '@angular/router';
import { Observable, of, throwError } from 'rxjs';
import { DocFile } from '../../docs-view-api';
import { DocsViewApi } from '../../docs-view-api';
import { PROJECTS, TREE, doc, link } from '../../docs-view.fixtures';
import { DocsFile } from './docs-file';

async function render(
  opts: {
    file?: Observable<DocFile>;
    query?: Record<string, string>;
    fragment?: string | null;
  } = {},
) {
  const api = {
    file: vi
      .fn()
      .mockReturnValue(
        opts.file ??
          of(doc('# Docs home\n\nHello.\n\n## First\n\ntext\n\n### Deeper\n\n## Second\n')),
      ),
    projects: vi.fn().mockReturnValue(of({ projects: PROJECTS })),
    tree: vi.fn().mockReturnValue(of({ project: 'my-game', count: 3, tree: TREE })),
  };
  TestBed.configureTestingModule({
    imports: [DocsFile],
    providers: [
      provideRouter([]),
      { provide: DocsViewApi, useValue: api },
      {
        provide: ActivatedRoute,
        useValue: {
          paramMap: of(convertToParamMap({ project: 'my-game' })),
          queryParamMap: of(convertToParamMap(opts.query ?? { path: 'docs/README.md' })),
          fragment: of(opts.fragment ?? null),
        },
      },
    ],
  });
  const fixture = TestBed.createComponent(DocsFile);
  for (let i = 0; i < 3; i++) {
    await fixture.whenStable();
    fixture.detectChanges();
  }
  return { fixture, api, el: fixture.nativeElement as HTMLElement };
}

describe('DocsFile', () => {
  it('shows a breadcrumb back to the tree, the path and the modified time', async () => {
    const { el, api } = await render();
    expect(api.file).toHaveBeenCalledWith('my-game', 'docs/README.md');
    const crumbs = Array.from(el.querySelectorAll('nav[aria-label="Breadcrumb"] li')).map((l) =>
      l.textContent?.trim(),
    );
    expect(crumbs).toEqual(['Docs', 'My Game', 'docs', 'Docs home']);
    expect(el.querySelector('nav[aria-label="Breadcrumb"] a[href="/docs/my-game"]')).not.toBeNull();
    expect(el.querySelector('.facts code')?.textContent).toBe('docs/README.md');
    expect(el.querySelector('.facts')?.textContent).toContain('Modified');
    expect(el.querySelector('h1')?.textContent).toContain('My Game docs');
  });

  it('falls back to the modified time in the tree when the file answer lacks it', async () => {
    const file = of({ ...doc('# T'), modified: undefined });
    const { el, api } = await render({ file });
    expect(api.tree).toHaveBeenCalledWith('my-game');
    expect(el.querySelector('.facts')?.textContent).toContain('Modified');
  });

  it('has an outline landmark listing the headings with their levels', async () => {
    const { el } = await render();
    const nav = el.querySelector('nav[aria-label="Outline of this doc"]')!;
    const rows = Array.from(nav.querySelectorAll('li')).map((l) => [
      l.textContent?.trim(),
      (l as HTMLElement).style.paddingLeft,
    ]);
    expect(rows).toEqual([
      ['Docs home', '0rem'],
      ['First', '0.75rem'],
      ['Deeper', '1.5rem'],
      ['Second', '0.75rem'],
    ]);
    expect(nav.querySelector('a')?.getAttribute('href')).toBe('#docs-home');
  });

  it('keeps the doc headings below the page h1', async () => {
    const { el } = await render();
    expect(el.querySelectorAll('h1').length).toBe(1);
    expect(el.querySelector('app-docs-body h2')?.textContent).toBe('Docs home');
  });

  it('scrolls to the heading when an outline entry is clicked and updates the URL', async () => {
    const { el, fixture } = await render();
    const nav = vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
    const target = el.querySelector('#second') as HTMLElement;
    target.scrollIntoView = vi.fn();
    const links = el.querySelectorAll('nav[aria-label="Outline of this doc"] a');
    const event = new MouseEvent('click', { bubbles: true, cancelable: true });
    links[3].dispatchEvent(event);
    fixture.detectChanges();
    expect(event.defaultPrevented).toBe(true);
    expect(target.scrollIntoView).toHaveBeenCalled();
    expect(nav).toHaveBeenCalledWith([], { queryParamsHandling: 'preserve', fragment: 'second' });
  });

  it('opens a deep link at its fragment', async () => {
    const { el } = await render({ fragment: 'first' });
    expect(el.querySelector('.scroll-target')?.id).toBe('first');
  });

  it('shows a missing doc as an error with a way back', async () => {
    const { el } = await render({
      file: throwError(() => new HttpErrorResponse({ status: 404, error: { error: 'not found' } })),
    });
    expect(el.querySelector('[role="alert"]')?.textContent).toContain('answered 404: not found');
    expect(el.querySelector('a[href="/docs/my-game"]')).not.toBeNull();
  });

  it('shows how to start the server when it is down', async () => {
    const { el } = await render({ file: throwError(() => new HttpErrorResponse({ status: 0 })) });
    expect(el.textContent).toContain('not reachable');
  });

  it('shows a loading state while waiting', async () => {
    const { el } = await render({ file: new Observable<DocFile>(() => undefined) });
    expect(el.querySelector('[role="status"]')?.textContent).toContain('Loading the doc');
  });

  it('asks for a path when the address has none', async () => {
    const { el, api } = await render({ query: {} });
    expect(api.file).not.toHaveBeenCalled();
    expect(el.textContent).toContain('No doc path in the address');
  });

  it('renders the doc text with its links through the body component', async () => {
    const { el } = await render({
      file: of(
        doc('[other](other.md)', [
          link({ target: 'other.md', kind: 'doc', path: 'docs/other.md', exists: true }),
        ]),
      ),
    });
    expect(el.querySelector('a.doc-link')?.getAttribute('href')).toBe(
      '/docs/my-game/file?path=docs%2Fother.md',
    );
  });
});
