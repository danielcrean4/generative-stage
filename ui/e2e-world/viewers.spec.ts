import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

/**
 * The 3D viewer and clip player against a real API server. The rigged example model (made by
 * blender/build_rigged.py) is put in a stand-in run as the 3D file. The test opens it from the
 * profile page and from the trace page, compares it with the current choice, plays one of its
 * clips, checks that the canvas shows a lit model rather than a blank or black picture, and
 * checks phone width for sideways scrolling. Needs the throwaway API server and dev server the
 * config starts. Set WORLD_SCREENSHOT_DIR to also save screenshots.
 */

const shots = process.env['WORLD_SCREENSHOT_DIR'];
const WRITE = { 'X-Studio-Request': '1' };
const RUNS_ROOT = join(tmpdir(), `world-e2e-api-${process.env['WORLD_E2E_API_PORT'] ?? '4311'}`, 'data', 'asset-runs');
const SERVER = resolve(__dirname, '..', '..', 'server');
const MODEL = resolve(__dirname, '..', '..', 'blender', 'examples', 'rigged', 'biped.glb');
const BACKGROUND = [0xd7, 0xda, 0xdf];

async function shot(page: Page, name: string, height = 1500): Promise<void> {
  if (!shots) return;
  const size = page.viewportSize()!;
  await page.setViewportSize({ width: size.width, height });
  await page.waitForTimeout(250);
  await page.screenshot({ path: join(shots, `${name}.png`) });
  await page.setViewportSize(size);
}

async function api<T>(request: APIRequestContext, slug: string, method: 'post' | 'get', path: string, data?: unknown): Promise<T> {
  const response = await request[method](`/api/v1/projects/${slug}${path}`, { headers: WRITE, data });
  expect(response.status(), `${method} ${path}: ${await response.text()}`).toBeLessThan(300);
  return (await response.json()) as T;
}

/** How much of a canvas is model: the share of pixels that are not the background, and how bright they are on average. */
async function modelPixels(page: Page, canvas: Locator): Promise<{ share: number; brightness: number }> {
  const png = (await canvas.screenshot()).toString('base64');
  return page.evaluate(
    async ([data, bg]) => {
      const image = new Image();
      image.src = `data:image/png;base64,${data}`;
      await image.decode();
      const c = document.createElement('canvas');
      c.width = image.width;
      c.height = image.height;
      const ctx = c.getContext('2d')!;
      ctx.drawImage(image, 0, 0);
      const px = ctx.getImageData(0, 0, c.width, c.height).data;
      let model = 0;
      let light = 0;
      for (let i = 0; i < px.length; i += 4) {
        const d = Math.abs(px[i] - bg[0]) + Math.abs(px[i + 1] - bg[1]) + Math.abs(px[i + 2] - bg[2]);
        if (d > 60) {
          model++;
          light += (px[i] + px[i + 1] + px[i + 2]) / 3;
        }
      }
      return { share: model / (px.length / 4), brightness: model ? light / model : 0 };
    },
    [png, BACKGROUND] as const,
  );
}

async function expectLitModel(page: Page, viewer: Locator): Promise<void> {
  await expect(viewer).toHaveAttribute('data-state', 'ready', { timeout: 30_000 });
  const canvas = viewer.getByTestId('viewer-canvas');
  await expect
    .poll(async () => (await modelPixels(page, canvas)).share, { message: 'the model is drawn', timeout: 15_000 })
    .toBeGreaterThan(0.02);
  const { brightness } = await modelPixels(page, canvas);
  expect(brightness, 'the model is lit, not black').toBeGreaterThan(40);
}

async function sidewaysScrollers(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const wide = (el: Element) => el.scrollWidth > el.clientWidth + 1;
    const found: string[] = [];
    if (wide(document.documentElement)) found.push(`document ${document.documentElement.scrollWidth}`);
    const content = document.querySelector('.content');
    if (content && wide(content)) found.push(`content ${content.scrollWidth} > ${content.clientWidth}`);
    return found;
  });
}

async function makeProject(request: APIRequestContext, slug: string): Promise<{ id: string; folder: string }> {
  const folder = join(mkdtempSync(join(tmpdir(), 'world-e2e-project-')), slug);
  const created = await request.post('/api/v1/projects', { headers: WRITE, data: { folder, slug, name: slug } });
  expect(created.status()).toBe(201);
  const bench = await api<{ id: string }>(request, slug, 'post', '/entities', { kind: 'prop', data: { name: 'Walker', brief: 'A jointed walking figure.' } });
  return { id: bench.id, folder };
}

function collectProblems(page: Page): string[] {
  const problems: string[] = [];
  page.on('pageerror', (e) => problems.push(e.message));
  page.on('console', (m) => {
    if (m.type() === 'error' && !m.text().includes('Failed to load resource') && !m.text().includes('ERR_FAILED')) problems.push(m.text());
  });
  return problems;
}

test('profile: the 3D tab shows the model, its facts and a clip that plays', async ({ page, request }) => {
  test.setTimeout(120_000);
  const problems = collectProblems(page);
  const { id, folder } = await makeProject(request, 'viewer-profile');
  try {
    const seeded = JSON.parse(execFileSync('uv', ['run', 'python', resolve(__dirname, 'seed_run.py'), folder, id, '1', RUNS_ROOT, MODEL], { cwd: SERVER, encoding: 'utf8' })) as {
      job_id: string;
      candidates: string[];
    };
    const mesh = seeded.candidates[3];
    await api(request, 'viewer-profile', 'post', `/entities/${id}/runs`, { run_id: seeded.job_id });
    await api(request, 'viewer-profile', 'post', `/entities/${id}/chosen`, { run_id: seeded.job_id, candidate: mesh, slot: 'mesh' });

    await page.goto(`/world/prop/${id}`);
    await page.locator('[data-slot="mesh"]').click();
    const hero = page.locator('[data-panel="hero"]');
    const viewer = hero.getByTestId('model-viewer');
    await expectLitModel(page, viewer);
    await expect(hero.getByTestId('viewer-stats')).toContainText(/\d+ triangles, \d+ vertices, .* m × .* m × .* m, 4 materials/);
    await shot(page, 'profile-3d-tab');

    await test.step('orbit, wireframe and reset change the picture', async () => {
      const canvas = viewer.getByTestId('viewer-canvas');
      const before = await canvas.screenshot();
      const box = (await canvas.boundingBox())!;
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
      await page.mouse.down();
      await page.mouse.move(box.x + box.width / 2 + 120, box.y + box.height / 2 + 20, { steps: 6 });
      await page.mouse.up();
      await expect.poll(async () => !(await canvas.screenshot()).equals(before)).toBe(true);
      await viewer.locator('[data-action="wireframe"]').click();
      await expect(viewer.locator('[data-action="wireframe"]')).toHaveAttribute('aria-pressed', 'true');
      await shot(page, 'profile-3d-wireframe');
      await viewer.locator('[data-action="wireframe"]').click();
      await viewer.locator('[data-action="reset-view"]').click();
      await expect.poll(async () => (await canvas.screenshot()).equals(before)).toBe(true);
    });

    await test.step('the clip player lists the clips and plays one', async () => {
      const player = viewer.getByTestId('clip-player');
      await expect(player.locator('[data-testid="clip-select"] option')).toHaveText([/flinch/, /idle/, /run/, /walk/]);
      await player.getByTestId('clip-select').selectOption('walk');
      await expect(player.getByTestId('clip-time')).toContainText(/0\.00 \/ 0\.6\d/);
      await player.locator('[data-action="play-clip"]').click();
      await expect(player.locator('[data-action="play-clip"]')).toContainText('Pause');
      await expect.poll(async () => parseFloat((await player.getByTestId('clip-time').textContent()) ?? '0')).toBeGreaterThan(0.05);
      await shot(page, 'profile-3d-walk-playing');
      await player.locator('[data-action="play-clip"]').click();
      const held = await player.getByTestId('clip-time').textContent();
      await page.waitForTimeout(300);
      expect(await player.getByTestId('clip-time').textContent()).toBe(held);
      const scrub = player.getByTestId('clip-scrub');
      await scrub.fill('0.3');
      await expect(player.getByTestId('clip-time')).toContainText('0.30 /');
      await expectLitModel(page, viewer);
      await player.getByTestId('clip-speed').selectOption('0.5');
      await player.getByTestId('clip-loop').uncheck();
    });

    await test.step('phone width: no sideways scroll', async () => {
      await page.setViewportSize({ width: 390, height: 844 });
      await page.reload();
      await page.locator('[data-slot="mesh"]').click();
      await expectLitModel(page, page.locator('[data-panel="hero"]').getByTestId('model-viewer'));
      expect(await sidewaysScrollers(page)).toEqual([]);
      await shot(page, 'profile-3d-phone-390', 2200);
    });
    expect(problems).toEqual([]);
  } finally {
    await request.delete(`/api/v1/projects/viewer-profile`, { headers: WRITE });
  }
});

test('trace: a mesh tile opens in the stage detail, and the compare panel sets it beside the current choice', async ({ page, request }) => {
  test.setTimeout(120_000);
  const problems = collectProblems(page);
  const { id, folder } = await makeProject(request, 'viewer-trace');
  try {
    const seeded = JSON.parse(execFileSync('uv', ['run', 'python', resolve(__dirname, 'seed_trace.py'), folder, id, '1', RUNS_ROOT, MODEL], { cwd: SERVER, encoding: 'utf8' })) as {
      job_id: string;
      candidates: string[];
      first: string;
    };
    const run = seeded.job_id;
    await api(request, 'viewer-trace', 'post', `/entities/${id}/runs`, { run_id: run });
    await api(request, 'viewer-trace', 'post', `/entities/${id}/chosen`, { run_id: run, candidate: seeded.candidates[2], slot: 'mesh' });

    await page.goto(`/world/prop/${id}/runs/${run}?attempt=${seeded.first}&stage=shape`);
    const strip = page.getByTestId('filmstrip');
    await expect(strip.locator('[data-stage="shape"] [data-file="mesh.glb"]')).toBeVisible();
    await expect(page.getByTestId('model-viewer')).toHaveCount(0); // nothing 3D is loaded until a tile is opened

    await strip.locator('[data-stage="shape"] [data-file="mesh.glb"]').click();
    const detail = page.locator('[data-panel="stage-detail"]').getByTestId('model-viewer');
    await expectLitModel(page, detail);
    const compare = page.locator('[data-panel="compare"]');
    await expectLitModel(page, compare.getByTestId('compare-this-viewer').getByTestId('model-viewer'));
    await expectLitModel(page, compare.getByTestId('compare-current-viewer').getByTestId('model-viewer'));
    await shot(page, 'trace-3d-compare');

    await test.step('phone width', async () => {
      await page.setViewportSize({ width: 390, height: 844 });
      await page.reload();
      await strip.locator('[data-stage="shape"] [data-file="mesh.glb"]').click();
      await expectLitModel(page, page.locator('[data-panel="stage-detail"]').getByTestId('model-viewer'));
      expect(await sidewaysScrollers(page)).toEqual([]);
      await shot(page, 'trace-3d-phone-390', 3200);
    });
    expect(problems).toEqual([]);
  } finally {
    await request.delete(`/api/v1/projects/viewer-trace`, { headers: WRITE });
  }
});
