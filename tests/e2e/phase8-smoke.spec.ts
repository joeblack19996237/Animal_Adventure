import { test, expect } from '@playwright/test';

const PLAYERS_API = '**/api/v1/players';
const PLAYER_ID_KEY = 'animal_adventure_player_id';

const RETURNING_PLAYER = {
  player_id: 'p8smoke-return-abc123',
  name: 'SmokeEight',
  normalized_name: 'smokeeight',
  character_id: 'arctic_fox',
};

test.describe('@phase8-smoke', () => {
  test('login_creates_player: name login creates backend player and displays game scene', async ({
    page,
  }) => {
    const pageErrors: string[] = [];
    page.on('pageerror', (err) => pageErrors.push(err.message));
    page.on('console', (msg) => {
      if (msg.type() === 'error') pageErrors.push(msg.text());
    });

    await page.route(PLAYERS_API, async (route, request) => {
      let body: Record<string, unknown> = {};
      try {
        body = JSON.parse(request.postData() ?? '{}') as Record<string, unknown>;
      } catch {
        await route.fulfill({ status: 400 });
        return;
      }
      if (body['character_id'] === undefined) {
        await route.fulfill({
          status: 400,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'character_required' }),
        });
      } else {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            player_id: 'p8smoke-new-xyz789',
            name: String(body['name'] ?? ''),
            normalized_name: String(body['name'] ?? '').toLowerCase(),
            character_id: String(body['character_id']),
          }),
        });
      }
    });

    await page.goto('/');

    const overlay = page.locator('#login-overlay');
    await expect(overlay).toBeVisible({ timeout: 10000 });

    await overlay.locator('input[type="text"]').fill('SmokeEight');
    await overlay.locator('button', { hasText: 'Play' }).click();

    const charButtons = overlay.locator('button[data-character-id]');
    await expect(charButtons.first()).toBeVisible({ timeout: 5000 });
    await expect(charButtons).toHaveCount(3);

    await overlay.locator('button[data-character-id="arctic_fox"]').click();

    await expect(page.locator('#login-overlay')).toHaveCount(0, { timeout: 5000 });

    const storedId = await page.evaluate((key) => localStorage.getItem(key), PLAYER_ID_KEY);
    expect(storedId).toBe('p8smoke-new-xyz789');
  });

  test('reload_restores_session: reload preserves player_id and returning login loads same state', async ({
    page,
  }) => {
    const pageErrors: string[] = [];
    page.on('pageerror', (err) => pageErrors.push(err.message));
    page.on('console', (msg) => {
      if (msg.type() === 'error') pageErrors.push(msg.text());
    });

    await page.route(PLAYERS_API, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(RETURNING_PLAYER),
      });
    });

    await page.goto('/');

    const overlay = page.locator('#login-overlay');
    await expect(overlay).toBeVisible({ timeout: 10000 });

    await overlay.locator('input[type="text"]').fill('SmokeEight');
    await overlay.locator('button', { hasText: 'Play' }).click();

    await expect(page.locator('#login-overlay')).toHaveCount(0, { timeout: 5000 });

    const playerIdBeforeReload = await page.evaluate(
      (key) => localStorage.getItem(key),
      PLAYER_ID_KEY,
    );
    expect(playerIdBeforeReload).toBe(RETURNING_PLAYER.player_id);

    await page.reload();

    const playerIdAfterReload = await page.evaluate(
      (key) => localStorage.getItem(key),
      PLAYER_ID_KEY,
    );
    expect(playerIdAfterReload).toBe(RETURNING_PLAYER.player_id);

    const reloadOverlay = page.locator('#login-overlay');
    await expect(reloadOverlay).toBeVisible({ timeout: 10000 });

    await reloadOverlay.locator('input[type="text"]').fill('SMOKEEIGHT');
    await reloadOverlay.locator('button', { hasText: 'Play' }).click();

    await expect(page.locator('#login-overlay')).toHaveCount(0, { timeout: 5000 });

    const restoredId = await page.evaluate((key) => localStorage.getItem(key), PLAYER_ID_KEY);
    expect(restoredId).toBe(RETURNING_PLAYER.player_id);
  });
});
