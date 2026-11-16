import { HttpErrorResponse } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { Observable, of, throwError } from 'rxjs';
import { DocsViewApi, SourceWindow } from '../../docs-view-api';
import { DocsSource } from './docs-source';

const WINDOW: SourceWindow = {
  path: 'ui/hint.gd',
  total_lines: 160,
  start: 38,
  end: 42,
  truncated: true,
  lines: ['var x', '', '', 'func _ready() -> void:', '\tpass'],
};

async function render(
  opts: { query?: Record<string, string>; result?: Observable<SourceWindow> } = {},
) {
  const api = { source: vi.fn().mockReturnValue(opts.result ?? of(WINDOW)) };
  TestBed.configureTestingModule({
    imports: [DocsSource],
    providers: [
      provideRouter([]),
      { provide: DocsViewApi, useValue: api },
      {
        provide: ActivatedRoute,
        useValue: {
          paramMap: of(convertToParamMap({ project: 'my-game' })),
          queryParamMap: of(convertToParamMap(opts.query ?? { path: 'ui/hint.gd', line: '40' })),
        },
      },
    ],
  });
  const fixture = TestBed.createComponent(DocsSource);
  for (let i = 0; i < 3; i++) {
    await fixture.whenStable();
    fixture.detectChanges();
  }
  return { api, el: fixture.nativeElement as HTMLElement };
}

describe('DocsSource', () => {
  it('asks the API for a window around the line', async () => {
    const { api } = await render();
    expect(api.source).toHaveBeenCalledWith('my-game', 'ui/hint.gd', 40);
  });

  it('shows numbered lines starting at the window start, with the target line highlighted', async () => {
    const { el } = await render();
    const list = el.querySelector('ol.code')!;
    expect(list.getAttribute('start')).toBe('38');
    const rows = Array.from(list.querySelectorAll('li'));
    expect(rows.length).toBe(5);
    expect(rows[3].textContent).toContain('func _ready() -> void:');
    const target = list.querySelectorAll('li.target');
    expect(target.length).toBe(1);
    expect(target[0]).toBe(rows[2]);
    expect(target[0].getAttribute('aria-current')).toBe('location');
    expect(el.textContent).toContain('Lines 38 to 42 of 160');
    expect(el.textContent).toContain('longer than this window');
  });

  it('is read-only: no form controls', async () => {
    const { el } = await render();
    expect(el.querySelector('input, textarea, button, [contenteditable]')).toBeNull();
  });

  it('explains a link outside the allowlist without calling the server', async () => {
    const { api, el } = await render({ query: { path: 'secret/key.txt', blocked: '1' } });
    expect(api.source).not.toHaveBeenCalled();
    expect(el.querySelector('.blocked')?.textContent).toContain(
      'not shown: outside the folders this project lets the docs view open',
    );
  });

  it('shows the same note when the server answers 404 for the file', async () => {
    const { el } = await render({
      result: throwError(
        () => new HttpErrorResponse({ status: 404, error: { error: 'not found' } }),
      ),
    });
    expect(el.querySelector('.blocked')?.textContent).toContain('not shown');
  });

  it('shows other errors, with how to start the server when it is down', async () => {
    const { el } = await render({ result: throwError(() => new HttpErrorResponse({ status: 0 })) });
    expect(el.querySelector('[role="alert"]')?.textContent).toContain('not reachable');
  });

  it('shows a loading state', async () => {
    const { el } = await render({ result: new Observable<SourceWindow>(() => undefined) });
    expect(el.querySelector('[role="status"]')?.textContent).toContain('Loading the file');
  });

  it('says so when the file is empty', async () => {
    const { el } = await render({
      result: of({ ...WINDOW, lines: [], total_lines: 0, start: 1, end: 0, truncated: false }),
    });
    expect(el.textContent).toContain('This file is empty');
  });
});
