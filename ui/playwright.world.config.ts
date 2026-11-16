import { defineConfig, devices } from '@playwright/test';

/**
 * The world-model end-to-end test. Unlike the default config, this one starts its own servers on
 * ports of its own (a throwaway API server on 4311 with a temporary data folder, and the dev
 * server on 4310 proxying to it), so it never touches a server that is already running. Run it
 * with `npm run e2e:world`. Set WORLD_SCREENSHOT_DIR to also save a screenshot of each screen.
 */
export default defineConfig({
  testDir: './e2e-world',
  fullyParallel: false,
  retries: 0,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: 'http://127.0.0.1:4310',
    trace: 'retain-on-failure',
    viewport: { width: 1280, height: 900 },
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: 'node e2e-world/start-api.mjs',
      url: 'http://127.0.0.1:4311/api/v1/projects',
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: 'npx ng serve --host 127.0.0.1 --port 4310 --proxy-config e2e-world/proxy.conf.json',
      url: 'http://127.0.0.1:4310',
      reuseExistingServer: false,
      timeout: 180_000,
      env: { NG_CLI_ANALYTICS: 'false' },
    },
  ],
});
