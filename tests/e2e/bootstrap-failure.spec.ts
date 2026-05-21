import { test, expect, type Page } from '@playwright/test';

/**
 * Tests for issue 16.2: Frontend silently ignores bootstrap failure.
 *
 * These tests fail against the current code because GameScene.loadBootstrapAsync()
 * at src/scenes/GameScene.ts:221 silently returns on failure instead of showing
 * a blocking overlay. They pass once a blocking error overlay is rendered.
 */

const BOOTSTRAP_API = '**/api/v1/config/bootstrap';
const PLAYERS_API = '**/api/v1/players';
const WS_GLOB = '**/ws/**';
const PLAYER_NAME = 'BootstrapFailTestPlayer';
const PLAYER_ID = 'bootstrap-fail-test-player';

const MOCK_PLAYER = {
  player_id: PLAYER_ID,
  name: PLAYER_NAME,
  normalized_name: 'bootstrapfailtestplayer',
  character_id: 'penguin',
};

async function mockPlayersApi(page: Page): Promise<void> {
  await page.route(PLAYERS_API, (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(MOCK_PLAYER),
    });
  });
}

async function mockWebSocket(page: Page): Promise<void> {
  await page.routeWebSocket(WS_GLOB, (ws) => {
    ws.send(
      JSON.stringify({
        type: 'state_sync',
        server_time: new Date().toISOString(),
        player: {
          id: PLAYER_ID,
          name: PLAYER_NAME,
          x: 160,
          y: 160,
          direction: 'down',
          coins: 0,
          level: 1,
        },
        progress: {},
        inventory: [],
        equipment: [],
        quests: [],
        online_players: {},
        world_items: [],
      }),
    );
  });
}

async function countWebSocketAttempts(page: Page): Promise<() => number> {
  let attempts = 0;
  await page.routeWebSocket(WS_GLOB, (ws) => {
    attempts++;
    ws.send(
      JSON.stringify({
        type: 'state_sync',
        server_time: new Date().toISOString(),
        player: {
          id: PLAYER_ID,
          name: PLAYER_NAME,
          x: 160,
          y: 160,
          direction: 'down',
          coins: 0,
          level: 1,
        },
        progress: {},
        inventory: [],
        equipment: [],
        quests: [],
        online_players: {},
        world_items: [],
      }),
    );
  });
  return () => attempts;
}

async function completeLogin(page: Page): Promise<void> {
  await page.getByPlaceholder('Enter your name').fill(PLAYER_NAME);
  await page.getByRole('button', { name: 'Play' }).click();
  await expect(page.locator('#login-overlay')).toBeHidden({ timeout: 5000 });
}

test('bootstrap failure shows a blocking overlay element', async ({ page }) => {
  await mockPlayersApi(page);
  const webSocketAttempts = await countWebSocketAttempts(page);

  await page.route(BOOTSTRAP_API, (route) => {
    route.fulfill({ status: 500, body: 'Internal Server Error' });
  });

  await page.goto('/');
  await completeLogin(page);

  const overlay = page.locator('#bootstrap-error');
  await expect(overlay, 'A blocking error overlay must be visible when bootstrap fails').toBeVisible({
    timeout: 10000,
  });
  await expect(overlay).toContainText('Configuration failed to load');
  await expect(overlay).toContainText('Bootstrap config unavailable');
  await expect(overlay.getByRole('button', { name: 'Retry' })).toBeVisible();
  expect(webSocketAttempts(), 'Gameplay WebSocket must not open until bootstrap succeeds').toBe(0);
});

test('bootstrap failure prevents shop button from being interactive', async ({ page }) => {
  await mockPlayersApi(page);
  await mockWebSocket(page);

  await page.route(BOOTSTRAP_API, (route) => {
    route.fulfill({ status: 500, body: 'Internal Server Error' });
  });

  await page.goto('/');
  await completeLogin(page);

  await expect(page.locator('#bootstrap-error')).toBeVisible({ timeout: 10000 });
  await page.locator('#hud-shop').click({ timeout: 1000 }).catch(() => undefined);
  await expect(page.locator('#shop-panel')).toBeHidden();
});
