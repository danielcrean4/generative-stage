import { expect, test } from '@playwright/test';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

/**
 * Generating from the profile, on the stand-in adapters of the throwaway API server (ports 4311 and 4310): an empty
 * profile offers Generate, the panel lists only the pipelines for the record's kind, a bad choice is stopped before
 * a request, the run shows its state, the candidates reach the strip, one is chosen, and Generate again is offered.
 */

const WRITE = { 'X-Studio-Request': '1' };

test('generate from the profile and choose a candidate', async ({ page, request }) => {
  test.setTimeout(180_000);
  const folder = join(mkdtempSync(join(tmpdir(), 'world-e2e-generate-')), 'generate-demo');
  const created = await request.post('/api/v1/projects', { headers: WRITE, data: { folder, slug: 'generate-demo', name: 'Generate Demo' } });
  expect(created.status()).toBe(201);
  const made = await request.post('/api/v1/projects/generate-demo/entities', {
    headers: WRITE,
    data: { kind: 'prop', data: { name: 'Brass key', brief: 'A heavy brass key on a ring.', size: 'hand' } },
  });
  const key = (await made.json()) as { id: string };
  try {
    await page.goto(`/world/prop/${key.id}`);
    await expect(page.getByTestId('nothing-chosen')).toBeVisible();
    await page.locator('[data-action="generate"]').click();
    const panel = page.locator('[data-panel="generate"]');
    await expect(panel).toBeVisible();

    await test.step('only the pipelines for a prop, with its brief as the prompt', async () => {
      const options = await panel.locator('[data-field="pipeline"] option').allTextContents();
      expect(options.length).toBe(4); // prop, 3D, concept, icon: not the character ones
      await expect(panel.locator('[data-field="prompt"]')).toHaveValue('A heavy brass key on a ring.');
      await expect(panel.locator('[data-adapter="image"]')).toBeVisible();
      await expect(panel.locator('[data-adapter="image"] option').first()).toContainText('Default (standin-image)');
    });

    await test.step('a choice out of range is stopped before any request', async () => {
      await panel.locator('[data-field="candidates"]').fill('9');
      await expect(page.getByTestId('generate-problems')).toContainText('Candidates');
      await expect(panel.locator('[data-action="start-run"]')).toBeDisabled();
      await panel.locator('[data-field="candidates"]').fill('2');
      await expect(panel.locator('[data-action="start-run"]')).toBeEnabled();
    });

    await test.step('start a concept image run and watch it end', async () => {
      await panel.locator('[data-field="pipeline"]').selectOption({ label: 'Concept images' });
      await panel.locator('[data-field="style"]').selectOption('sketch');
      await panel.locator('[data-field="candidates"]').fill('2');
      await panel.locator('[data-action="start-run"]').click();
      await expect(page.getByTestId('run-status')).toHaveAttribute('data-status', 'succeeded', { timeout: 120_000 });
      await expect(panel.locator('[data-action="open-run"]')).toBeVisible();
    });

    await test.step('the candidates are in the strip; choose one', async () => {
      const strip = page.getByTestId('candidate-strip');
      await expect(strip.locator('[data-candidate]')).toHaveCount(2);
      await strip.locator('[data-candidate]').first().click();
      await page.locator('[data-action="use-this"]').click();
      await expect(page.getByTestId('hero-image')).toBeVisible();
      await expect(page.locator('[data-action="generate-again"]')).toBeVisible();
    });

    await test.step('the run opens in the trace page', async () => {
      await panel.locator('[data-action="open-run"]').click();
      await expect(page).toHaveURL(/\/runs\//);
    });
  } finally {
    await request.delete('/api/v1/projects/generate-demo', { headers: WRITE });
  }
});
