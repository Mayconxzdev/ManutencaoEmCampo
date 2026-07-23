import { defineConfig, devices } from '@playwright/test';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const projectRoot = path.resolve(__dirname, '..');
const python = process.env.MEC_E2E_PYTHON
  || (process.platform === 'win32'
    ? path.join(projectRoot, '.venv', 'Scripts', 'python.exe')
    : path.join(projectRoot, '.venv', 'bin', 'python'));
const baseURL = process.env.MEC_E2E_BASE_URL || 'http://127.0.0.1:8124';

/**
 * The public portfolio always starts an isolated server whose database is
 * generated from synthetic data. It never connects to an installed service,
 * a network share or a company database.
 */
export default defineConfig({
  testDir: './tests',
  timeout: 30_000,
  expect: { timeout: 8_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list'], ['html', { outputFolder: path.join(projectRoot, 'output', 'playwright-report'), open: 'never' }]],
  outputDir: path.join(projectRoot, 'output', 'playwright-artifacts'),
  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
  },
  webServer: process.env.MEC_E2E_BASE_URL ? undefined : {
    command: `"${python}" "${path.join(projectRoot, 'scripts', 'e2e_server.py')}"`,
    url: 'http://127.0.0.1:8124/health',
    timeout: 60_000,
    reuseExistingServer: false,
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } },
    { name: 'tablet', use: { browserName: 'chromium', viewport: { width: 820, height: 1180 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 } },
    { name: 'mobile', use: { browserName: 'chromium', viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 3 } },
  ],
});
