import { expect, test } from '@playwright/test';

test('generated textures, HUD selection, opt-in audio and mobile layout', async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(() => {
    const NativeAudio = window.AudioContext;
    (window as any).__audioStats = { contexts: 0, notes: 0 };
    window.AudioContext = class extends NativeAudio {
      constructor(options?: AudioContextOptions) {
        super(options);
        (window as any).__audioStats.contexts++;
      }
      createOscillator() {
        (window as any).__audioStats.notes++;
        return super.createOscillator();
      }
    };
  });
  await page.goto('/?token=e2e-office-token-0123456789');
  await expect(page.getByTestId('agent-card-codex')).toBeVisible();
  await expect(page.getByRole('meter')).toHaveCount(3);
  expect(await page.evaluate(() => (window as any).__audioStats.contexts)).toBe(0);

  const textures = await page.evaluate(async () => {
    const files = [
      ...[0, 1, 2].map(i => [`characters/char_${i}.png`, 112, 96]),
      ['furniture/WHITEBOARD/WHITEBOARD.png', 32, 32], ['furniture/COFFEE/COFFEE.png', 16, 16],
      ...[0, 1].map(i => [`carpets/carpet_${i}.png`, 48, 48]),
      ...['idea', 'spark', 'shield', 'inspection', 'coffee', 'success', 'error'].map(i => [`emotes/${i}.png`, 16, 16]),
    ] as Array<[string, number, number]>;
    return Promise.all(files.map(async ([file, width, height]) => {
      const img = new Image(); img.src = `/assets/generated/${file}`; await img.decode();
      const canvas = document.createElement('canvas'); canvas.width = width; canvas.height = height;
      const ctx = canvas.getContext('2d')!; ctx.drawImage(img, 0, 0);
      const rgba = ctx.getImageData(0, 0, width, height).data;
      const alphas = new Set(Array.from(rgba).filter((_, i) => i % 4 === 3));
      let populatedFrames = 0;
      if (file.startsWith('characters')) {
        for (let row = 0; row < 3; row++) for (let col = 0; col < 7; col++) {
          let opaque = 0;
          for (let y = 0; y < 32; y++) for (let x = 0; x < 16; x++) {
            const a = rgba[((row * 32 + y) * width + col * 16 + x) * 4 + 3];
            if (a) opaque++;
            if ((x === 0 || x === 15 || y === 31) && a) throw Error(`${file}: frame bleeds across gutter`);
          }
          if (opaque > 30) populatedFrames++;
        }
      }
      return { file, correctSize: img.naturalWidth === width && img.naturalHeight === height,
        binaryAlpha: alphas.size === 2 && alphas.has(0) && alphas.has(255), populatedFrames };
    }));
  });
  expect(textures).toHaveLength(14);
  expect(textures.every(t => t.correctSize && t.binaryAlpha)).toBe(true);
  expect(textures.filter(t => t.file.startsWith('characters')).every(t => t.populatedFrames === 21)).toBe(true);

  await page.getByTestId('agent-card-codex').click();
  await expect(page.getByTestId('inspector-codex')).toBeFocused();
  await expect(page.getByTestId('agent-card-codex')).toHaveAttribute('aria-pressed', 'true');
  await page.getByTestId('area-desks').click();
  await expect(page.getByLabel('Research workspace', { exact: true })).toBeFocused();
  await expect(page.getByTestId('research-panel')).toBeVisible();
  for (const [room, heading] of [['meeting_room', 'Discussion'], ['review_room', 'Doubts'], ['coding_room', 'Coding']] as const) {
    await page.getByTestId(`area-${room}`).click();
    await expect(page.getByLabel(`${heading} workspace`, { exact: true })).toBeFocused();
    await expect(page.getByTestId(`area-${room}`)).toHaveAttribute('aria-pressed', 'true');
  }
  await expect(page.getByText('Your implementation workspace', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Enable retro sound effects' }).click();
  await expect(page.getByRole('button', { name: 'Mute retro sound effects' })).toHaveAttribute('aria-pressed', 'true');
  expect(await page.evaluate(() => (window as any).__audioStats.contexts)).toBe(1);
  expect(await page.evaluate(() => (window as any).__audioStats.notes)).toBeGreaterThan(0);
  await page.getByRole('button', { name: 'Mute retro sound effects' }).click();
  const notesAtMute = await page.evaluate(() => (window as any).__audioStats.notes);
  await page.getByTestId('agent-card-claude').click();
  expect(await page.evaluate(() => (window as any).__audioStats.notes)).toBe(notesAtMute);
  await page.getByTestId('inspector-claude').getByRole('button', { name: 'close', exact: true }).click();
  await page.getByTestId('area-desks').click();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: testInfo.outputPath('office-desktop.png'), fullPage: true });

  await page.emulateMedia({ reducedMotion: 'reduce' });
  expect(await page.locator('.agent-portrait > span').first().evaluate(el => getComputedStyle(el).animationName)).toBe('none');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByTestId('select-agent-agy').click();
  await expect(page.getByTestId('inspector-agy')).toBeFocused();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('office-mobile.png'), fullPage: true });
  expect(errors).toEqual([]);
});
