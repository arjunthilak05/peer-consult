import { expect, test } from '@playwright/test';

test('top-bar models save without running agents and support keyboard dismissal', async ({ page, request }) => {
  const token = 'e2e-office-token-0123456789';
  const before = await (await request.get('/api/runs', { headers: { Authorization: `Bearer ${token}` } })).json();
  await page.goto(`/?token=${token}`);
  await expect(page.getByTestId('ws-status')).toHaveText(/live/);
  await page.getByTestId('open-models').click();
  await expect(page.getByText('Choose the models', { exact: true })).toBeVisible();
  await page.locator('#model-claude').selectOption('claude-opus-5-5');
  await page.locator('#model-agy').selectOption('gemini-3.8-flash');
  await page.getByRole('button', { name: 'Apply models', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('Models saved');
  const after = await (await request.get('/api/runs', { headers: { Authorization: `Bearer ${token}` } })).json();
  expect(after.runs.length).toBe(before.runs.length);
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('open-models')).toBeFocused();
  await page.getByTestId('open-models').click();
  await expect(page.locator('#model-claude')).toHaveValue('claude-opus-5-5');
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await expect(page.getByRole('button', { name: 'Apply models', exact: true })).toBeVisible();
  await page.keyboard.press('Escape');
});
