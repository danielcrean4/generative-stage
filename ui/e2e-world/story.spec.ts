import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { cpSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

/**
 * The story page against a real API server: a project is given the invented lighthouse kinds (with
 * x-story and x-vocabulary marks) and a few entities, then the page draws them, focuses one, shows a
 * node's conditions in plain words and falls back to a list at phone width.
 * Set WORLD_SCREENSHOT_DIR to save screenshots (desktop and 390 px wide).
 */

const shots = process.env['WORLD_SCREENSHOT_DIR'];
const WRITE = { 'X-Studio-Request': '1' };
const FIXTURE = resolve(__dirname, '..', '..', 'core', 'tests', 'fixtures', 'lighthouse');
const P = '/api/v1/projects/story-demo';

async function shot(page: Page, name: string): Promise<void> {
  if (shots) await page.screenshot({ path: join(shots, `${name}.png`), fullPage: true });
}

async function create(request: APIRequestContext, kind: string, data: object): Promise<string> {
  const made = await request.post(`${P}/entities`, { headers: WRITE, data: { kind, data } });
  expect(made.status(), await made.text()).toBe(201);
  return (await made.json()).id;
}

async function fill(request: APIRequestContext): Promise<Record<string, string>> {
  const north = await create(request, 'lamp', { key: 'north', name: 'North lamp' });
  await create(request, 'lamp', { key: 'south', name: 'South lamp' });
  const errand = await create(request, 'errand', {
    key: 'fetch_oil',
    name: 'Fetch oil',
    steps: {
      '10': { note: 'Find the oil in the cellar.', effects: [{ do: 'light', lamp: 'north' }] },
      '20': { note: 'Carry it up the stairs.', when: { all: [{ fact: 'keeper.oil', gte: 2 }, { fact: 'keeper.seen', has: 'cellar' }] } },
      '30': { note: 'Fill the lamp.', mode: 'once' },
    },
  });
  const talk = await create(request, 'talk', {
    key: 'keeper',
    opening: {
      line: 'Evening. The lamp is low.',
      replies: [
        { say: 'Need oil?', goto: 'oil' },
        { say: 'Is it lit?', goto: 'lit', requires: { fact: 'lamp(north).lit', eq: true } },
        { say: 'Goodbye.' },
      ],
    },
    lines: {
      oil: {
        line: 'Two litres, from the cellar.',
        errand: { key: 'fetch_oil', step: 10 },
        replies: [{ say: 'On my way.', effects: [{ do: 'advance', errand: 'fetch_oil', step: 20 }] }],
      },
      lit: { line: 'Burning bright, thanks to you.', requires: { fact: 'errand(fetch_oil).done', eq: true } },
      thanks: { line: 'You kept the light.', requires: { after_step: 30 } },
    },
  });
  const tends = await request.post(`${P}/links`, { headers: WRITE, data: { type: 'tends', source: errand, target: north } });
  expect(tends.status(), await tends.text()).toBe(201);
  return { north, errand, talk };
}

test('the story page draws the graph, focuses an entity and explains a condition', async ({ page, request }) => {
  test.setTimeout(90_000);
  const problems: string[] = [];
  page.on('pageerror', (e) => problems.push(e.message));
  const root = mkdtempSync(join(tmpdir(), 'world-e2e-project-'));
  const folder = join(root, 'story-demo');
  const created = await request.post('/api/v1/projects', { headers: WRITE, data: { folder, slug: 'story-demo', name: 'Story Demo' } });
  expect(created.status()).toBe(201);
  rmSync(join(folder, 'kinds'), { recursive: true, force: true });
  cpSync(FIXTURE, join(folder, 'kinds'), { recursive: true });
  try {
    const ids = await fill(request);
    await page.goto('/story');
    const graph = page.getByTestId('story-graph');
    await expect(graph).toBeVisible();
    await expect(page.getByTestId('story-node')).toHaveCount(3); // the south lamp has no story
    await page.getByText('Include entities with no story').click();
    await expect(page.getByTestId('story-node')).toHaveCount(4);
    await page.locator(`[data-node="${ids['talk']}"]`).click();
    await expect(page.getByTestId('story-panel')).toContainText('changes');
    await shot(page, 'story-01-overview');

    await page.getByTestId('focus-entity').click();
    await expect(page).toHaveURL(new RegExp(`entity=${ids['talk']}`));
    await expect(page.locator(`[data-node="${ids['talk']}#/lines/oil"]`)).toBeVisible();
    await page.locator(`[data-node="${ids['talk']}#/opening"]`).click();
    const panel = page.getByTestId('story-panel');
    await expect(panel).toContainText('Evening. The lamp is low.');
    await expect(panel.getByTestId('panel-out').filter({ hasText: 'Is it lit?' })).toContainText('if lamp(north).lit is true');
    await expect(panel).toContainText('Reads lamp(north).lit');
    await page.locator(`[data-node="${ids['talk']}#/lines/thanks"]`).click();
    await expect(panel).toContainText('Older shorthand');
    await page.locator(`[data-node="${ids['talk']}#/lines/lit"]`).click();
    await expect(panel.getByTestId('panel-condition')).toContainText('errand(fetch_oil).done is true');
    await shot(page, 'story-02-focus');

    await page.getByTestId('story-entity').selectOption(ids['errand']);
    await page.locator(`[data-node="${ids['errand']}#/steps/20"]`).click();
    await expect(panel.getByTestId('panel-condition')).toContainText('keeper.oil is at least 2 and keeper.seen has cellar');
    await page.getByTestId('mode-list').click();
    await expect(page.getByTestId('story-list')).toContainText('step 30');
    await shot(page, 'story-03-list');
    await page.getByTestId('open-profile').click();
    await expect(page).toHaveURL(new RegExp(`/world/errand/${ids['errand']}$`));

    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`/story?entity=${ids['talk']}`);
    await expect(page.getByTestId('story-list')).toBeVisible();
    await page.locator(`.story-list [data-node="${ids['talk']}#/opening"]`).click();
    await expect(page.getByTestId('story-panel')).toContainText('Need oil?');
    const wide = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
    expect(wide, 'no sideways scrolling at phone width').toBe(false);
    await shot(page, 'story-04-phone');
    expect(problems).toEqual([]);
  } finally {
    await request.delete('/api/v1/projects/story-demo', { headers: WRITE });
  }
});
