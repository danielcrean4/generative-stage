import { expect, test, type Page } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

/**
 * The vocabulary page against a real API server: a project is given the invented lighthouse
 * vocabulary through PUT, then the page lists it and its condition box checks as you type.
 * Set WORLD_SCREENSHOT_DIR to save screenshots (desktop and 390 px wide).
 */

const shots = process.env['WORLD_SCREENSHOT_DIR'];
const WRITE = { 'X-Studio-Request': '1' };
const FIXTURE = resolve(__dirname, '..', '..', 'core', 'tests', 'fixtures', 'lighthouse', 'vocabulary.json');

async function shot(page: Page, name: string): Promise<void> {
  if (shots) await page.screenshot({ path: join(shots, `${name}.png`), fullPage: true });
}

test('the vocabulary page lists the words and checks a condition as you type', async ({ page, request }) => {
  test.setTimeout(90_000);
  const problems: string[] = [];
  page.on('pageerror', (e) => problems.push(e.message));
  const folder = join(mkdtempSync(join(tmpdir(), 'world-e2e-project-')), 'vocab-demo');
  const created = await request.post('/api/v1/projects', { headers: WRITE, data: { folder, slug: 'vocab-demo', name: 'Vocabulary Demo' } });
  expect(created.status()).toBe(201);
  try {
    await page.goto('/vocabulary');
    await expect(page.getByTestId('no-vocabulary')).toBeVisible();
    const put = await request.put('/api/v1/projects/vocab-demo/vocabulary', { headers: WRITE, data: JSON.parse(readFileSync(FIXTURE, 'utf8')) });
    expect(put.status(), await put.text()).toBe(200);
    await page.reload();

    await expect(page.getByTestId('facts').locator('tbody tr')).toHaveCount(8);
    await expect(page.getByTestId('effects')).toContainText('advance');
    const box = page.getByTestId('condition-text');
    await box.fill('{"fact": "keeper.oil", "gte": "lots"}');
    await expect(page.getByTestId('condition-problems')).toContainText('/gte');
    await box.fill('{"fact": ');
    await expect(page.getByTestId('condition-status')).toContainText('not JSON yet');
    await box.fill('{"all": [{"fact": "keeper.oil", "gte": 2}, {"fact": "errand(fetch_oil).done", "eq": true}]}');
    await expect(page.getByTestId('condition-ok')).toBeVisible();
    await expect(page.getByTestId('condition-words')).toContainText('keeper.oil is at least 2 and errand(fetch_oil).done is true');

    await page.getByText('Add a fact').click();
    await page.getByTestId('add-fact').fill('keeper.seen');
    await page.getByTestId('add-operator').selectOption('has');
    await page.getByTestId('add-value').fill('cellar');
    await page.getByTestId('add-leaf').click();
    await expect(page.getByTestId('condition-words')).toContainText('keeper.seen has cellar');
    await expect(page.getByTestId('condition-ok')).toBeVisible();
    await shot(page, 'vocabulary-01-desktop');

    await page.setViewportSize({ width: 390, height: 844 });
    await page.reload();
    await expect(page.getByTestId('facts')).toBeVisible();
    const wide = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
    expect(wide, 'no sideways scrolling at phone width').toBe(false);
    await shot(page, 'vocabulary-02-phone');
    expect(problems).toEqual([]);
  } finally {
    await request.delete('/api/v1/projects/vocab-demo', { headers: WRITE });
  }
});
