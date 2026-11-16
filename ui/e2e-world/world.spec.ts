import { expect, test, type Page } from '@playwright/test';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

/**
 * The world-model screens against a real API server on a temporary project. One flow, in
 * order: make a project; make a setting, a character and a prop; edit one; link them; revert a
 * revision; meet a concurrent change; archive and restore. It also blocks every request to a
 * host outside this machine, which shows the screens do not need the network.
 */

const shots = process.env['WORLD_SCREENSHOT_DIR'];

async function shot(page: Page, name: string): Promise<void> {
  if (!shots) return;
  // The page scrolls inside the content area, so a tall window shows a whole screen at once.
  const size = page.viewportSize()!;
  await page.setViewportSize({ width: size.width, height: 1500 });
  await page.screenshot({ path: join(shots, `${name}.png`) });
  await page.setViewportSize(size);
}

const field = (page: Page, pointer: string) => page.locator(`[data-field="${pointer}"]`);
const input = (page: Page, pointer: string) => field(page, pointer).locator('input, textarea').first();

async function fillText(page: Page, pointer: string, value: string): Promise<void> {
  await input(page, pointer).fill(value);
}

async function addTag(page: Page, tag: string): Promise<void> {
  const box = field(page, '/data/tags').locator('input');
  await box.fill(tag);
  await box.press('Enter');
}

test('build a small world through the app', async ({ page, request }) => {
  const blocked: string[] = [];
  await page.route('**/*', (route) => {
    const host = new URL(route.request().url()).hostname;
    if (host === '127.0.0.1' || host === 'localhost') return route.continue();
    blocked.push(route.request().url());
    return route.abort();
  });
  const problems: string[] = [];
  page.on('pageerror', (e) => problems.push(e.message));
  page.on('console', (m) => {
    if (m.type() === 'error' && !m.text().includes('ERR_FAILED') && !m.text().includes('Failed to load resource')) problems.push(m.text());
  });

  const folder = join(mkdtempSync(join(tmpdir(), 'world-e2e-project-')), 'second-project');

  await test.step('projects: empty, then a first project', async () => {
    await page.goto('/');
    await expect(page).toHaveURL(/\/projects$/);
    await expect(page.getByTestId('no-projects')).toBeVisible();
    await shot(page, '01-projects-empty');

    // A wrong folder is refused on the folder field.
    await page.locator('input[name="name"]').fill('Second Project');
    await expect(page.locator('input[name="slug"]')).toHaveValue('second-project');
    await page.locator('input[name="folder"]').fill('not-absolute');
    await page.getByRole('button', { name: 'Make project' }).click();
    await expect(page.locator('form[data-form="create"] .field-error')).toContainText('absolute');
    await shot(page, '02-projects-error');

    await page.locator('input[name="folder"]').fill(folder);
    await page.getByRole('button', { name: 'Make project' }).click();
    await expect(page.getByTestId('world-project')).toContainText('Second Project');
    await expect(page.locator('[data-project="second-project"]')).toContainText('Current');
    for (const label of ['Settings', 'Characters', 'Props']) {
      await expect(page.locator('app-left-nav')).toContainText(label);
    }
    // The kinds are grouped by family, in family order; the script kind carries its form.
    await expect(page.locator('app-left-nav [data-family]')).toHaveCount(4);
    expect(await page.locator('app-left-nav [data-family]').evaluateAll((els) => els.map((e) => e.getAttribute('data-family')))).toEqual([
      'prop',
      'character',
      'setting',
      'script',
    ]);
    await expect(page.locator('a[data-kind="script"] .form-badge')).toHaveText('linear');
    await expect(page.locator('[data-nav="story"]')).toContainText('Story graph');
    await shot(page, '03-projects');
  });

  await test.step('kinds: sidebar, empty list, kind page', async () => {
    await page.locator('a[data-kind="setting"]').click();
    await expect(page.getByTestId('empty-kind')).toBeVisible();
    await shot(page, '04-list-empty');
    await page.getByRole('link', { name: 'About this kind' }).click();
    await expect(page.locator('[data-page="kind"]')).toContainText('Title field');
    await expect(page.locator('tr[data-field="/data/scale"]')).toContainText('one of: room');
    await shot(page, '05-kind');
  });

  async function createEntity(kindId: string, fill: () => Promise<void>): Promise<string> {
    await page.locator(`a[data-kind="${kindId}"]`).click();
    await page.locator('[data-action="create"]').click();
    await fill();
    await page.locator('[data-action="save"]').click();
    await expect(page).toHaveURL(new RegExp(`/world/${kindId}/[0-9a-f-]{36}$`));
    return page.url().split('/').pop()!;
  }

  let guide = '';
  let key = '';

  await test.step('entities: validation, then a setting, a character and a prop', async () => {
    await page.locator('a[data-kind="setting"]').click();
    await page.locator('[data-action="create"]').click();
    await page.locator('[data-action="save"]').click();
    await expect(field(page, '/data/name').locator('.field-error')).toBeVisible();
    await shot(page, '06-entity-error');

    await fillText(page, '/data/name', 'Hall');
    await fillText(page, '/data/brief', 'A large hall with a storage room.');
    await addTag(page, 'outdoor');
    await field(page, '/data/scale').locator('select').selectOption('building');
    await page.locator('[data-action="save"]').click();
    await expect(page).toHaveURL(/\/world\/setting\/[0-9a-f-]{36}$/);
    await expect(page.locator('[data-page="profile"] h1')).toHaveText('Hall');
    await shot(page, '07-entity-created');

    guide = await createEntity('character', async () => {
      await fillText(page, '/data/name', 'Guide');
      await fillText(page, '/data/brief', 'Shows visitors around the town.');
      await fillText(page, '/data/role', 'guide');
    });
    key = await createEntity('prop', async () => {
      await fillText(page, '/data/name', 'Key');
      await addTag(page, 'hall');
      await addTag(page, 'storage room');
    });
    await expect(page.locator('a[data-kind="prop"] .count')).toHaveText('1');
  });

  await test.step('edit: a second revision', async () => {
    await page.locator('[data-action="edit-all"]').click();
    await expect(page).toHaveURL(new RegExp(`/world/prop/${key}/edit$`));
    await expect(page.locator('[data-action="save"]')).toBeDisabled();
    await fillText(page, '/data/material', 'steel');
    await expect(page.locator('[data-action="save"]')).toBeEnabled();
    await page.locator('input[name="note"]').fill('Steel, not iron');
    await page.locator('[data-action="save"]').click();
    await expect(page.getByText('Revision 2, saved')).toBeVisible();
    await expect(page.locator('[data-panel="revisions"] [data-revision]')).toHaveCount(2);
  });

  await test.step('links: out and in, followed to the other page', async () => {
    await page.locator('[data-action="add-link"]').click();
    await page.locator('[data-testid="link-adder"] select').selectOption({ label: 'belongs to (Characters)' });
    await page.locator('[data-testid="link-adder"] input[type="search"]').fill('guide');
    await page.getByRole('button', { name: 'Link Guide' }).click();
    await expect(page.locator('[data-link-group="belongs_to|out"]')).toContainText('Guide');
    await shot(page, '08-links');

    // From the guide's side the same link reads with the inverse label, and the key links back.
    await page.locator('[data-link-group="belongs_to|out"] a', { hasText: 'Guide' }).click();
    await expect(page).toHaveURL(new RegExp(`/world/character/${guide}$`));
    await expect(page.locator('[data-page="profile"] h1')).toHaveText('Guide');
    await page.locator('[data-action="edit-all"]').click();
    await expect(page.locator('[data-link-group="belongs_to|in"]')).toContainText('Key');
    await expect(page.locator('[data-link-group="belongs_to|in"] h4')).toHaveText('owns');

    await page.locator('[data-action="add-link"]').click();
    await page.locator('[data-testid="link-adder"] select').selectOption({ label: 'lives in (Settings)' });
    await page.getByRole('button', { name: 'Link Hall' }).click();
    await expect(page.locator('[data-link-group="lives_in|out"]')).toContainText('Hall');

    // A link is removed, and added again.
    await page.getByRole('button', { name: 'Remove link: Hall' }).click();
    await expect(page.locator('[data-link-group="lives_in|out"]')).toHaveCount(0);
    await page.locator('[data-action="add-link"]').click();
    await page.locator('[data-testid="link-adder"] select').selectOption({ label: 'lives in (Settings)' });
    await page.getByRole('button', { name: 'Link Hall' }).click();
    await expect(page.locator('[data-link-group="lives_in|out"]')).toContainText('Hall');
  });

  await test.step('revisions: view an old one, revert to it', async () => {
    await page.goto(`/world/prop/${key}/edit`);
    await expect(page.locator('[data-revision="2"]')).toContainText('Steel, not iron');
    await page.locator('[data-revision="1"]').getByRole('button', { name: 'View' }).click();
    await expect(page.locator('[data-banner="viewing"]')).toContainText('revision 1');
    await expect(input(page, '/data/material')).toHaveValue('');
    await expect(input(page, '/data/name')).not.toBeEditable();
    await shot(page, '09-revision-view');
    await page.getByRole('button', { name: 'Revert to this revision' }).click();
    await page.getByRole('dialog').getByRole('button', { name: 'Revert', exact: true }).click();
    await expect(page.getByText('Revision 3, saved')).toBeVisible();
    await expect(input(page, '/data/material')).toHaveValue('');
    await expect(page.locator('[data-panel="revisions"] [data-revision]')).toHaveCount(3);
  });

  await test.step('unsaved changes: leaving asks first', async () => {
    await fillText(page, '/data/condition', 'used');
    await page.locator('a[data-kind="character"]').click();
    await expect(page.getByRole('dialog')).toContainText('not saved');
    await shot(page, '10-unsaved');
    await page.getByRole('dialog').getByRole('button', { name: 'Keep editing' }).click();
    await expect(page).toHaveURL(new RegExp(`/world/prop/${key}/edit$`));
    await expect(input(page, '/data/condition')).toHaveValue('used');
  });

  await test.step('conflict: a change made behind the page is never overwritten', async () => {
    // Someone else saves revision 4 through the API while this page still holds revision 3.
    const hit = await request.put(`/api/v1/projects/second-project/entities/${key}`, {
      headers: { 'X-Studio-Request': '1' },
      data: { revision: 3, data: { name: 'Key', material: 'iron' }, note: 'someone else' },
    });
    expect(hit.ok()).toBeTruthy();
    await page.locator('[data-action="save"]').click();
    await expect(page.locator('[data-banner="conflict"]')).toBeVisible();
    await expect(page.locator('[data-banner="conflict"]')).toContainText('revision 4');
    await expect(input(page, '/data/condition')).toHaveValue('used');
    await shot(page, '11-conflict');
    await page.getByRole('button', { name: 'Reload the latest' }).click();
    await expect(page.getByText('Revision 4, saved')).toBeVisible();
    await expect(input(page, '/data/material')).toHaveValue('iron');
    await expect(input(page, '/data/condition')).toHaveValue('');
  });

  await test.step('archive and restore', async () => {
    await page.locator('[data-action="archive"]').click();
    await expect(page.locator('[data-banner="archived"]')).toBeVisible();
    await expect(page.locator('[data-action="save"]')).toHaveCount(0);
    await shot(page, '12-archived');

    await page.locator('a[data-kind="prop"]').click();
    await expect(page.getByTestId('empty-kind')).toBeVisible();
    await page.getByRole('checkbox', { name: 'Show archived' }).check();
    const row = page.locator(`[data-entity="${key}"]`);
    await expect(row).toContainText('Archived');
    await shot(page, '13-list-archived');
    await row.getByRole('button', { name: 'Restore' }).click();
    await expect(row).not.toContainText('Archived');
    await expect(page.locator('a[data-kind="prop"] .count')).toHaveText('1');

    await page.getByRole('checkbox', { name: 'Show archived' }).uncheck();
    await expect(page.locator('[data-entity]')).toHaveCount(1);
    await shot(page, '14-list');
    await page.getByLabel('Search').fill('key');
    await expect(page.locator('[data-entity]')).toHaveCount(1);
    await page.getByLabel('Search').fill('zzz');
    await expect(page.getByTestId('no-match')).toBeVisible();
    await shot(page, '14b-list-no-match');
  });

  await test.step('projects: a second project, switching between them', async () => {
    await page.locator('a[href="/projects"]').first().click();
    await page.locator('input[name="name"]').fill('Third Project');
    await page.locator('input[name="folder"]').fill(join(mkdtempSync(join(tmpdir(), 'world-e2e-project-')), 'third'));
    await page.getByRole('button', { name: 'Make project' }).click();
    await expect(page.getByTestId('world-project')).toContainText('Third Project');
    // The new project is empty: nothing from the first one shows under its name.
    await expect(page.locator('a[data-kind="prop"] .count')).toHaveText('0');
    await expect(page.locator('[data-project="third-project"]')).toContainText('Current');

    await page.locator('[data-project="second-project"]').getByRole('button', { name: 'Use this project' }).click();
    await expect(page.getByTestId('world-project')).toContainText('Second Project');
    await expect(page.locator('a[data-kind="prop"] .count')).toHaveText('1');
    await shot(page, '15-two-projects');

    // The bar's menu switches too, and the list page then shows that project's entities.
    await page.getByRole('button', { name: 'Switch project' }).click();
    await page.getByRole('menuitem', { name: 'Third Project' }).click();
    await expect(page.getByTestId('world-project')).toContainText('Third Project');
    await page.locator('a[data-kind="prop"]').click();
    await expect(page.getByTestId('empty-kind')).toBeVisible();
    await page.locator('a[href="/projects"]').first().click();
    await page.locator('[data-project="second-project"]').getByRole('button', { name: 'Use this project' }).click();
    await page.locator('a[data-kind="prop"]').click();
    await expect(page.locator(`[data-entity="${key}"]`)).toBeVisible();
  });

  await test.step('projects: remove from the list leaves the folder', async () => {
    await page.locator('a[href="/projects"]').first().click();
    await page.locator('[data-project="second-project"]').getByRole('button', { name: 'Remove from list' }).click();
    await expect(page.getByRole('dialog')).toContainText('stay exactly as they are');
    await shot(page, '16-remove-confirm');
    await page.getByRole('dialog').getByRole('button', { name: 'Remove from list' }).click();
    await expect(page.locator('[data-project="second-project"]')).toHaveCount(0);
    // The current project was removed, so the other one takes its place.
    await expect(page.getByTestId('world-project')).toContainText('Third Project');
    // Opening the same project file again brings everything back.
    await page.locator('input[name="project_file"]').fill(join(folder, 'studio.project.json'));
    await page.getByRole('button', { name: 'Open project' }).click();
    await expect(page.getByTestId('world-project')).toContainText('Second Project');
    await expect(page.locator('a[data-kind="prop"] .count')).toHaveText('1');
  });

  expect(problems, problems.join('\n')).toEqual([]);
  // The old page's fonts and scripts come from outside hosts; the world screens ask for nothing,
  // so whatever was blocked must be the shell's existing index.html links and nothing else.
  const unexpected = blocked.filter((u) => !/fonts\.(googleapis|gstatic)\.com|cdn\.jsdelivr\.net/.test(u));
  expect(unexpected).toEqual([]);
});
