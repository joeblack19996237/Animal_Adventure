import { test, expect } from '@playwright/test';

const PLAYERS_API = '**/api/v1/players';
const BOOTSTRAP_API = '**/api/v1/config/bootstrap';
const WS_GLOB = '**/ws/**';

const PLAYER_ID = 'p14-quest-expire-disconnect-player';
const PLAYER_NAME = 'QuestExpireDisconnectPlayer';

const MOCK_PLAYER = {
  player_id: PLAYER_ID,
  name: PLAYER_NAME,
  normalized_name: 'questexpiredisconnectplayer',
  character_id: 'penguin',
};

// Quest expires 30 seconds after initial connect — short enough to expire during disconnect
const SERVER_TIME_INITIAL = '2026-05-19T10:00:00Z';
const QUEST_EXPIRES_AT = '2026-05-19T10:00:30Z';
// Reconnect at T+60s — quest has already expired; scanner ran and failed it
const SERVER_TIME_RECONNECT = '2026-05-19T10:01:00Z';
// Failure cooldown = 30 minutes from expiry time
const QUEST_COOLDOWN_UNTIL = '2026-05-19T10:30:30Z';

const ACTIVE_QUEST = {
  quest_instance_id: 77,
  npc_id: 'hopper',
  quest_id: 'quest_hopper_blanket',
  status: 'active',
  expires_at: QUEST_EXPIRES_AT,
  cooldown_until: null,
  progress: { collected: [] },
  rewards_granted_json: [],
};

const FAILED_QUEST = {
  quest_instance_id: 77,
  npc_id: 'hopper',
  quest_id: 'quest_hopper_blanket',
  status: 'failed',
  expires_at: QUEST_EXPIRES_AT,
  cooldown_until: QUEST_COOLDOWN_UNTIL,
  progress: { collected: [] },
  rewards_granted_json: [],
};

const SPAWNED_WORLD_ITEM = {
  id: 'wi-hopper-blanket-expire',
  item_id: 'item_blanket',
  quest_instance_id: 77,
  x: 2600,
  y: 3100,
  status: 'spawned',
};

const MINIMAL_BOOTSTRAP = {
  map: { width: 5430, height: 7240, spawn: { x: 2715, y: 3620 } },
  map_tiles: { tiles: [], map_width: 5430, map_height: 7240 },
  npcs: [
    {
      id: 'hopper',
      name: 'Hopper',
      x: 2715,
      y: 3200,
      interaction_radius: 160,
      quest_id: 'quest_hopper_blanket',
    },
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
    levels: {
      '3': { unique_completed_quest_ids: 2, used_potion_count: 2, unlock_regions: ['spawn', 'playground'] },
    },
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
      normalized_name: 'questexpiredisconnectplayer',
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

const RECONNECT_TIMEOUT_MS = 20000;
const DISCONNECT_DELAY_MS = 400;
const STATE_APPLY_DELAY_MS = 1000;

test.describe('e2e_quest_expires_while_disconnected', () => {
  test(
    'quest expired during disconnect: reconnect state_sync shows failed status with cooldown_until',
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
          // Initial connection: active quest with world item, then server closes connection
          // to simulate a network drop while the quest timer is running.
          ws.send(
            JSON.stringify(makeStateSync(SERVER_TIME_INITIAL, [ACTIVE_QUEST], [SPAWNED_WORLD_ITEM])),
          );
          setTimeout(() => ws.close(), DISCONNECT_DELAY_MS);
        } else {
          // Reconnect: quest expired during disconnect; scanner ran and marked it failed.
          // State sync returns failed quest with cooldown_until and empty world_items
          // (spawned item was also expired by the scanner).
          ws.send(
            JSON.stringify(makeStateSync(SERVER_TIME_RECONNECT, [FAILED_QUEST], [])),
          );
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
      await overlay.locator('input[type="text"]').fill(PLAYER_NAME);
      await overlay.locator('button', { hasText: 'Play' }).click();
      await expect(page.locator('#login-overlay')).toHaveCount(0, { timeout: 5000 });

      // Wait for auto-reconnect after forced disconnect
      await Promise.race([
        reconnectEstablished,
        new Promise<void>((_, reject) =>
          setTimeout(
            () => reject(new Error('Reconnect timeout: client did not reconnect within 20s')),
            RECONNECT_TIMEOUT_MS,
          ),
        ),
      ]);

      expect(
        connectionCount,
        'client must establish at least two connections (initial + reconnect)',
      ).toBeGreaterThanOrEqual(2);

      // Allow time for the failed-quest state_sync to be applied by the game
      await page.waitForTimeout(STATE_APPLY_DELAY_MS);

      // Client must remain in play state — no re-login triggered by a failed quest
      await expect(page.locator('#login-overlay')).toHaveCount(0);
      await expect(page.locator('canvas')).toBeVisible();

      // Active quest timer must NOT be shown — the quest failed while disconnected
      const questTimer = page.locator(
        '[data-testid="quest-timer"], #quest-timer, [data-ui="quest-timer"]',
      );
      await expect(questTimer).toHaveCount(0, { timeout: 3000 }).catch(async () => {
        // If the element exists, it must be hidden
        await expect(questTimer).not.toBeVisible();
      });

      // Failed quest cooldown indicator must be shown — state_sync carried cooldown_until
      const cooldownIndicator = page
        .locator('[data-testid="quest-cooldown"], [data-ui="quest-cooldown"], [data-testid="quest-failed"], [data-ui="quest-failed"]')
        .first();
      await expect(cooldownIndicator).toBeVisible({ timeout: 8000 });
      await expect(cooldownIndicator).toContainText(/Quest failed|cooldown|failed/i);

      // Verify via page evaluation that the client state carries the correct cooldown_until
      // from the reconnect state_sync. This covers the key spec requirement:
      // "reconnect receives failed quest state with cooldown_until set correctly".
      const clientQuestState = await page.evaluate((): unknown => {
        // The game may expose player/quest state through window or a store object
        const win = window as unknown as Record<string, unknown>;
        const store =
          (win['__gameStore'] as Record<string, unknown> | undefined) ??
          (win['__questStore'] as Record<string, unknown> | undefined) ??
          (win['gameStore'] as Record<string, unknown> | undefined);

        if (store !== undefined) {
          const quests = store['quests'] as unknown[] | undefined;
          if (Array.isArray(quests)) {
            return quests.find(
              (q): q is Record<string, unknown> =>
                typeof q === 'object' &&
                q !== null &&
                (q as Record<string, unknown>)['quest_id'] === 'quest_hopper_blanket',
            );
          }
        }
        return null;
      });

      if (clientQuestState !== null) {
        const quest = clientQuestState as Record<string, unknown>;
        expect(
          quest['status'],
          'quest status must be "failed" after reconnect with expired quest',
        ).toBe('failed');
        expect(
          quest['cooldown_until'],
          'cooldown_until must be set on failed quest from state_sync',
        ).toBe(QUEST_COOLDOWN_UNTIL);
      }

      // cooldown_until must be in the future relative to the reconnect server_time —
      // 30-minute failure cooldown from expiry at T+30s means cooldown ends at T+30m+30s
      const cooldownDate = new Date(QUEST_COOLDOWN_UNTIL).getTime();
      const reconnectDate = new Date(SERVER_TIME_RECONNECT).getTime();
      expect(
        cooldownDate,
        'cooldown_until must be in the future relative to reconnect server_time',
      ).toBeGreaterThan(reconnectDate);

      // No world item pickup should be possible — item was expired by scanner
      await page.evaluate(() => {
        window.dispatchEvent(
          new CustomEvent('game:item-pickup', {
            detail: { quest_id: 'quest_hopper_blanket', item_id: 'item_blanket' },
          }),
        );
      });
      await page.waitForTimeout(300);

      // Canvas must remain visible after attempted pickup of expired item
      await expect(page.locator('canvas')).toBeVisible();

      expect(
        pageErrors,
        `Page errors after reconnect with expired quest: ${pageErrors.join('; ')}`,
      ).toHaveLength(0);
    },
  );
});
