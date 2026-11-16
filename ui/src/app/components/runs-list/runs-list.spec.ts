import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { of, throwError } from 'rxjs';
import { HttpErrorResponse } from '@angular/common/http';
import { RunViewApi, RunSummary } from '../../run-view-api';
import { RunsList } from './runs-list';

function row(id: string, extra: Partial<RunSummary> = {}): RunSummary {
  return {
    run_id: id,
    latest_attempt_id: 'att-' + id,
    status: 'generated',
    error: null,
    started: '2026-11-11T02:08:34Z',
    finished: '2026-11-11T02:09:13Z',
    stages: ['concept', 'matte'],
    modified: '2026-11-11T02:09:13Z',
    ...extra,
  };
}

async function render(runs: ReturnType<typeof vi.fn>) {
  TestBed.configureTestingModule({
    imports: [RunsList],
    providers: [provideRouter([]), { provide: RunViewApi, useValue: { runs } }],
  });
  const fixture = TestBed.createComponent(RunsList);
  await fixture.whenStable();
  fixture.detectChanges();
  return fixture;
}

describe('RunsList', () => {
  it('shows runs in the order given, with real table headers and a problem row', async () => {
    const runs = vi.fn().mockReturnValue(
      of({ runs: [row('bbb'), row('aaa', { problem: 'attempt.json is not valid JSON' })], total: 2, limit: 50 }),
    );
    const fixture = await render(runs);
    const el: HTMLElement = fixture.nativeElement;
    expect(runs).toHaveBeenCalledWith(50);
    expect(el.querySelectorAll('thead th[scope="col"]').length).toBe(6);
    const ids = Array.from(el.querySelectorAll('tbody th')).map((e) => e.textContent?.trim());
    expect(ids).toEqual(['bbb', 'aaa']);
    expect(el.textContent).toContain('attempt.json is not valid JSON');
  });

  it('filters by run id', async () => {
    const runs = vi.fn().mockReturnValue(of({ runs: [row('bbb'), row('aaa')], total: 2, limit: 50 }));
    const fixture = await render(runs);
    fixture.componentInstance.filter.set('aa');
    fixture.detectChanges();
    const ids = Array.from(fixture.nativeElement.querySelectorAll('tbody th')).map((e) =>
      (e as HTMLElement).textContent?.trim(),
    );
    expect(ids).toEqual(['aaa']);
  });

  it('reloads with the chosen limit', async () => {
    const runs = vi.fn().mockReturnValue(of({ runs: [], total: 0, limit: 100 }));
    const fixture = await render(runs);
    fixture.componentInstance.setLimit('100');
    expect(runs).toHaveBeenLastCalledWith(100);
  });

  it('shows the empty state', async () => {
    const fixture = await render(vi.fn().mockReturnValue(of({ runs: [], total: 0, limit: 50 })));
    expect(fixture.nativeElement.textContent).toContain('found no runs');
  });

  it('shows how to start the server when it is down', async () => {
    const fixture = await render(
      vi.fn().mockReturnValue(throwError(() => new HttpErrorResponse({ status: 0 }))),
    );
    const text: string = fixture.nativeElement.textContent;
    expect(text).toContain('not reachable');
    expect(text).toContain('uv run python -m authoring.readonly_server --port 8781');
  });
});
