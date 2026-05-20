import { test, expect, type Page } from '@playwright/test';

const PLAYERS_API = '**/api/v1/players';
const BOOTSTRAP_API = '**/api/v1/config/bootstrap';
const WS_GLOB = '**/ws/**';

const PLAYER_ID = 'p11smoke-player';

const MOCK_PLAYER = {
  player_id: PLAYER_ID,
  name: 'SmokeEleven',
  normalized_name: 'smokeeleven',
  character_id: 'penguin',
};

const MINIMAL_BOOTSTRAP = {
  map: { width: 5430, height: 7240 },
  map_tiles: { tiles: [], map_width: 5430, map_height: 7240 },
  npcs: [],
  quests: [],
  items: [],
  shop: { items: [] },
  characters: [
    {
      id: 'penguin',
      name: 'Penguin',
      scale: 1,
      anchor_x: 0.5,
      anchor_y: 0.5,
      collision_radius: 32,
      directions: {},
    },
    {
      id: 'arctic_fox',
      name: 'Arctic Fox',
      scale: 1,
      anchor_x: 0.5,
      anchor_y: 0.5,
      collision_radius: 32,
      directions: {},
    },
    {
      id: 'cat_snowman',
      name: 'Cat Snowman',
      scale: 1,
      anchor_x: 0.5,
      anchor_y: 0.5,
      collision_radius: 32,
      directions: {},
    },
  ],
  preset_phrases: [],
  progression: { levels: [] },
  assets: {},
};

const RECONNECT_TIMEOUT_MS = 10000;
const DISCONNECT_DELAY_MS = 400;

function makeStateSync(coins: number, serverTime: string): Record<string, unknown> {
  return {
    type: 'state_sync',
    server_time: serverTime,
    player: {
      id: PLAYER_ID,
      name: 'SmokeEleven',
      normalized_name: 'smokeeleven',
      character_id: 'penguin',
      x: 2715,
      y: 3620,
      direction: 'down',
      level: 0,
      coins,
    },
    progress: {
      completed_quest_count: 0,
      unique_completed_quest_ids: [],
      used_potion_count: 0,
      unlocked_level: 0,
      unlocked_regions: ['spawn'],
    },
    inventory: [],
    equipment: [],
    quests: [],
    online_players: {},
    world_items: [],
  };
}

async function setupMockRoutes(page: Page): Promise<void> {
  await page.route(PLAYERS_API, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(MOCK_PLAYER),
    });
  });

  await page.route(BOOTSTRAP_API, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(MINIMAL_BOOTSTRAP),
    });
  });
}

async function loginPlayer(page: Page): Promise<void> {
  await page.goto('/');
  const overlay = page.locator('#login-overlay');
  await expect(overlay).toBeVisible({ timeout: 10000 });
  await overlay.locator('input[type="text"]').fill('SmokeEleven');
  await overlay.locator('button', { hasText: 'Play' }).click();
  await expect(page.locator('#login-overlay')).toHaveCount(0, { timeout: 5000 });
}

async function waitForReconnect(
  reconnectEstablished: Promise<void>,
  errorMessage: string,
): Promise<void> {
  await Promise.race([
    reconnectEstablished,
    new Promise<void>((_, reject) =>
      setTimeout(() => reject(new Error(errorMessage)), RECONNECT_TIMEOUT_MS),
    ),
  ]);
}

test.describe('@phase11-smoke', () => {
  test(
    'reconnect_receives_state_sync: reconnect after forced disconnect delivers state_sync' +
      ' without console errors',
    async ({ page }) => {
      const pageErrors: string[] = [];
      page.on('pageerror', (err) => pageErrors.push(err.message));
      page.on('console', (msg) => {
        if (msg.type() === 'error') pageErrors.push(msg.text());
      });

      let connectionCount = 0;
      let resolveReconnect!: () => void;
      const reconnectEstablished = new Promise<void>((resolve) => {
        resolveReconnect = resolve;
      });

      await page.routeWebSocket(WS_GLOB, (ws) => {
        connectionCount++;
        if (connectionCount === 1) {
          ws.send(JSON.stringify(makeStateSync(25, '2026-05-18T10:00:00Z')));
          setTimeout(() => ws.close(), DISCONNECT_DELAY_MS);
        } else {
          ws.send(JSON.stringify(makeStateSync(30, '2026-05-18T10:00:05Z')));
          resolveReconnect();
        }
      });

      await setupMockRoutes(page);
      await loginPlayer(page);

      await waitForReconnect(
        reconnectEstablished,
        'Reconnect timeout: client did not reconnect within 10s',
      );

      expect(
        connectionCount,
        'client must reconnect after forced disconnect',
      ).toBeGreaterThanOrEqual(2);

      await expect(page.locator('canvas')).toBeVisible();
      await expect(page.locator('#login-overlay')).toHaveCount(0);

      expect(
        pageErrors,
        `Console errors after reconnect: ${pageErrors.join('; ')}`,
      ).toHaveLength(0);
    },
  );


  test(
    'webkit_touch_joystick_smoke: touch joystick is visible and accepts touch input' +
      ' on webkit-ipad',
    async ({ page, browserName }) => {
      test.skip(browserName !== 'webkit', 'webkit-ipad touch joystick smoke targets WebKit only');

      const pageErrors: string[] = [];
      page.on('pageerror', (err) => pageErrors.push(err.message));
      page.on('console', (msg) => {
        if (msg.type() === 'error') pageErrors.push(msg.text());
      });

      await page.routeWebSocket(WS_GLOB, (ws) => {
        ws.send(JSON.stringify(makeStateSync(25, '2026-05-18T10:00:00Z')));
      });

      await setupMockRoutes(page);
      await loginPlayer(page);

      const joystickBase = page.locator('#joystick-base');
      await expect(joystickBase).toBeVisible({ timeout: 10000 });

      const box = await joystickBase.boundingBox();
      expect(box, 'joystick bounding box must not be null').not.toBeNull();
      if (!box) throw new Error('joystick bounding box is null');
      expect(box.width, 'joystick width must be non-zero').toBeGreaterThan(0);
      expect(box.height, 'joystick height must be non-zero').toBeGreaterThan(0);

      // Dispatch synthetic touch events directly on the joystick element.
      // Avoids new Touch() which Playwright's WebKit build rejects.
      await joystickBase.dispatchEvent('touchstart', { bubbles: true, cancelable: true });
      await page.waitForTimeout(100);
      await joystickBase.dispatchEvent('touchmove', { bubbles: true, cancelable: true });
      await page.waitForTimeout(100);
      await joystickBase.dispatchEvent('touchend', { bubbles: true, cancelable: true });

      expect(
        pageErrors,
        `Console errors during touch joystick smoke: ${pageErrors.join('; ')}`,
      ).toHaveLength(0);
    },
  );


  test(
    'webkit_reconnect_state_sync_smoke: auto-reconnects and restores state_sync on webkit-ipad',
    async ({ page, browserName }) => {
      test.skip(browserName !== 'webkit', 'webkit-ipad reconnect smoke targets WebKit only');

      const pageErrors: string[] = [];
      page.on('pageerror', (err) => pageErrors.push(err.message));
      page.on('console', (msg) => {
        if (msg.type() === 'error') pageErrors.push(msg.text());
      });

      let connectionCount = 0;
      let resolveReconnect!: () => void;
      const reconnectEstablished = new Promise<void>((resolve) => {
        resolveReconnect = resolve;
      });

      await page.routeWebSocket(WS_GLOB, (ws) => {
        connectionCount++;
        if (connectionCount === 1) {
          ws.send(JSON.stringify(makeStateSync(25, '2026-05-18T10:00:00Z')));
          setTimeout(() => ws.close(), DISCONNECT_DELAY_MS);
        } else {
          ws.send(JSON.stringify(makeStateSync(30, '2026-05-18T10:00:05Z')));
          resolveReconnect();
        }
      });

      await setupMockRoutes(page);
      await loginPlayer(page);

      await waitForReconnect(
        reconnectEstablished,
        'WebKit reconnect timeout: client did not reconnect within 10s',
      );

      expect(
        connectionCount,
        'webkit client must reconnect after forced disconnect',
      ).toBeGreaterThanOrEqual(2);

      await expect(page.locator('canvas')).toBeVisible();
      await expect(page.locator('#login-overlay')).toHaveCount(0);

      expect(
        pageErrors,
        `Console errors after WebKit reconnect: ${pageErrors.join('; ')}`,
      ).toHaveLength(0);
    },
  );
});
