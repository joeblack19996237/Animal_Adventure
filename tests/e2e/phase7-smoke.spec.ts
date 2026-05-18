import { test, expect } from '@playwright/test';

const PLAYERS_API = '**/api/v1/players';

test.describe('@phase7-smoke', () => {
  test('login_name_only: UI shows name input only', async ({ page }) => {
    await page.goto('/');

    const overlay = page.locator('#login-overlay');
    await expect(overlay).toBeVisible({ timeout: 10000 });

    const nameInput = overlay.locator('input[type="text"]');
    await expect(nameInput).toBeVisible();
    await expect(nameInput).toHaveAttribute('placeholder', 'Enter your name');

    const playBtn = overlay.locator('button', { hasText: 'Play' });
    await expect(playBtn).toBeVisible();

    await expect(overlay.locator('input[type="password"]')).toHaveCount(0);
    await expect(overlay.locator('input[type="email"]')).toHaveCount(0);

    await expect(overlay.locator('button[data-character-id]').first()).not.toBeVisible();
  });

  test('login_new_player_character_select: new player selects MVP character', async ({ page }) => {
    await page.route(PLAYERS_API, async (route, request) => {
      const body = JSON.parse(request.postData() ?? '{}') as Record<string, unknown>;
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
            player_id: 'new-test-player-id',
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

    await overlay.locator('input[type="text"]').fill('NewPlayer');
    await overlay.locator('button', { hasText: 'Play' }).click();

    const charButtons = overlay.locator('button[data-character-id]');
    await expect(charButtons.first()).toBeVisible({ timeout: 5000 });
    await expect(charButtons).toHaveCount(3);

    await expect(overlay.locator('input[type="text"]')).not.toBeVisible();
    await expect(overlay.locator('button', { hasText: 'Play' })).not.toBeVisible();

    await overlay.locator('button[data-character-id="penguin"]').click();

    await expect(page.locator('#login-overlay')).toHaveCount(0, { timeout: 5000 });
  });

  test('login_returning_player_skips_character_select: returning player bypasses character selection', async ({
    page,
  }) => {
    await page.route(PLAYERS_API, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          player_id: 'existing-player-id',
          name: 'ReturnPlayer',
          normalized_name: 'returnplayer',
          character_id: 'arctic_fox',
        }),
      });
    });

    await page.goto('/');

    const overlay = page.locator('#login-overlay');
    await expect(overlay).toBeVisible({ timeout: 10000 });

    await expect(overlay.locator('button[data-character-id]').first()).not.toBeVisible();

    await overlay.locator('input[type="text"]').fill('RETURNPLAYER');
    await overlay.locator('button', { hasText: 'Play' }).click();

    await expect(page.locator('#login-overlay')).toHaveCount(0, { timeout: 5000 });
  });
});
