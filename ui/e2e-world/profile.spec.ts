import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

/**
 * The profile page against a real API server. A stand-in run (three real PNG images from three
 * stages with their gate reports, and a 3D file) is put in the runs root; the test attaches it,
 * chooses from it, looks at candidates, uses one, edits fields in place and meets a conflict. It
 * writes notes (text, a mention, a pasted image, a pin, edit and delete) and checks the page at
 * phone width for sideways scrolling. Needs the throwaway API server and
 * dev server the config starts (ports 4311 and 4310).
 */

const shots = process.env['WORLD_SCREENSHOT_DIR'];
const API = '/api/v1/projects/profile-demo';
const WRITE = { 'X-Studio-Request': '1' };
const RUNS_ROOT = join(tmpdir(), `world-e2e-api-${process.env['WORLD_E2E_API_PORT'] ?? '4311'}`, 'data', 'asset-runs');
const SERVER = resolve(__dirname, '..', '..', 'server');
const SEED = resolve(__dirname, 'seed_run.py');

async function shot(page: Page, name: string, height = 1300): Promise<void> {
  if (!shots) return;
  const size = page.viewportSize()!;
  await page.setViewportSize({ width: size.width, height });
  await page.screenshot({ path: join(shots, `${name}.png`) });
  await page.setViewportSize(size);
}

async function api<T>(request: APIRequestContext, method: 'post' | 'put' | 'get', path: string, data?: unknown): Promise<T> {
  const response = await request[method](`${API}${path}`, { headers: WRITE, data });
  expect(response.status(), `${method} ${path}: ${await response.text()}`).toBeLessThan(300);
  return (await response.json()) as T;
}

async function imageLoaded(page: Page, selector: string): Promise<boolean> {
  return page.locator(selector).evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0);
}

/** What can be scrolled sideways: the document, the app's scrolling area or the profile itself. Empty when nothing can. */
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
    const profile = document.querySelector('[data-page="profile"]')!;
    if (wide(profile)) found.push(`profile ${profile.scrollWidth} > ${profile.clientWidth}`);
    return found;
  });
}

test('the profile page: chosen version, candidates, in-place edits, history', async ({ page, request }) => {
  test.setTimeout(120_000);
  const problems: string[] = [];
  page.on('pageerror', (e) => problems.push(e.message));
  page.on('console', (m) => {
    if (m.type() === 'error' && !m.text().includes('Failed to load resource') && !m.text().includes('ERR_FAILED')) problems.push(m.text());
  });

  // A project with a prop and a character, linked, with the stand-in run attached.
  const folder = join(mkdtempSync(join(tmpdir(), 'world-e2e-project-')), 'profile-demo');
  const created = await request.post('/api/v1/projects', { headers: WRITE, data: { folder, slug: 'profile-demo', name: 'Profile Demo' } });
  expect(created.status()).toBe(201);
  try {
    const bench = await api<{ id: string }>(request, 'post', '/entities', {
      kind: 'prop',
      data: { name: 'Workshop bench', brief: 'The heavy bench where machines are opened up and mended.', tags: ['workshop'], material: 'oak top', size: 'large' },
    });
    const mechanic = await api<{ id: string }>(request, 'post', '/entities', { kind: 'character', data: { name: 'Mechanic', brief: 'Keeps the lifts and pumps running.', role: 'repairs' } });
    await api(request, 'post', '/links', { type: 'belongs_to', source: bench.id, target: mechanic.id });
    const seeded = JSON.parse(
      execFileSync('uv', ['run', 'python', SEED, folder, bench.id, '1', RUNS_ROOT], { cwd: SERVER, encoding: 'utf8' }),
    ) as { job_id: string; candidates: string[] };
    const [concept, tidy, , mesh] = seeded.candidates;
    const run = seeded.job_id;
    await api(request, 'post', `/entities/${bench.id}/runs`, { run_id: run, note: 'made by a job' });
    await api(request, 'post', `/entities/${bench.id}/chosen`, { run_id: run, candidate: concept, note: 'the clean one' });
    await api(request, 'post', `/entities/${mechanic.id}/runs`, { run_id: run });
    await api(request, 'post', `/entities/${mechanic.id}/chosen`, { run_id: run, candidate: tidy });
    // A choice whose file is not there, and a change after the choice.
    await api(request, 'post', `/entities/${bench.id}/chosen`, { run_id: run, candidate: 'attempts/a1/gone/final.png', slot: 'icon' });
    await api(request, 'put', `/entities/${bench.id}`, {
      revision: 1,
      data: { name: 'Workshop bench', brief: 'The heavy bench where machines are opened up and mended.', tags: ['workshop'], material: 'oak top, steel legs', size: 'large' },
      note: 'steel legs',
    });

    // The only project, so the app opens it without being told.
    await page.goto(`/world/prop/${bench.id}`);

    await test.step('hero: the chosen image, and how the entity has moved on since', async () => {
      const profile = page.locator('[data-page="profile"]');
      await expect(profile.locator('h1')).toHaveText('Workshop bench');
      await expect(page.getByTestId('hero-image')).toBeVisible();
      await expect.poll(() => imageLoaded(page, '[data-testid="hero-image"]')).toBe(true);
      await expect(page.getByTestId('status-line')).toContainText('Chosen from run');
      await expect(page.getByTestId('status-line')).toContainText('final.png, at revision 1');
      await expect(page.getByTestId('status-line')).toContainText('now at revision 2');
      await expect(page.getByTestId('stale-line')).toContainText('Material');
      await shot(page, 'profile-01-desktop');
    });

    await test.step('candidates: verdict badges, and a 3D file as a link', async () => {
      const strip = page.getByTestId('candidate-strip');
      await expect(strip.locator('[data-candidate]')).toHaveCount(3);
      await expect(strip.locator('[data-verdict="pass"]')).toHaveCount(1);
      await expect(strip.locator('[data-verdict="review"]')).toHaveCount(1);
      await expect(strip.locator('[data-verdict="fail"]')).toHaveCount(1);
      await page.locator('[data-slot="mesh"]').click();
      await expect(page.getByTestId('nothing-chosen')).toBeVisible();
      await expect(strip.locator('[data-candidate]')).toHaveCount(1);
      await strip.locator('[data-candidate]').click();
      await expect(page.getByTestId('hero-file')).toHaveAttribute('href', new RegExp(`/runs/${run}/files/attempts/a1/mesh/mesh.glb$`));
      await expect(page.getByTestId('preview-banner')).toContainText('mesh.glb');
      await shot(page, 'profile-02-3d-preview');
      await page.locator('[data-slot="main"]').click();
      await expect(page.getByTestId('preview-banner')).toHaveCount(0);
    });

    await test.step('a choice whose file is gone says so', async () => {
      await page.locator('[data-slot="icon"]').click();
      await expect(page.getByTestId('file-missing')).toBeVisible();
      await page.locator('[data-slot="main"]').click();
    });

    await test.step('use another candidate, then go back to the first', async () => {
      const before = await page.getByTestId('hero-image').getAttribute('src');
      await page.locator('[data-candidate$="tidy/final.png"]').click();
      await expect(page.getByTestId('preview-banner')).toContainText('Previewing final.png');
      await expect(page.getByTestId('hero-image')).not.toHaveAttribute('src', before!);
      await expect.poll(() => imageLoaded(page, '[data-testid="hero-image"]')).toBe(true);
      await shot(page, 'profile-03-preview');
      await page.locator('[data-action="use-this"]').click();
      await expect(page.getByTestId('preview-banner')).toHaveCount(0);
      await expect(page.getByTestId('status-line')).toContainText('at revision 2');
      await expect(page.locator('[data-candidate$="tidy/final.png"]')).toHaveClass(/is-current/);
      await expect(page.locator('[data-candidate$="concept/final.png"]')).not.toHaveClass(/is-current/);
      await expect(page.getByTestId('stale-line')).toHaveCount(0);

      await page.locator('[data-candidate$="concept/final.png"]').click();
      await page.locator('[data-action="use-this"]').click();
      await expect(page.locator('[data-candidate$="concept/final.png"]')).toHaveClass(/is-current/);
      await expect.poll(() => imageLoaded(page, '[data-testid="hero-image"]')).toBe(true);
    });

    await test.step('fields: edited in place, one at a time, each a revision', async () => {
      await page.locator('[data-edit="/data/condition"]').click();
      await page.locator('form[data-editing="/data/condition"] input[type="text"]').first().fill('worn, oil-stained');
      await page.locator('form[data-editing="/data/condition"] input.note').fill('more lived-in');
      await page.keyboard.press('Enter');
      await expect(page.locator('[data-row="/data/condition"]')).toContainText('worn, oil-stained');
      await expect(page.locator('[data-event="change"]').first()).toContainText('Revision 3 saved');
      await expect(page.locator('[data-event="change"]').first()).toContainText('Condition: empty → worn, oil-stained');
      await expect(page.locator('[data-event="change"]').first()).toContainText('more lived-in');

      // A field error stays on the field and keeps the editor open.
      await page.locator('[data-edit="/data/name"]').click();
      await page.locator('form[data-editing="/data/name"] input').first().fill('');
      await page.keyboard.press('Enter');
      await expect(page.locator('form[data-editing="/data/name"] .field-error')).toBeVisible();
      await page.keyboard.press('Escape');
      await expect(page.locator('[data-page="profile"] h1')).toHaveText('Workshop bench');

      // The enum and the tags.
      await page.locator('[data-edit="/data/size"]').click();
      await page.locator('form[data-editing="/data/size"] select').selectOption('huge');
      await page.getByRole('button', { name: 'Save' }).click();
      await expect(page.locator('[data-row="/data/size"]')).toContainText('huge');
      await page.locator('[data-edit="/data/tags"]').click();
      await page.locator('form[data-editing="/data/tags"] input').first().fill('workshop, harbour');
      await page.getByRole('button', { name: 'Save' }).click();
      await expect(page.locator('[data-row="/data/tags"]')).toContainText('harbour');
      await expect(page.locator('[data-event="change"]').first()).toContainText('Revision 5 saved');
    });

    await test.step('conflict: a change made behind the page is never overwritten', async () => {
      const latest = await api<{ revision: number; data: Record<string, unknown> }>(request, 'get', `/entities/${bench.id}`);
      await api(request, 'put', `/entities/${bench.id}`, { revision: latest.revision, data: { ...latest.data, condition: 'rusted' }, note: 'someone else' });
      await page.locator('[data-edit="/data/material"]').click();
      await page.locator('form[data-editing="/data/material"] input[type="text"]').first().fill('plain oak');
      await page.keyboard.press('Enter');
      await expect(page.locator('[data-banner="conflict"]')).toContainText('revision 6');
      await shot(page, 'profile-04-conflict');
      await page.getByRole('button', { name: 'Reload the latest' }).click();
      await expect(page.locator('[data-banner="conflict"]')).toHaveCount(0);
      await expect(page.locator('[data-row="/data/condition"]')).toContainText('rusted');
      await expect(page.locator('[data-row="/data/material"]')).toContainText('oak top, steel legs');
    });

    await test.step('history: filters; related: the linked character with its image', async () => {
      await page.locator('[data-filter="run"]').click();
      await expect(page.locator('[data-event="change"]')).toHaveCount(0);
      await expect(page.locator('[data-event="run"]')).toHaveCount(1);
      await expect(page.locator('[data-event="choice"]').first()).toContainText('as image');
      // A choice's thumbnail is the image itself; one whose file is gone says so instead of a broken icon.
      const thumbs = page.locator('[data-event="choice"] img');
      await expect(thumbs.first()).toBeVisible();
      for (const img of await thumbs.all()) {
        await expect.poll(() => img.evaluate((el: HTMLImageElement) => el.complete && el.naturalWidth > 0)).toBe(true);
      }
      await expect(page.getByTestId('thumb-missing')).toHaveCount(1);
      await page.locator('[data-filter="change"]').click();
      await expect(page.locator('[data-event="choice"]')).toHaveCount(0);
      await expect(page.locator('[data-event="change"]').first()).toContainText('Revision 6 saved');
      await page.locator('[data-filter="all"]').click();
      const related = page.locator(`[data-related="${mechanic.id}"]`);
      await expect(related).toContainText('Mechanic');
      await expect(related).toContainText('belongs to');
      await expect.poll(() => related.locator('img').evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0)).toBe(true);
      await shot(page, 'profile-05-history-related');
    });

    await test.step('notes: a mention, a pasted image, newlines, a pin, a filter, edit and delete', async () => {
      const revisionBefore = (await api<{ revision: number }>(request, 'get', `/entities/${bench.id}`)).revision;
      const composer = page.getByTestId('composer');
      await expect(composer).toBeVisible();
      await expect(composer).toHaveAttribute('placeholder', 'Add a note…');

      // The @ picker offers the project's other entities and Enter picks one instead of posting.
      await composer.click();
      await composer.pressSequentially('Lower the bench, ask @Mech');
      await expect(page.getByTestId('mention-menu')).toContainText('Mechanic');
      await expect(page.getByTestId('mention-menu')).not.toContainText('Workshop bench');
      await page.keyboard.press('Enter');
      await expect(page.getByTestId('mention-menu')).toHaveCount(0);
      await expect(composer).toHaveValue('Lower the bench, ask @Mechanic ');
      await composer.pressSequentially('about it');

      // Paste an image from the clipboard (the chosen image stands in for a screenshot).
      const shotBytes = (await (await request.get(`${API}/entities/${bench.id}/chosen/main/file`)).body()).toString('base64');
      await composer.evaluate((el, b64) => {
        const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
        const clipboardData = new DataTransfer();
        clipboardData.items.add(new File([bytes], 'screenshot.png', { type: 'image/png' }));
        el.dispatchEvent(new ClipboardEvent('paste', { clipboardData, bubbles: true, cancelable: true }));
      }, shotBytes);
      await expect(page.getByTestId('composer-drafts').locator('img')).toHaveCount(1);
      await shot(page, 'notes-01-composer');
      await page.keyboard.press('Enter');
      const first = page.locator('[data-event="note"]').first();
      await expect(first).toContainText('Lower the bench, ask @Mechanic about it');
      await expect(first.locator('a[data-mention]')).toHaveAttribute('href', `/world/character/${mechanic.id}`);
      await expect.poll(() => first.getByTestId('note-image').evaluate((el: HTMLImageElement) => el.complete && el.naturalWidth > 0)).toBe(true);
      await expect(composer).toHaveValue('');
      await expect(page.getByTestId('composer-drafts')).toHaveCount(0);

      // Shift+Enter is a new line; Enter posts.
      await composer.click();
      await composer.pressSequentially('line one');
      await page.keyboard.press('Shift+Enter');
      await composer.pressSequentially('line two');
      await expect(composer).toHaveValue('line one\nline two');
      await page.keyboard.press('Enter');
      await expect(page.locator('[data-event="note"]').first()).toContainText('line one');
      await expect(page.locator('[data-event="note"]')).toHaveCount(2);

      // A note never makes a revision.
      expect((await api<{ revision: number }>(request, 'get', `/entities/${bench.id}`)).revision).toBe(revisionBefore);

      // Pin the older note: it appears under the identity block, and unpinning removes it.
      const older = page.locator('[data-event="note"]').nth(1);
      await older.locator('[data-action="note-menu"]').click();
      await page.getByRole('menuitem', { name: 'Pin', exact: true }).click();
      const pinned = page.locator('[data-panel="pinned"]');
      await expect(pinned).toContainText('Lower the bench');
      await expect(pinned.getByTestId('note-image')).toBeVisible();
      await shot(page, 'notes-02-pinned');

      // Reload: the notes are still there.
      await page.reload();
      await expect(page.locator('[data-event="note"]')).toHaveCount(2);
      await expect(page.locator('[data-panel="pinned"]')).toContainText('Lower the bench');

      // The Notes filter.
      await page.locator('[data-filter="note"]').click();
      await expect(page.locator('[data-event="note"]')).toHaveCount(2);
      await expect(page.locator('[data-event="change"], [data-event="run"], [data-event="choice"]')).toHaveCount(0);
      await shot(page, 'notes-03-filter');
      await page.locator('[data-filter="all"]').click();
      await expect(page.locator('[data-event="change"]').first()).toBeVisible();

      // Edit the newest note, then delete it.
      const newest = page.locator('[data-event="note"]').first();
      await newest.locator('[data-action="note-menu"]').click();
      await page.getByRole('menuitem', { name: 'Edit' }).click();
      await newest.locator('textarea').fill('line one, edited');
      await page.keyboard.press('Enter');
      await expect(page.locator('[data-event="note"]').first()).toContainText('line one, edited');
      await page.locator('[data-event="note"]').first().locator('[data-action="note-menu"]').click();
      await page.getByRole('menuitem', { name: 'Delete' }).click();
      await page.getByRole('button', { name: 'Delete' }).click();
      await expect(page.locator('[data-event="note"]')).toHaveCount(1);

      // Unpin the other one, then pin it again for the phone-width check.
      await page.locator('[data-event="note"]').first().locator('[data-action="note-menu"]').click();
      await page.getByRole('menuitem', { name: 'Unpin' }).click();
      await expect(page.locator('[data-panel="pinned"]')).toHaveCount(0);
      await page.locator('[data-event="note"]').first().locator('[data-action="note-menu"]').click();
      await page.getByRole('menuitem', { name: 'Pin', exact: true }).click();
      await expect(page.locator('[data-panel="pinned"]')).toBeVisible();

      expect((await api<{ revision: number }>(request, 'get', `/entities/${bench.id}`)).revision).toBe(revisionBefore);
    });

    await test.step('the form is one click away, and links lead to the other profile', async () => {
      await page.locator('[data-action="edit-all"]').click();
      await expect(page).toHaveURL(new RegExp(`/world/prop/${bench.id}/edit$`));
      await page.locator('[data-action="to-profile"]').click();
      await expect(page).toHaveURL(new RegExp(`/world/prop/${bench.id}$`));
      await page.locator(`[data-related="${mechanic.id}"]`).click();
      await expect(page).toHaveURL(new RegExp(`/world/character/${mechanic.id}$`));
      await expect(page.locator('[data-page="profile"] h1')).toHaveText('Mechanic');
      await expect.poll(() => imageLoaded(page, '[data-testid="hero-image"]')).toBe(true);
      await expect(page.getByTestId('stale-line')).toHaveCount(0);
    });

    await test.step('phone width: no sideways scrolling', async () => {
      await page.setViewportSize({ width: 390, height: 844 });
      await page.goto(`/world/prop/${bench.id}`);
      await expect(page.getByTestId('hero-image')).toBeVisible();
      await expect(page.getByTestId('candidate-strip')).toBeVisible();
      await expect(page.getByTestId('composer')).toBeVisible();
      await expect(page.getByTestId('note-image').first()).toBeVisible();
      expect(await sidewaysScrollers(page)).toEqual([]);
      await shot(page, 'profile-06-phone', 2600);
      await page.setViewportSize({ width: 1280, height: 900 });
    });

    expect(problems).toEqual([]);
  } finally {
    await request.delete('/api/v1/projects/profile-demo', { headers: WRITE });
  }
});
