// Re-make the README screenshots from a running install.
//
//   node docs/img/capture.mjs http://127.0.0.1:4280
//
// Start from a fresh install with the example loaded (`python3 scripts/load_example.py <address>`), then, through the
// Generate panel or the API, run the `prop` pipeline on "Driftwood Fiddle", "Brass Signal Lantern" and "Tide Table Notebook" and the
// `character` pipeline on "Ines Marlow" (stand-in generators, seed 7), and choose each run's image and 3D model.
// The hero shots (viewer, trace, gate, generate) show the fiddle. The Generate shot starts one more prop run, so it comes last; Statistics is taken before it.
//
// Needs Playwright's Chromium (`cd ui && npx playwright install chromium`). Images are written next to this file:
// 1440 CSS px wide at device scale 2. Each shot is cropped to the part of the screen worth showing.
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const { chromium } = createRequire(join(here, '../../ui/package.json'))('playwright');
const base = (process.argv[2] ?? 'http://127.0.0.1:4280').replace(/\/$/, '');
const out = (name) => join(here, name);

const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 });
const page = await context.newPage();
page.on('pageerror', (e) => console.error('page error:', e.message));

/** Tall enough that nothing scrolls; each shot then clips what it wants. */
const resize = (height = 2400) => page.setViewportSize({ width: 1440, height });
/** No spinner or progress bar on the page, the network quiet, and a beat for the canvas to draw. */
async function settled(extra = 600) {
  await page.waitForLoadState('networkidle');
  await page.locator('mat-spinner, mat-progress-spinner, mat-progress-bar, [role=progressbar]').first()
    .waitFor({ state: 'detached', timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(extra);
}
async function open(path, name) {
  await page.goto(base + path);
  await page.getByText(name).first().click();
  await page.getByText('Related').first().waitFor();
  await settled();
}
async function shot(name, clip) {
  await page.mouse.move(0, 0);
  await page.screenshot({ path: out(name), clip });
  console.log('wrote', name);
}
async function showModel() {
  await page.getByText('3D', { exact: true }).first().click();
  await page.getByText(/triangles/).first().waitFor();
  await settled(2500); // the viewer draws after the file loads
}
const top = async (locator) => (await locator.first().boundingBox()).y;
const bottom = async (locator) => { const b = await locator.first().boundingBox(); return b.y + b.height; };

// records.png: the list of props
await resize(560);
await page.goto(base + '/world/prop');
await page.getByText('Brass Signal Lantern').first().waitFor();
await settled();
await shot('records.png');

// viewer.png: the 3D tab with the chosen model, the title and the fields beside it
await resize();
await open('/world/prop', 'Driftwood Fiddle');
await showModel();
await shot('viewer.png', { x: 0, y: 0, width: 1440, height: 760 });

// profile.png: fields, history of runs and choices, Feeds this, Related
await page.getByText('Image', { exact: true }).first().click();
await settled();
await page.getByRole('button', { name: 'Runs and choices' }).click();
await settled();
await page.evaluate(() => { document.body.style.zoom = '0.88'; }); // so Related fits in 1100 px
await page.waitForTimeout(500);
await shot('profile.png', { x: 0, y: 92, width: 1260, height: 1100 });
await page.evaluate(() => { document.body.style.zoom = ''; });

// character.png: the rigged character in the clip player, the walk clip part-way through
await open('/world/character', 'Ines Marlow');
await showModel();
await page.getByTestId('clip-select').selectOption({ label: /walk/ }).catch(async () => {
  const walk = await page.getByTestId('clip-select').locator('option', { hasText: 'walk' }).first().getAttribute('value');
  await page.getByTestId('clip-select').selectOption(walk);
});
await page.waitForTimeout(500);
const scrub = page.getByTestId('clip-scrub');
const length = Number(await scrub.getAttribute('max'));
await scrub.fill(String((length * 0.3).toFixed(2)));
await settled(1200);
await shot('character.png', { x: 0, y: 0, width: 1440, height: 840 });

// trace.png: the stage strip, then the Concept image stage: outputs, prompt and the colour legend
await open('/world/prop', 'Driftwood Fiddle');
await page.getByText('See how it was made').first().click();
await page.getByText('Shape gate').first().waitFor();
await settled();
await page.getByText('Concept image').first().click();
await page.getByText('Prompt', { exact: true }).first().waitFor();
await settled();
const legendEnd = await bottom(page.getByText(/Point at or tap a piece/));
await shot('trace.png', { x: 0, y: 0, width: 1440, height: Math.ceil(legendEnd + 6) });

// gate.png: the Shape gate stage, its measures with value, limit and margin
await page.getByText('Shape gate').first().click();
await page.getByText('Measure', { exact: true }).waitFor();
await settled();
const gateTop = await top(page.getByRole('heading', { name: 'Gate', exact: true }).or(page.getByText('Gate', { exact: true })));
await shot('gate.png', { x: 240, y: Math.max(0, Math.floor(gateTop - 10)), width: 1200, height: 800 });

// statistics.png
await page.goto(base + '/statistics');
await page.getByText('Time per stage').waitFor();
await settled(1000);
await shot('statistics.png', { x: 0, y: 0, width: 1440, height: 1180 });

// generate.png: start a prop run and wait until it is done, the stages listed with their state
await open('/world/prop', 'Driftwood Fiddle');
await page.getByRole('button', { name: 'Generate again' }).click();
await page.getByRole('button', { name: 'Start' }).click();
await page.getByText(/^Done\./).waitFor({ timeout: 120000 });
await settled();
const genTop = await top(page.getByRole('heading', { name: 'Generate' }));
await shot('generate.png', { x: 240, y: Math.floor(genTop - 24), width: 520, height: 760 });

await browser.close();
