import { expect, test, type Page } from '@playwright/test';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

/**
 * Where the words of a prompt came from, on the stand-in adapters of the throwaway API server (ports 4310 and 4311): a
 * real run makes a prop, the trace shows its prompt as coloured pieces, a piece names its source and opens the source's
 * page, the page lists the record that read it and leads back to it, the profile lists what the last run read, and a 3D
 * model is then made from the picture chosen for the record. Pages are checked at phone width for sideways scrolling.
 * WORLD_SCREENSHOT_DIR saves a picture of each screen.
 */

const WRITE = { 'X-Studio-Request': '1' };
const shots = process.env['WORLD_SCREENSHOT_DIR'];

async function shot(page: Page, name: string): Promise<void> {
  if (!shots) return;
  await page.screenshot({ path: join(shots, `${name}.png`), fullPage: true });
}

/** What can be scrolled sideways: the document or the app's scrolling area. Empty when nothing can. */
async function sidewaysScrollers(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const wide = (el: Element) => el.scrollWidth > el.clientWidth + 1;
    const found: string[] = [];
    if (wide(document.documentElement)) found.push(`document ${document.documentElement.scrollWidth} > ${document.documentElement.clientWidth}`);
    const content = document.querySelector('.content');
    if (content && wide(content)) found.push(`content ${content.scrollWidth} > ${content.clientWidth}`);
    return found;
  });
}

async function generate(page: Page, pipeline: string, fill: () => Promise<void>): Promise<void> {
  const panel = page.locator('[data-panel="generate"]');
  await expect(panel).toBeVisible();
  await panel.locator('[data-field="pipeline"]').selectOption({ label: pipeline });
  await fill();
  await panel.locator('[data-action="start-run"]').click();
  await expect(page.getByTestId('run-status')).toHaveAttribute('data-status', 'succeeded', { timeout: 150_000 });
}

test('a prompt shows where its words came from, and a mesh is made from the chosen picture', async ({ page, request }) => {
  test.setTimeout(300_000);
  const problems: string[] = [];
  page.on('pageerror', (e) => problems.push(e.message));
  const folder = join(mkdtempSync(join(tmpdir(), 'world-e2e-provenance-')), 'provenance-demo');
  const created = await request.post('/api/v1/projects', { headers: WRITE, data: { folder, slug: 'provenance-demo', name: 'Provenance Demo' } });
  expect(created.status()).toBe(201);
  const made = await request.post('/api/v1/projects/provenance-demo/entities', {
    headers: WRITE,
    data: { kind: 'prop', data: { name: 'Brass key', brief: 'A heavy brass key on a ring.', size: 'hand' } },
  });
  const key = (await made.json()) as { id: string };
  try {
    await test.step('make a prop on the stand-in and choose its picture', async () => {
      await page.goto(`/world/prop/${key.id}`);
      await page.locator('[data-action="generate"]').click();
      await generate(page, 'Props from a concept image', async () => {
        await page.locator('[data-panel="generate"] [data-field="style"]').selectOption('clay');
      });
      const strip = page.getByTestId('candidate-strip');
      await expect(strip.locator('[data-candidate]')).toHaveCount(1); // the Image tab lists the concept picture
      await strip.locator('[data-candidate$=".png"]').click();
      await page.locator('[data-action="use-this"]').click();
      await expect(page.getByTestId('hero-image')).toBeVisible();
    });

    await test.step('the profile lists what the last run read', async () => {
      const feeds = page.getByTestId('feeds');
      await expect(feeds.locator('[data-source="prop.clay"]')).toBeVisible();
      await expect(feeds.locator('[data-source="prop.repair_shop"]')).toBeVisible();
      await expect(feeds.locator('[data-source="prop.contract"]')).toBeVisible();
      await shot(page, 'profile-feeds');
    });

    await test.step('the trace shows the prompt as pieces, and a piece names its source', async () => {
      await page.locator('[data-action="open-trace"]').click();
      await page.locator('[data-stage="concept"] .col-head').click();
      const prompt = page.getByTestId('stage-prompt');
      await expect(prompt.locator('button.part[data-tone="subject"]')).toContainText('A heavy brass key on a ring.');
      await expect(prompt.locator('button.part[data-tone="style"]').first()).toBeVisible();
      await expect(prompt.locator('button.part[data-tone="motif"]')).toContainText('repair-shop');
      await expect(prompt.locator('button.part[data-tone="capture"]').first()).toContainText('white background');
      await expect(page.getByTestId('prompt-legend').first().locator('li')).toHaveCount(4);
      await prompt.locator('button.part[data-tone="style"]').first().hover();
      await expect(page.getByTestId('part-source').first()).toContainText('The style pack "clay"');
      await shot(page, 'trace-prompt-parts');
      // The negative prompt comes from the parent pack, not from clay.
      await page.getByTestId('stage-negative').locator('button.part').hover();
      await expect(page.getByTestId('part-source').last()).toContainText('The style pack "vinyl_toy"');
    });

    await test.step('follow the piece to its source page, then back to the record', async () => {
      await page.getByTestId('stage-prompt').locator('button.part[data-tone="style"]').first().click();
      await page.getByTestId('part-source').first().locator('[data-action="open-source"]').click();
      await expect(page).toHaveURL(/\/sources\/style\/prop\.clay$/);
      await expect(page.getByTestId('source-name')).toHaveText('clay');
      await expect(page.getByTestId('source-location')).toContainText('pipeline/pipelines/examples/prop/styles/clay/style.json');
      await expect(page.getByTestId('source-readonly')).toContainText('read-only');
      await expect(page.locator('[data-key="prompt.negative"]')).toContainText('text, watermark');
      const readers = page.getByTestId('source-readers');
      await expect(readers).toContainText('Brass key');
      await expect.poll(() => readers.locator('img.thumb').first().evaluate((i: HTMLImageElement) => i.complete && i.naturalWidth > 0)).toBe(true);
      await shot(page, 'source-page');
      await readers.locator('[data-action="open-entity"]').click();
      await expect(page).toHaveURL(new RegExp(`/world/prop/${key.id}$`));
    });

    await test.step('make a 3D model from the picture already chosen', async () => {
      await page.locator('[data-action="generate-again"]').click();
      await generate(page, 'A rough 3D model from a concept image', async () => {
        const picture = page.locator('[data-panel="generate"] [data-field="start_image"]');
        await picture.selectOption('main');
        await page.locator('[data-panel="generate"] [data-field="prompt"]').fill('');
        await expect(page.getByTestId('generate-problems')).toHaveCount(0);
      });
      await page.locator('[data-panel="generate"] [data-action="open-run"]').click();
      const strip = page.getByTestId('filmstrip');
      await expect(strip.locator('[data-stage="concept"]')).toHaveAttribute('data-status', 'supplied');
      await expect(strip.locator('[data-stage="mesh"]')).toHaveAttribute('data-status', 'completed');
      await strip.locator('[data-stage="concept"] .col-head').click();
      await expect(page.getByTestId('stage-prompt')).toHaveCount(0); // no prompt was used
      await shot(page, 'trace-from-chosen-image');
    });

    await test.step('phone width: nothing scrolls sideways', async () => {
      await page.setViewportSize({ width: 390, height: 844 });
      await expect.poll(() => sidewaysScrollers(page)).toEqual([]);
      await shot(page, 'phone-trace-supplied');
      for (const [name, url] of [
        ['phone-source', '/sources/style/prop.clay'],
        ['phone-sources', '/sources'],
        ['phone-profile', `/world/prop/${key.id}`],
      ]) {
        await page.goto(url);
        await expect(page.locator('main, .content').first()).toBeVisible();
        await page.waitForTimeout(400);
        expect(await sidewaysScrollers(page), name).toEqual([]);
        await shot(page, name);
      }
      // The first run's trace, with its long prompt open.
      await page.goto(`/world/prop/${key.id}`);
      await page.locator('[data-action="open-trace"]').first().click();
      await page.locator('[data-stage="concept"] .col-head').click();
      await page.getByTestId('stage-prompt').locator('button.part').first().click();
      expect(await sidewaysScrollers(page), 'phone-trace-prompt').toEqual([]);
      await shot(page, 'phone-trace-prompt');
    });
  } finally {
    await request.delete('/api/v1/projects/provenance-demo', { headers: WRITE });
  }
  expect(problems).toEqual([]);
});
