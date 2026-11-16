import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { of, throwError } from 'rxjs';
import { HttpErrorResponse } from '@angular/common/http';
import { AttemptDetail, RunViewApi } from '../../run-view-api';
import { attempt, stage } from '../../run-view.fixtures';
import { AttemptView } from './attempt-view';

async function render(source: ReturnType<typeof vi.fn>) {
  TestBed.configureTestingModule({
    imports: [AttemptView],
    providers: [
      provideRouter([]),
      { provide: RunViewApi, useValue: { attempt: source, fileText: vi.fn().mockReturnValue(of('LOG TEXT')) } },
      {
        provide: ActivatedRoute,
        useValue: { paramMap: of(convertToParamMap({ runId: 'run-1', attemptId: 'att-1' })) },
      },
    ],
  });
  const fixture = TestBed.createComponent(AttemptView);
  await fixture.whenStable();
  fixture.detectChanges();
  return fixture;
}

const ok = (a: AttemptDetail) => vi.fn().mockReturnValue(of(a));

describe('AttemptView', () => {
  it('renders one panel per stage in the order given, without hard-coded names', async () => {
    const fixture = await render(
      ok(attempt({ stages: [stage({ stage: 'zeta' }), stage({ stage: 'alpha' }), stage({ stage: 'mid' })] })),
    );
    const heads = Array.from(fixture.nativeElement.querySelectorAll('h4')).map((e) =>
      (e as HTMLElement).textContent?.trim(),
    );
    expect(heads).toEqual(['Step 1: zeta', 'Step 2: alpha', 'Step 3: mid']);
  });

  it('shows the resolved prompt first, cache state and cache key', async () => {
    const fixture = await render(
      ok(attempt({ stages: [stage({ stage: 'concept', reused: true })] })),
    );
    const text: string = fixture.nativeElement.textContent;
    expect(text).toContain('Reused from cache');
    expect(text).toContain('Cache key');
    const firstKey = fixture.nativeElement.querySelector('article section dl.kv dt');
    expect(firstKey.textContent).toBe('settings.prompt');
  });

  it('shows a failed gate with each reason and a Failed label', async () => {
    const fixture = await render(
      ok(
        attempt({
          stages: [
            stage({
              stage: 'mesh',
              gates: [
                {
                  file: 'mesh-validation.json',
                  url: '/u',
                  passed: false,
                  reasons: ['too many pieces', 'silhouette too thin'],
                  measures: { pieces: 17 },
                  thresholds: { max_pieces: 3 },
                },
              ],
            }),
          ],
        }),
      ),
    );
    const el: HTMLElement = fixture.nativeElement;
    const reasons = Array.from(el.querySelectorAll('.gate .reason')).map((e) => e.textContent?.trim());
    expect(reasons).toEqual(['too many pieces', 'silhouette too thin']);
    expect(el.querySelector('.gate .verdict')?.textContent?.trim()).toBe('Failed');
    expect(el.querySelector('.gate')?.textContent).toContain('2 failure reasons');
    expect(el.querySelector('.gate')?.textContent).toContain('pieces');
  });

  it('labels a report without a verdict', async () => {
    const fixture = await render(
      ok(attempt({ stages: [stage({ stage: 'concept', gates: [{ file: 'image-validation.json', url: '/u', passed: null, reasons: [], measures: [{ size: [1, 1] }], thresholds: null }] })] })),
    );
    expect(fixture.nativeElement.querySelector('.gate .verdict').textContent).toContain('No verdict');
  });

  it('marks a stage that attempt.json did not record', async () => {
    const fixture = await render(
      ok(attempt({ stages: [stage({ stage: 'mesh', recorded: false, status: 'gate_failed', reused: null, cache_key: null })] })),
    );
    const text: string = fixture.nativeElement.textContent;
    expect(text).toContain('Not recorded');
    expect(text).toContain('gate_failed');
    expect(fixture.nativeElement.querySelector('article').getAttribute('data-recorded')).toBe('false');
  });

  it('shows the attempt error at the top', async () => {
    const fixture = await render(ok(attempt({ status: 'failed', error: 'mesh failed the shape gate' })));
    const first = fixture.nativeElement.querySelector('[role="alert"]');
    expect(first.textContent).toContain('mesh failed the shape gate');
  });

  it('shows images with alt text, the 3D viewer, and opens a log in the viewer pane', async () => {
    const base = { size: 10, url: '/f' };
    const fixture = await render(
      ok(
        attempt({
          stages: [
            stage({
              stage: 'mesh',
              files: [
                { ...base, name: 'matte.png', media_type: 'image/png' },
                { ...base, name: 'mesh.glb', media_type: 'model/gltf-binary' },
                { ...base, name: 'step.log', media_type: 'text/plain' },
              ],
            }),
          ],
        }),
      ),
    );
    const el: HTMLElement = fixture.nativeElement;
    expect(el.querySelector('img')?.getAttribute('alt')).toBe('mesh output matte.png');
    expect(el.querySelector('app-model-viewer')).toBeTruthy();
    (el.querySelector('.file-links button') as HTMLButtonElement).click();
    fixture.detectChanges();
    expect(el.querySelector('.viewer pre')?.textContent).toBe('LOG TEXT');
  });

  it('shows the error state with how to start the server', async () => {
    const fixture = await render(vi.fn().mockReturnValue(throwError(() => new HttpErrorResponse({ status: 0 }))));
    expect(fixture.nativeElement.querySelector('[role="alert"]').textContent).toContain(
      'uv run python -m authoring.readonly_server --port 8781',
    );
  });
});
