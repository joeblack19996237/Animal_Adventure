import { test, expect } from '@playwright/test';

const CORE_ASSET_PATHS = [
  '/assets/images/MapTiles/map_tile_0_0.png',
  '/assets/images/NPC/NPC_1_Hopper.png',
  '/assets/images/NPC/NPC_A_Copper.png',
  '/config/map_tiles.json',
  '/config/assets.json',
];

test.describe('@phase5-smoke', () => {
  test('app boots without critical page errors', async ({ page }) => {
    const pageErrors: string[] = [];
    const consoleErrors: string[] = [];

    page.on('pageerror', (err) => pageErrors.push(err.message));
    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        consoleErrors.push(msg.text());
      }
    });

    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    expect(pageErrors, `Page errors: ${pageErrors.join('; ')}`).toHaveLength(0);
    expect(consoleErrors, `Console errors: ${consoleErrors.join('; ')}`).toHaveLength(0);
  });

  test('canvas is present and nonblank after Phaser boot', async ({ page }) => {
    await page.goto('/');

    const canvas = page.locator('#game-container canvas');
    await expect(canvas).toBeVisible({ timeout: 10000 });

    const box = await canvas.boundingBox();
    expect(box, 'canvas bounding box must not be null').not.toBeNull();
    if (!box) throw new Error('canvas bounding box is null');
    expect(box.width, 'canvas width must be non-zero').toBeGreaterThan(0);
    expect(box.height, 'canvas height must be non-zero').toBeGreaterThan(0);
  });

  test('core assets do not 404', async ({ request }) => {
    for (const assetPath of CORE_ASSET_PATHS) {
      const response = await request.get(assetPath);
      expect(
        response.status(),
        `Asset ${assetPath} returned ${response.status()}`,
      ).not.toBe(404);
    }
  });
});
