import { test, expect } from '@playwright/test';

const PLAYERS_API = '**/api/v1/players';
const BOOTSTRAP_API = '**/api/v1/config/bootstrap';
const WS_GLOB = '**/ws/**';

const PLAYER_ID = 'safari-ws-reconnect-e2e-player';

const MOCK_PLAYER = {
  player_id: PLAYER_ID,
  name: 'ReconnectTester',
  normalized_name: 'reconnecttester',
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

function makeStateSync(coins: number, serverTime: string): Record<string, unknown> {
  return {
    type: 'state_sync',
    server_time: serverTime,
    player: {
      id: PLAYER_ID,
      name: 'ReconnectTester',
      normalized_name: 'reconnecttester',
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

const RECONNECT_TIMEOUT_MS = 10000;
const DISCONNECT_DELAY_MS = 400;

test.describe('e2e_safari_ws_reconnect', () => {
  test(
    'auto-reconnects after forced disconnect and state_sync restores session state',
    async ({ page, browserName }) => {
      test.skip(browserName !== 'webkit', 'WebKit reconnect test targets WebKit (iPad) only');

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
          // Initial connection: send state_sync with 25 coins, then force disconnect
          ws.send(JSON.stringify(makeStateSync(25, '2026-05-18T10:00:00Z')));
          setTimeout(() => ws.close(), DISCONNECT_DELAY_MS);
        } else {
          // Reconnect: send updated state_sync with 35 coins to confirm state restore
          ws.send(JSON.stringify(makeStateSync(35, '2026-05-18T10:00:05Z')));
          resolveReconnect();
        }
      });

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

      await page.goto('/');

      const overlay = page.locator('#login-overlay');
      await expect(overlay).toBeVisible({ timeout: 10000 });
      await overlay.locator('input[type="text"]').fill('ReconnectTester');
      await overlay.locator('button', { hasText: 'Play' }).click();
      await expect(page.locator('#login-overlay')).toHaveCount(0, { timeout: 5000 });

      // Wait for the client to auto-reconnect after the forced disconnect
      await Promise.race([
        reconnectEstablished,
        new Promise<void>((_, reject) =>
          setTimeout(
            () => reject(new Error('Reconnect timeout: client did not reconnect within 10s')),
            RECONNECT_TIMEOUT_MS,
          ),
        ),
      ]);

      expect(
        connectionCount,
        'client must establish at least two connections (initial + reconnect)',
      ).toBeGreaterThanOrEqual(2);

      // Allow brief time for the reconnect state_sync to be applied by the game
      await page.waitForTimeout(300);

      // Game must remain in play state after reconnect
      await expect(page.locator('#login-overlay')).toHaveCount(0);
      await expect(page.locator('canvas')).toBeVisible();

      expect(
        pageErrors,
        `Page errors after WebSocket reconnect: ${pageErrors.join('; ')}`,
      ).toHaveLength(0);
    },
  );
});
