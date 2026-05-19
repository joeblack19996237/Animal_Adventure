import { test, expect } from '@playwright/test';

const PLAYERS_API = '**/api/v1/players';
const BOOTSTRAP_API = '**/api/v1/config/bootstrap';
const WS_GLOB = '**/ws/**';

const PLAYER_ID = 'p14-quest-reconnect-player';
const PLAYER_NAME = 'QuestReconnectPlayer';

const MOCK_PLAYER = {
  player_id: PLAYER_ID,
  name: PLAYER_NAME,
  normalized_name: 'questreconnectplayer',
  character_id: 'penguin',
};

// Server time at initial connect and after 5-second reconnect gap
const SERVER_TIME_INITIAL = '2026-05-19T10:00:00Z';
const SERVER_TIME_RECONNECT = '2026-05-19T10:00:05Z';
// Quest expires 5 minutes after SERVER_TIME_INITIAL → ~4:55 remaining on reconnect
const QUEST_EXPIRES_AT = '2026-05-19T10:05:00Z';

const WORLD_ITEM_INSTANCE_ID = 'wi-hopper-blanket-reconnect';
const WORLD_ITEM = {
  id: WORLD_ITEM_INSTANCE_ID,
  item_id: 'item_blanket',
  quest_instance_id: 42,
  x: 2600,
  y: 3100,
  status: 'spawned',
};

const ACTIVE_QUEST = {
  quest_instance_id: 42,
  npc_id: 'hopper',
  quest_id: 'quest_hopper_blanket',
  status: 'active',
  expires_at: QUEST_EXPIRES_AT,
  cooldown_until: null,
  progress: { collected: [] },
  rewards_granted_json: [],
};

const MINIMAL_BOOTSTRAP = {
  map: { width: 5430, height: 7240, spawn: { x: 2715, y: 3620 } },
  map_tiles: { tiles: [], map_width: 5430, map_height: 7240 },
  npcs: [
    { id: 'hopper', name: 'Hopper', x: 2715, y: 3200, interaction_radius: 160, quest_id: 'quest_hopper_blanket' },
  ],
  quests: [
    {
      id: 'quest_hopper_blanket',
      npc_id: 'hopper',
      title: "Find Hopper's Blanket",
      time_limit_seconds: 300,
      required_items: ['item_blanket'],
      item_spawn: { mode: 'fixed', x: 2600, y: 3100, pickup_radius: 96 },
      rewards: [{ type: 'coins', amount: 25 }],
      completion_cooldown_seconds: 3600,
      failure_cooldown_seconds: 1800,
    },
  ],
  items: [
    { id: 'item_blanket', name: 'Blanket', stackable: false, slot_type: 'inventory', type: 'quest_item' },
    { id: 'potion_l0', name: 'Potion', stackable: true, slot_type: 'equipment', type: 'consumable' },
  ],
  shop: { items: [] },
  characters: [
    { id: 'penguin', name: 'Penguin', scale: 1, anchor_x: 0.5, anchor_y: 0.5, collision_radius: 32, directions: {} },
    { id: 'arctic_fox', name: 'Arctic Fox', scale: 1, anchor_x: 0.5, anchor_y: 0.5, collision_radius: 32, directions: {} },
    { id: 'cat_snowman', name: 'Cat Snowman', scale: 1, anchor_x: 0.5, anchor_y: 0.5, collision_radius: 32, directions: {} },
  ],
  preset_phrases: [],
  progression: {
    levels: { '3': { unique_completed_quest_ids: 2, used_potion_count: 2, unlock_regions: ['spawn', 'playground'] } },
  },
  assets: {},
};

function makeStateSync(
  serverTime: string,
  quests: unknown[],
  worldItems: unknown[],
): Record<string, unknown> {
  return {
    type: 'state_sync',
    server_time: serverTime,
    player: {
      id: PLAYER_ID,
      name: PLAYER_NAME,
      normalized_name: 'questreconnectplayer',
      character_id: 'penguin',
      x: 2715,
      y: 3620,
      direction: 'down',
      level: 0,
      coins: 25,
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
    quests,
    online_players: {},
    world_items: worldItems,
  };
}

const RECONNECT_TIMEOUT_MS = 10000;
const DISCONNECT_DELAY_MS = 400;
const STATE_APPLY_DELAY_MS = 400;

test.describe('e2e_quest_reconnect_restores_timers', () => {
  test(
    'reconnect restores active quest timer and world items from state_sync',
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

      // Track whether the client sends item_pickup_request after reconnect,
      // which confirms world items were restored to game state.
      let pickupRequestSentAfterReconnect = false;

      await page.routeWebSocket(WS_GLOB, (ws) => {
        connectionCount++;
        if (connectionCount === 1) {
          // Initial connection: active quest + world item, then force disconnect
          ws.send(JSON.stringify(makeStateSync(SERVER_TIME_INITIAL, [ACTIVE_QUEST], [WORLD_ITEM])));
          setTimeout(() => ws.close(), DISCONNECT_DELAY_MS);
        } else {
          // Reconnect: server sends state_sync restoring the same active quest and world item
          ws.send(JSON.stringify(makeStateSync(SERVER_TIME_RECONNECT, [ACTIVE_QUEST], [WORLD_ITEM])));
          resolveReconnect();

          ws.onMessage((rawMsg: string | Buffer) => {
            let msg: Record<string, unknown>;
            try {
              msg = JSON.parse(typeof rawMsg === 'string' ? rawMsg : rawMsg.toString()) as Record<string, unknown>;
            } catch {
              return;
            }
            if (msg['type'] === 'item_pickup_request') {
              pickupRequestSentAfterReconnect = true;
            }
          });
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
      await overlay.locator('input[type="text"]').fill(PLAYER_NAME);
      await overlay.locator('button', { hasText: 'Play' }).click();
      await expect(page.locator('#login-overlay')).toHaveCount(0, { timeout: 5000 });

      // Wait for auto-reconnect after forced disconnect
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

      // Allow time for the reconnect state_sync to be applied by the game
      await page.waitForTimeout(STATE_APPLY_DELAY_MS);

      // Game must remain in play state — no re-login after reconnect
      await expect(page.locator('#login-overlay')).toHaveCount(0);
      await expect(page.locator('canvas')).toBeVisible();

      // Quest timer countdown must be visible — restored from state_sync expires_at
      const questTimer = page.locator(
        '[data-testid="quest-timer"], #quest-timer, [data-ui="quest-active"], [data-ui="quest-timer"]',
      );
      await expect(questTimer).toBeVisible({ timeout: 5000 });

      // Timer text must contain a countdown (MM:SS or M:SS format)
      // Remaining time ≈ QUEST_EXPIRES_AT − SERVER_TIME_RECONNECT = 4:55
      const timerText = await questTimer.textContent();
      expect(timerText, 'quest timer must display a countdown after reconnect').toMatch(/\d+:\d{2}/);

      // Trigger a simulated item pickup to confirm world item instances were restored
      // to game state — a disconnected client would not be able to send this request.
      await page.evaluate(() => {
        window.dispatchEvent(
          new CustomEvent('game:item-pickup', {
            detail: { quest_id: 'quest_hopper_blanket', item_id: 'item_blanket' },
          }),
        );
      });

      // Allow brief time for the pickup event to be processed
      await page.waitForTimeout(300);

      expect(
        pickupRequestSentAfterReconnect,
        'client must send item_pickup_request after reconnect, confirming world items were restored',
      ).toBe(true);

      expect(
        pageErrors,
        `Page errors after reconnect with active quest: ${pageErrors.join('; ')}`,
      ).toHaveLength(0);
    },
  );
});
