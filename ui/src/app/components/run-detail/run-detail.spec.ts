import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { of, throwError } from 'rxjs';
import { HttpErrorResponse } from '@angular/common/http';
import { RunViewApi } from '../../run-view-api';
import { RunDetail } from './run-detail';

async function render(run: ReturnType<typeof vi.fn>) {
  TestBed.configureTestingModule({
    imports: [RunDetail],
    providers: [
      provideRouter([]),
      { provide: RunViewApi, useValue: { run } },
      { provide: ActivatedRoute, useValue: { paramMap: of(convertToParamMap({ runId: 'run-1' })) } },
    ],
  });
  const fixture = TestBed.createComponent(RunDetail);
  await fixture.whenStable();
  fixture.detectChanges();
  return fixture;
}

describe('RunDetail', () => {
  it('lists attempts in the order given and shows root images with alt text', async () => {
    const run = vi.fn().mockReturnValue(
      of({
        run_id: 'run-1',
        latest_attempt_id: 'new',
        attempts: [
          { attempt_id: 'new', status: 'failed', error: 'boom', started: null, finished: null, seed: 1, stages: ['a'] },
          { attempt_id: 'old', status: 'generated', error: null, started: null, finished: null, seed: 1, stages: ['a'] },
        ],
        root_files: [{ name: 'bust_raw.png', size: 2048, media_type: 'image/png', url: '/api/ro/x/bust_raw.png' }],
      }),
    );
    const fixture = await render(run);
    const el: HTMLElement = fixture.nativeElement;
    expect(run).toHaveBeenCalledWith('run-1');
    expect(Array.from(el.querySelectorAll('tbody th')).map((e) => e.textContent?.replace('latest', '').trim())).toEqual([
      'new',
      'old',
    ]);
    expect(el.querySelector('img')?.getAttribute('alt')).toBe('Run root file bust_raw.png');
  });

  it('shows the error state', async () => {
    const fixture = await render(
      vi.fn().mockReturnValue(throwError(() => new HttpErrorResponse({ status: 404, error: { error: 'not found' } }))),
    );
    expect(fixture.nativeElement.querySelector('[role="alert"]').textContent).toContain('404: not found');
  });
});
