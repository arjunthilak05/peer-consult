import { defineConfig } from '@playwright/test';

// Python interpreter with peer-consult installed (e.g. `pip install -e .[dev]` from the repo root).
const PY = process.env.PEER_CONSULT_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');

export default defineConfig({
  testDir: './e2e',
  timeout: 120_000,
  use: {
    baseURL: 'http://127.0.0.1:4199',
    // Set PLAYWRIGHT_CHANNEL=msedge (or chrome) to use an installed browser instead of
    // the bundled Chromium from `npx playwright install chromium`.
    channel: process.env.PLAYWRIGHT_CHANNEL || undefined,
    viewport: { width: 1600, height: 1000 },
  },
  webServer: {
    command: `"${PY}" ../tests/e2e_office_server.py 4199 e2e-office-token-0123456789`,
    url: 'http://127.0.0.1:4199/api/health',
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
