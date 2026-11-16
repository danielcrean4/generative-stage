import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

/**
 * The trace page, the statistics page and choosing from a trace, against a real API server. A
 * stand-in pipeline run (three attempts: one that finished, one whose shape gate failed and one
 * whose tidy stage errored) is put in the runs root and attached to a prop. The test reads the
 * trace stage by stage, compares a file with the current choice and chooses it, follows the links
 * between the entity and the trace, reads the statistics and checks both pages at phone width for
 * sideways scrolling. Needs the throwaway API server and dev server the config starts.
 */

const shots = process.env['WORLD_SCREENSHOT_DIR'];
const API = '/api/v1/projects/trace-demo';
const WRITE = { 'X-Studio-Request': '1' };
const RUNS_ROOT = join(tmpdir(), `world-e2e-api-${process.env['WORLD_E2E_API_PORT'] ?? '4311'}`, 'data', 'asset-runs');
const SERVER = resolve(__dirname, '..', '..', 'server');
const SEED = resolve(__dirname, 'seed_trace.py');

async function shot(page: Page, name: string, height = 1500): Promise<void> {
  if (!shots) return;
  const size = page.viewportSize()!;
  await page.setViewportSize({ width: size.width, height });
  await page.screenshot({ path: join(shots, `${name}.png`) });
  await page.setViewportSize(size);
}

async function api<T>(request: APIRequestContext, method: 'post' | 'get', path: string, data?: unknown): Promise<T> {
  const response = await request[method](`${API}${path}`, { headers: WRITE, data });
  expect(response.status(), `${method} ${path}: ${await response.text()}`).toBeLessThan(300);
  return (await response.json()) as T;
}

async function imageLoaded(page: Page, selector: string): Promise<boolean> {
  return page.locator(selector).first().evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0);
}

/** What can be scrolled sideways: the document or the app's scrolling area. Empty when nothing can. */
async function sidewaysScrollers(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const wide = (el: Element) => el.scrollWidth > el.clientWidth + 1;
    const found: string[] = [];
    if (wide(document.documentElement)) {
      found.push(`document ${document.documentElement.scrollWidth} > ${document.documentElement.clientWidth}`);
      for (const el of document.querySelectorAll('body *')) {
        if (el.getBoundingClientRect().right > document.documentElement.clientWidth + 1) found.push(`${el.tagName.toLowerCase()}.${String(el.className).slice(0, 40)}`);
      }
    }
    const content = document.querySelector('.content')!;
    if (wide(content)) found.push(`content ${content.scrollWidth} > ${content.clientWidth}`);
    return found;
  });
}

test('trace, statistics and choosing', async ({ page, request }) => {
  test.setTimeout(120_000);
  const problems: string[] = [];
  page.on('pageerror', (e) => problems.push(e.message));
  page.on('console', (m) => {
    if (m.type() === 'error' && !m.text().includes('Failed to load resource') && !m.text().includes('ERR_FAILED')) problems.push(m.text());
  });

  const folder = join(mkdtempSync(join(tmpdir(), 'world-e2e-project-')), 'trace-demo');
  const created = await request.post('/api/v1/projects', { headers: WRITE, data: { folder, slug: 'trace-demo', name: 'Trace Demo' } });
  expect(created.status()).toBe(201);
  try {
    const bench = await api<{ id: string }>(request, 'post', '/entities', {
      kind: 'prop',
      data: { name: 'Workshop bench', brief: 'The heavy bench where machines are opened up and mended.', tags: ['workshop'] },
    });
    const seeded = JSON.parse(execFileSync('uv', ['run', 'python', SEED, folder, bench.id, '1', RUNS_ROOT], { cwd: SERVER, encoding: 'utf8' })) as {
      job_id: string;
      candidates: string[];
      first: string;
      second: string;
    };
    const run = seeded.job_id;
    const [concept, tidy, mesh] = seeded.candidates;
    await api(request, 'post', `/entities/${bench.id}/runs`, { run_id: run, note: 'made by a job' });
    await api(request, 'post', `/entities/${bench.id}/chosen`, { run_id: run, candidate: concept });

    await test.step('profile: a link to the trace of the chosen version', async () => {
      await page.goto(`/world/prop/${bench.id}`);
      await expect(page.getByTestId('status-line')).toContainText('Chosen from run');
      await page.locator('[data-action="open-trace"]').click();
      await expect(page).toHaveURL(new RegExp(`/world/prop/${bench.id}/runs/${run}\\?attempt=${seeded.first}&stage=concept$`));
    });

    await test.step('trace: every stage in order, with what it did', async () => {
      const strip = page.getByTestId('filmstrip');
      await expect(strip.locator('[data-stage]')).toHaveCount(3);
      await expect(strip.locator('[data-stage]')).toHaveText([/Concept image/, /Tidy the image/, /Make the shape/], { useInnerText: true });
      await expect(strip.locator('[data-stage="concept"]')).toHaveAttribute('data-status', 'completed');
      await expect.poll(() => imageLoaded(page, '[data-stage="concept"] img')).toBe(true);
      await expect(strip.locator('[data-stage="concept"] [data-testid="stage-time"]')).toHaveText('1 min 03 s');
      await expect(strip.locator('[data-stage="tidy"]')).toContainText('Reused');
      await expect(strip.locator('[data-stage="shape"] [data-verdict="fail"]')).toBeVisible();
      await expect(strip.locator('[data-stage="shape"]')).toContainText('3D file');
      await expect(page.getByTestId('attempt-status')).toHaveText('failed');

      // The chosen stage is open: its prompt, inputs context, model and time.
      const detail = page.locator('[data-panel="stage-detail"]');
      await expect(detail).toHaveAttribute('data-stage', 'concept');
      await expect(page.getByTestId('stage-prompt')).toContainText('a worn oak workshop bench');
      await expect(page.getByTestId('stage-adapter')).toContainText('stand-in');
      await expect(page.getByTestId('stage-adapter')).toContainText('ab12cd34');
      await expect(page.getByTestId('stage-context')).toContainText('width');
      await expect(page.getByTestId('stage-timing')).toContainText('1 min 03 s');
      await shot(page, 'trace-01-desktop');

      // Opening the shape stage shows the failing gate with its measures against the limit.
      await strip.locator('[data-stage="shape"] .col-head').click();
      await expect(detail).toHaveAttribute('data-stage', 'shape');
      const gate = page.getByTestId('stage-gate');
      await expect(gate).toContainText('Gate: fail');
      await expect(gate).toContainText('the silhouette does not match the image');
      await expect(gate).toContainText('silhouette_iou');
      await expect(gate).toContainText('0.48');
      await expect(gate).toContainText('0.6');
      await shot(page, 'trace-02-failing-gate');
    });

    await test.step('trace: the attempt that errored, with its error text', async () => {
      await page.getByTestId('attempt-pick').selectOption(seeded.second);
      await expect(page).toHaveURL(new RegExp(`attempt=${seeded.second}`));
      const strip = page.getByTestId('filmstrip');
      await expect(strip.locator('[data-stage="tidy"]')).toHaveAttribute('data-status', 'errored');
      await expect(strip.locator('[data-stage="shape"]')).toHaveAttribute('data-status', 'not_run');
      await expect(page.getByTestId('attempt-error')).toContainText('memory error');
      // It opens on the stage that went wrong.
      await expect(page.locator('[data-panel="stage-detail"]')).toHaveAttribute('data-stage', 'tidy');
      await expect(page.getByTestId('stage-error')).toContainText('memory error');
      await shot(page, 'trace-03-errored');
    });

    await test.step('choosing: compare with the current choice, then use this', async () => {
      await page.goto(`/world/prop/${bench.id}/runs/${run}?attempt=${seeded.first}`);
      const strip = page.getByTestId('filmstrip');
      // The 3D file has nothing chosen in its slot yet.
      await strip.locator('[data-stage="shape"] [data-file="mesh.glb"]').click();
      const compare = page.locator('[data-panel="compare"]');
      await expect(compare.getByTestId('compare-none')).toBeVisible();
      await expect(compare.getByTestId('slot-pick')).toHaveCount(0);

      // A picture next to the image chosen now.
      await strip.locator('[data-stage="tidy"] [data-file="final.png"]').click();
      await expect(compare.getByTestId('compare-this')).toBeVisible();
      await expect(compare.getByTestId('compare-current')).toBeVisible();
      await expect.poll(() => imageLoaded(page, '[data-testid="compare-current"]')).toBe(true);
      await expect(compare.getByTestId('slot-pick')).toHaveValue('main');
      await shot(page, 'trace-04-compare');
      await compare.locator('[data-action="use-this"]').click();
      await expect(compare.getByTestId('already-chosen')).toContainText('Image');
      await expect(strip.locator('[data-stage="tidy"] .tag')).toHaveText('chosen');
      const chosen = await api<{ chosen: Record<string, { candidate: string }> }>(request, 'get', `/entities/${bench.id}/chosen`);
      expect(chosen.chosen['main'].candidate).toBe(tidy);

      // The 3D file too.
      await strip.locator('[data-stage="shape"] [data-file="mesh.glb"]').click();
      await compare.locator('[data-action="use-this"]').click();
      await expect(compare.getByTestId('already-chosen')).toContainText('3D');
      const after = await api<{ chosen: Record<string, { candidate: string }> }>(request, 'get', `/entities/${bench.id}/chosen`);
      expect(after.chosen['mesh'].candidate).toBe(mesh);
    });

    await test.step('back from the trace to the entity', async () => {
      await page.locator('[data-action="back-to-entity"]').click();
      await expect(page).toHaveURL(new RegExp(`/world/prop/${bench.id}$`));
      await expect(page.locator('[data-page="profile"] h1')).toHaveText('Workshop bench');
      await page.locator('[data-panel="history"] [data-action="stream-trace"]').click();
      await expect(page).toHaveURL(new RegExp(`/world/prop/${bench.id}/runs/${run}$`));
      await expect(page.locator('[data-page="trace"]')).toBeVisible();
    });

    await test.step('statistics: runs, time per stage, completed against errored, assets', async () => {
      await page.locator('[data-nav="statistics"]').click();
      await expect(page).toHaveURL(/\/statistics$/);
      await expect(page.locator('[data-stat="runs"]')).toHaveText('3');
      await expect(page.locator('[data-stat="completed"]')).toHaveText('1');
      await expect(page.locator('[data-stat="errored"]')).toHaveText('2');
      await expect(page.locator('[data-stat="candidates"]')).toHaveText('3');
      await expect(page.locator('[data-stat="chosen"]')).toHaveText('2');
      await expect(page.locator('[data-testid="days"] [data-day]')).toHaveText([/Nov\s*9/, /Nov\s*10/, /Nov\s*11/], { useInnerText: true });
      await expect(page.locator('[data-testid="stages"] [data-stage]')).toHaveCount(3);
      await expect(page.locator('[data-testid="stages"] [data-stage="shape"]')).toContainText('3.4 min');
      await shot(page, 'statistics-01-desktop');
    });

    await test.step('phone width: no sideways scrolling', async () => {
      await page.setViewportSize({ width: 390, height: 844 });
      await page.goto(`/world/prop/${bench.id}/runs/${run}?attempt=${seeded.first}&stage=shape`);
      await expect(page.getByTestId('filmstrip')).toBeVisible();
      await page.getByTestId('filmstrip').locator('[data-stage="tidy"] [data-file="final.png"]').click();
      await expect(page.locator('[data-panel="compare"]')).toBeVisible();
      expect(await sidewaysScrollers(page)).toEqual([]);
      await shot(page, 'trace-05-phone', 2600);
      await page.goto('/statistics');
      await expect(page.locator('[data-stat="runs"]')).toHaveText('3');
      expect(await sidewaysScrollers(page)).toEqual([]);
      await shot(page, 'statistics-02-phone', 2000);
    });

    expect(problems).toEqual([]);
  } finally {
    await request.delete('/api/v1/projects/trace-demo', { headers: WRITE });
  }
});

test('statistics of a project with no runs say so', async ({ page, request }) => {
  const folder = join(mkdtempSync(join(tmpdir(), 'world-e2e-project-')), 'empty-stats');
  const created = await request.post('/api/v1/projects', { headers: WRITE, data: { folder, slug: 'empty-stats', name: 'Empty Stats' } });
  expect(created.status()).toBe(201);
  try {
    await page.goto('/statistics');
    await expect(page.locator('[data-stat="runs"]')).toHaveText('0');
    await expect(page.getByTestId('stats-empty')).toBeVisible();
  } finally {
    await request.delete('/api/v1/projects/empty-stats', { headers: WRITE });
  }
});
