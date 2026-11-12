import * as fs from 'fs';
import * as path from 'path';
import { fileURLToPath } from 'url';
import { expect, test } from '@playwright/test';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const TOKEN = 'e2e-office-token-0123456789';
// Set UPDATE_DOCS_SCREENSHOTS=1 to refresh the README screenshots in docs/screenshots from this run.
const SHOTS = process.env.UPDATE_DOCS_SCREENSHOTS ? '../docs/screenshots' : 'test-results/screenshots';

test('unauthenticated API access is rejected', async ({ request }) => {
  const r = await request.get('/api/state');
  expect(r.status()).toBe(401);
});

test('full council workflow driven from the Pixel Office UI', async ({ page, request }) => {
  await page.goto(`/?token=${TOKEN}`);
  await expect(page.getByTestId('ws-status')).toHaveText(/live/, { timeout: 15_000 });
  await expect(page.getByTestId('pixel-office-canvas')).toBeVisible();
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${SHOTS}/01-office-idle.png` });

  // Start a real (fake-provider) plan run through the authenticated REST API used by the UI form.
  const health = await request.get('/api/health');
  expect(health.ok()).toBeTruthy();
  const repoPath = await page.evaluate(async (tok) => {
    const r = await fetch('/api/runs', { headers: { Authorization: `Bearer ${tok}` } });
    return r.ok;
  }, TOKEN);
  expect(repoPath).toBeTruthy();

  await page.getByTestId('question-input').fill('Make compute() in app.py return 42');
  await page.getByLabel('Workflow', { exact: true }).selectOption('plan');
  const marker = path.resolve(__dirname, '../../tests/.e2e_repo_path');
  const cwd = process.env.E2E_REPO || (fs.existsSync(marker) ? fs.readFileSync(marker, 'utf8').trim() : '');
  if (cwd) await page.getByPlaceholder('repository path (optional)').fill(cwd);
  await page.getByTestId('start-run-btn').click();

  await expect(page.getByTestId('run-state')).toHaveAttribute('data-state', 'AWAITING_APPROVAL', { timeout: 60_000 });
  await page.waitForTimeout(1500); // let characters walk to the meeting room
  await page.screenshot({ path: `${SHOTS}/02-meeting-awaiting-approval.png` });

  // Meeting drawer: proposals, critiques, consensus, disagreements
  await page.getByTestId('area-meeting_room').click();
  await expect(page.getByTestId('meeting-drawer')).toBeVisible();
  await page.getByTestId('tab-disagreements').click();
  await expect(page.getByTestId('disagreements')).toContainText('Caching');
  await page.screenshot({ path: `${SHOTS}/03-meeting-disagreements.png` });
  await page.getByTestId('area-review_room').click();
  await expect(page.getByTestId('doubts-panel')).toContainText('Caching');
  await page.getByTestId('area-desks').click();
  await expect(page.getByTestId('research-panel')).toContainText('confidence');

  // Character inspector
  await page.getByTestId('select-agent-codex').click();
  await expect(page.getByTestId('inspector-codex')).toContainText('gpt-6-astra');
  await page.screenshot({ path: `${SHOTS}/04-agent-inspector.png` });

  // Approval: dialog must wait for backend confirmation
  await page.getByTestId('open-approval').click();
  await expect(page.getByTestId('approval-dialog')).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/05-approval-dialog.png` });
  await page.getByTestId('approve-btn').click();
  await expect(page.getByTestId('approval-dialog')).toBeHidden({ timeout: 30_000 });

  await expect(page.getByTestId('run-state')).toHaveAttribute('data-state', 'COMPLETED', { timeout: 90_000 });
  await page.getByTestId('area-coding_room').click();
  await expect(page.getByTestId('test-status')).toHaveText('PASSED');
  await expect(page.getByTestId('git-diff')).toContainText('return 42');
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${SHOTS}/06-execution-completed.png` });

  // Event replay (client-side only)
  await page.getByTestId('replay-btn').click();
  await expect(page.getByText(/Exit replay/)).toBeVisible({ timeout: 10_000 });
  await page.waitForTimeout(2500);
  await page.screenshot({ path: `${SHOTS}/07-event-replay.png` });
});
