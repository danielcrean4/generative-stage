import { HttpErrorResponse } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router, convertToParamMap, provideRouter } from '@angular/router';
import { Observable, of, throwError } from 'rxjs';
import { DocsViewApi } from '../../docs-view-api';
import { hit } from '../../docs-view.fixtures';
import { DocsSearch, SEARCH_DEBOUNCE_MS, markParts } from './docs-search';

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

async function render(
  opts: { project?: string; q?: string; all?: boolean; result?: Observable<unknown> } = {},
) {
  const response = { docs_matched: 1, total_hits: 1, truncated: false, hits: [hit()] };
  const api = {
    search: vi.fn().mockReturnValue(opts.result ?? of(response)),
    searchAll: vi
      .fn()
      .mockReturnValue(
        opts.result ??
          of({
            ...response,
            hits: [hit(), hit({ project: 'my-tools', title: 'Locks' })],
            docs_matched: 2,
            total_hits: 2,
          }),
      ),
  };
  TestBed.configureTestingModule({
    imports: [DocsSearch],
    providers: [
      provideRouter([]),
      { provide: DocsViewApi, useValue: api },
      {
        provide: ActivatedRoute,
        useValue: {
          snapshot: {
            queryParamMap: convertToParamMap({
              ...(opts.q ? { q: opts.q } : {}),
              ...(opts.all ? { all: '1' } : {}),
            }),
          },
        },
      },
    ],
  });
  const navigate = vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
  const fixture = TestBed.createComponent(DocsSearch);
  fixture.componentRef.setInput('project', opts.project ?? 'my-game');
  const settle = async () => {
    await fixture.whenStable();
    fixture.detectChanges();
    await wait(0);
    await fixture.whenStable();
    fixture.detectChanges();
  };
  await settle();
  const el = fixture.nativeElement as HTMLElement;
  const type = (value: string) => {
    const input = el.querySelector('input[type="search"]') as HTMLInputElement;
    input.value = value;
    input.dispatchEvent(new Event('input'));
  };
  return { fixture, api, el, navigate, settle, type };
}

describe('DocsSearch', () => {
  it('does nothing until something is typed', async () => {
    const { api, el } = await render();
    expect(api.search).not.toHaveBeenCalled();
    expect(el.querySelector('.hits')).toBeNull();
  });

  it('waits for a pause in typing, then searches once for the last text', async () => {
    const { api, type, settle } = await render();
    type('g');
    type('gp');
    type('gpu lock');
    await settle();
    expect(api.search).not.toHaveBeenCalled();
    await wait(SEARCH_DEBOUNCE_MS + 60);
    await settle();
    expect(api.search).toHaveBeenCalledTimes(1);
    expect(api.search).toHaveBeenCalledWith('my-game', 'gpu lock');
  });

  it('shows project, title, heading above the hit, a marked excerpt and a link to the line', async () => {
    const { el, type, settle } = await render({ q: 'gpu lock' });
    expect(el.querySelector('.project')).toBeNull();
    const li = el.querySelector('.hits li')!;
    expect(li.querySelector('.doc')?.textContent).toBe('Vision');
    expect(li.querySelector('.heading')?.textContent).toBe('under "Power use"');
    expect(Array.from(li.querySelectorAll('mark')).map((m) => m.textContent)).toEqual(['GPU lock']);
    expect(li.querySelector('.where')?.textContent).toBe('docs/design/vision.md:12');
    expect(li.querySelector('a.doc')?.getAttribute('href')).toBe(
      '/docs/my-game/file?path=docs%2Fdesign%2Fvision.md&line=12',
    );
    expect(el.querySelector('.count')?.textContent).toContain('1 match in 1 doc');
    type('');
    await settle();
  });

  it('the all-projects toggle changes the call and shows each hit project', async () => {
    const { api, el, fixture, settle } = await render({ q: 'lock' });
    expect(api.search).toHaveBeenCalledWith('my-game', 'lock');
    const box = el.querySelector('input[type="checkbox"]') as HTMLInputElement;
    box.checked = true;
    box.dispatchEvent(new Event('change'));
    await wait(SEARCH_DEBOUNCE_MS + 60);
    await settle();
    fixture.detectChanges();
    expect(api.searchAll).toHaveBeenCalledWith('lock');
    expect(Array.from(el.querySelectorAll('.project')).map((p) => p.textContent)).toEqual([
      'my-game',
      'my-tools',
    ]);
  });

  it('reads the query and the all-projects switch from the URL, and writes them back', async () => {
    const { api, navigate } = await render({ q: 'ratchet', all: true });
    expect(api.searchAll).toHaveBeenCalledWith('ratchet');
    expect(navigate).toHaveBeenCalledWith(
      [],
      expect.objectContaining({ queryParams: { q: 'ratchet', all: 1 }, replaceUrl: true }),
    );
  });

  it('on the project picker page it can only search all projects', async () => {
    const { api, el } = await render({ project: '', q: 'lock' });
    expect((el.querySelector('input[type="checkbox"]') as HTMLInputElement).disabled).toBe(true);
    expect(api.searchAll).toHaveBeenCalledWith('lock');
  });

  it('says so when nothing matches', async () => {
    const { el } = await render({
      q: 'zzz',
      result: of({ docs_matched: 0, total_hits: 0, truncated: false, hits: [] }),
    });
    expect(el.textContent).toContain('Nothing found for "zzz" in this project');
  });

  it('notes when the hit list was cut short', async () => {
    const { el } = await render({
      q: 'a',
      result: of({ docs_matched: 9, total_hits: 80, truncated: true, hits: [hit()] }),
    });
    expect(el.textContent).toContain('80 matches in 9 docs');
    expect(el.textContent).toContain('Showing the first 1');
  });

  it('shows the error, with how to start the server when it is down', async () => {
    const { el } = await render({
      q: 'lock',
      result: throwError(() => new HttpErrorResponse({ status: 0 })),
    });
    expect(el.querySelector('[role="alert"]')?.textContent).toContain('not reachable');
    expect(el.textContent).toContain('readonly_server');
  });

  it('shows a loading state while the answer is pending', async () => {
    const { el } = await render({ q: 'lock', result: new Observable(() => undefined) });
    expect(el.querySelector('[role="status"]')?.textContent).toContain('Searching');
  });
});

describe('markParts', () => {
  it('marks every occurrence, ignoring case, and keeps the original text', () => {
    expect(markParts('Gpu lock and GPU LOCK', 'gpu lock')).toEqual([
      { text: 'Gpu lock', hit: true },
      { text: ' and ', hit: false },
      { text: 'GPU LOCK', hit: true },
    ]);
  });
  it('returns the whole excerpt when nothing matches', () => {
    expect(markParts('abc', 'x')).toEqual([{ text: 'abc', hit: false }]);
  });
});
