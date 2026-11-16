import { expect, test } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { mkdirSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

/**
 * The parametric example (a lamp) on the stand-in adapters of the throwaway API server (ports 4311 and 4310): the
 * slider form previews live, Save as candidate and Use this work, a batch of 20 is made with no model and triaged on a
 * contact sheet, the marks survive a reload, the kept tiles become records and the export carries them.
 */

const WRITE = { 'X-Studio-Request': '1' };
const SHOTS = resolve(process.cwd(), 'test-output', 'parametric');

// The other specs expect no leftover project (world.spec starts from an empty list), so the lamps project goes, pass or fail.
test.afterEach(async ({ request }) => {
  await request.delete('/api/v1/projects/lamps', { headers: WRITE });
});

test('sliders preview live; a batch is triaged; a kept row exports', async ({ page, request }) => {
  test.setTimeout(240_000);
  mkdirSync(SHOTS, { recursive: true });
  const folder = join(mkdtempSync(join(tmpdir(), 'world-e2e-parametric-')), 'lamps');
  const created = await request.post('/api/v1/projects', { headers: WRITE, data: { folder, slug: 'lamps', name: 'Lamps' } });
  expect(created.status()).toBe(201);
  execFileSync('python3', [resolve(process.cwd(), '..', 'scripts', 'add_parametric_example.py'), folder]);
  const made = await request.post('/api/v1/projects/lamps/entities', {
    headers: WRITE,
    data: { kind: 'lamp', data: { name: 'Desk lamp', shade: 'drum', height_cm: 80, base_radius_cm: 10, has_arm: false, colour: '#a0714f', drum_radius_cm: 20 } },
  });
  expect(made.status()).toBe(201);
  const lamp = (await made.json()) as { id: string };

  await test.step('the slider form previews live', async () => {
    await page.goto(`/world/lamp/${lamp.id}`);
    const panel = page.locator('[data-panel="parametric"]');
    await expect(panel).toBeVisible();
    const preview = panel.getByTestId('parametric-preview');
    await expect(preview).toBeVisible();
    const first = await preview.getAttribute('data-preview');
    await expect(panel.locator('[data-param="arm_reach_cm"]')).toHaveCount(0); // the switch is off
    await expect(panel.locator('[data-param="cone_top_cm"]')).toHaveCount(0); // the other shade's field

    await panel.locator('[data-param="height_cm"] input').fill('150');
    await expect(panel.locator('[data-value="height_cm"]')).toHaveText('150 cm');
    await expect(preview).not.toHaveAttribute('data-preview', first!, { timeout: 10_000 });

    await panel.locator('[data-param="has_arm"] input').check();
    await expect(panel.locator('[data-param="arm_reach_cm"]')).toHaveCount(1);
    await panel.locator('[data-param="shade"] select').selectOption('cone');
    await expect(panel.locator('[data-param="cone_top_cm"]')).toHaveCount(1);
    await expect(panel.locator('[data-param="drum_radius_cm"]')).toHaveCount(0);
    await expect(panel.getByTestId('parametric-gates').locator('li')).toHaveCount(3);
    await expect(panel.getByTestId('parametric-busy')).toHaveCount(0);
    await page.screenshot({ path: join(SHOTS, 'sliders.png') });
  });

  await test.step('Save as candidate, then Use this', async () => {
    const panel = page.locator('[data-panel="parametric"]');
    await panel.locator('[data-action="param-save"]').click();
    await expect(panel.getByTestId('parametric-notice')).toHaveText('Saved as a candidate.');
    await panel.locator('[data-action="param-use"]').click();
    await expect
      .poll(async () => {
        const saved = await request.get(`/api/v1/projects/lamps/entities/${lamp.id}`);
        const data = ((await saved.json()) as { data: Record<string, unknown> }).data;
        const chosen = await request.get(`/api/v1/projects/lamps/entities/${lamp.id}/chosen`);
        return [data['shade'], data['height_cm'], Object.keys(((await chosen.json()) as { chosen: object }).chosen).includes('main')];
      })
      .toEqual(['cone', 150, true]);
    await expect(page.getByTestId('candidate-strip').locator('[data-candidate]').first()).toBeVisible();
  });

  let batchUrl = '';
  await test.step('make a batch of 20 and see the contact sheet', async () => {
    await page.goto('/world/lamp/batch');
    await page.locator('[data-cross="theme"] [data-value="industrial"]').uncheck();
    await page.locator('[data-cross="material"] [data-value="steel"]').uncheck();
    await page.locator('[data-field="count"]').fill('5');
    const started = Date.now();
    await page.locator('[data-action="make-batch"]').click();
    await expect(page.locator('[data-panel="contact-sheet"]')).toBeVisible({ timeout: 60_000 });
    expect(Date.now() - started).toBeLessThan(30_000);
    await expect(page.locator('[data-tile]')).toHaveCount(20);
    await expect(page.getByTestId('batch-summary')).toContainText('20 variants');
    batchUrl = page.url();
    await page.screenshot({ path: join(SHOTS, 'contact-sheet.png'), fullPage: true });
  });

  await test.step('triage: keep, fix with a note, remove; marks survive a reload', async () => {
    const tile = (id: string) => page.locator(`[data-tile="${id}"]`);
    await tile('v001').locator('[data-triage="keep"]').click();
    await tile('v002').locator('[data-triage="keep"]').click();
    await tile('v003').locator('[data-triage="fix"]').click();
    await tile('v003').locator('[data-field="triage-note"]').fill('arm too long');
    await tile('v003').locator('[data-field="triage-note"]').blur();
    await tile('v004').locator('[data-triage="remove"]').click();
    await expect(page.getByTestId('triage-tally')).toHaveText('keep 2 · fix 1 · improve 0 · remove 1');
    await page.goto(batchUrl);
    await expect(tile('v001')).toHaveAttribute('data-mark', 'keep');
    await expect(tile('v003').locator('[data-field="triage-note"]')).toHaveValue('arm too long');
    await expect(page.getByTestId('triage-tally')).toHaveText('keep 2 · fix 1 · improve 0 · remove 1');
    await page.screenshot({ path: join(SHOTS, 'triage.png'), fullPage: true });
  });

  await test.step('the kept tiles become records and the export carries them', async () => {
    await page.locator('[data-action="create-kept"]').click();
    await expect(page.getByTestId('batch-notice')).toHaveText('2 records created, each with its picture chosen.', { timeout: 30_000 });
    const list = await request.get('/api/v1/projects/lamps/entities?kind=lamp');
    const ids = ((await list.json()) as { entities: { id: string }[] }).entities.map((e) => e.id);
    expect(ids.length).toBe(3); // the desk lamp and the two kept tiles
    const exported = await request.post('/api/v1/projects/lamps/exports', { headers: WRITE, data: { kinds: ['lamp'] } });
    expect(exported.status()).toBe(201);
    const id = ((await exported.json()) as { id: string }).id;
    const manifest = JSON.stringify(await (await request.get(`/api/v1/projects/lamps/exports/${id}`)).json());
    for (const record of ids) expect(manifest).toContain(record);
  });
});
