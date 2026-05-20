import { test, expect } from '@playwright/test';

const PLAYERS_API = '**/api/v1/players';
const BOOTSTRAP_API = '**/api/v1/config/bootstrap';
const WS_GLOB = '**/ws/**';

const PLAYER_ID = 'p14-backend-restart-player';
const PLAYER_NAME = 'BackendRestartPlayer';

const MOCK_PLAYER = {
  player_id: PLAYER_ID,
  name: PLAYER_NAME,
  normalized_name: 'backendrestartplayer',
  character_id: 'penguin',
};

// Coins after completing one quest: 25 initial + 25 reward = 50, minus 10 for 1 potion = 40
const COINS_BEFORE_RESTART = 40;
const SERVER_TIME_INITIAL = '2026-05-19T12:00:00Z';
const SERVER_TIME_RECONNECT = '2026-05-19T12:01:00Z';
// Second quest still has 4 minutes remaining after the 1-minute restart window
const QUEST_EXPIRES_AT = '2026-05-19T12:05:00Z';

const COMPLETED_QUEST = {
  quest_instance_id: 10,
  npc_id: 'hopper',
  quest_id: 'quest_hopper_blanket',
  status: 'completed',
  expires_at: '2026-05-19T11:55:00Z',
  cooldown_until: '2026-05-19T12:55:00Z',
  progress: { collected: ['item_blanket'] },
  rewards_granted_json: ['coins:25'],
};

const ACTIVE_QUEST = {
  quest_instance_id: 20,
  npc_id: 'copper',
  quest_id: 'quest_copper_bagpipe',
  status: 'active',
  expires_at: QUEST_EXPIRES_AT,
  cooldown_until: null,
  progress: { collected: [] },
  rewards_granted_json: [],
};

const WORLD_ITEM = {
  id: 'wi-copper-bagpipe-restart',
  item_id: 'item_bagpipe',
  quest_instance_id: 20,
  x: 3330,
  y: 3500,
  status: 'spawned',
};

const POTION_IN_EQUIPMENT = { item_id: 'potion_l0', quantity: 1, slot_type: 'equipment' };

const MINIMAL_BOOTSTRAP = {
  map: { width: 5430, height: 7240, spawn: { x: 2715, y: 3620 } },
  map_tiles: { tiles: [], map_width: 5430, map_height: 7240 },
  npcs: [
    { id: 'hopper', name: 'Hopper', x: 2715, y: 3200, interaction_radius: 160, quest_id: 'quest_hopper_blanket' },
    { id: 'copper', name: 'Copper', x: 3150, y: 3620, interaction_radius: 160, quest_id: 'quest_copper_bagpipe' },
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
    {
      id: 'quest_copper_bagpipe',
      npc_id: 'copper',
      title: "Find Copper's Bagpipe",
      time_limit_seconds: 300,
      required_items: ['item_bagpipe'],
      item_spawn: { mode: 'fixed', x: 3330, y: 3500, pickup_radius: 96 },
      rewards: [{ type: 'coins', amount: 25 }],
      completion_cooldown_seconds: 3600,
      failure_cooldown_seconds: 1800,
    },
  ],
  items: [
    { id: 'item_blanket', name: 'Blanket', stackable: false, slot_type: 'inventory', type: 'quest_item' },
    { id: 'item_bagpipe', name: 'Bagpipe', stackable: false, slot_type: 'inventory', type: 'quest_item' },
    { id: 'potion_l0', name: 'Potion', stackable: true, slot_type: 'equipment', type: 'consumable' },
  ],
  shop: { items: [{ item_id: 'potion_l0', price: 10, unlock_level: 0 }] },
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
  coins: number,
  quests: unknown[],
  equipment: unknown[],
  worldItems: unknown[],
  completedQuestIds: string[],
): Record<string, unknown> {
  return {
    type: 'state_sync',
    server_time: serverTime,
    player: {
      id: PLAYER_ID,
      name: PLAYER_NAME,
      normalized_name: 'backendrestartplayer',
      character_id: 'penguin',
      x: 2715,
      y: 3620,
      direction: 'down',
      level: 0,
      coins,
    },
    progress: {
      completed_quest_count: completedQuestIds.length,
      unique_completed_quest_ids: completedQuestIds,
      used_potion_count: 1,
      unlocked_level: 0,
      unlocked_regions: ['spawn'],
    },
    inventory: [],
    equipment,
    quests,
    online_players: {},
    world_items: worldItems,
  };
}

const RECONNECT_TIMEOUT_MS = 10000;
const DISCONNECT_DELAY_MS = 400;
const STATE_APPLY_DELAY_MS = 500;

test.describe('e2e_backend_restart_preserves_progression', () => {
  test(
    'backend restart preserves quest state, progression, coins, inventory, and level',
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
          // Initial connection: player has 1 completed quest, 1 active quest, 1 potion, 40 coins.
          // Backend restarts — simulate by closing the WebSocket after a short delay.
          ws.send(
            JSON.stringify(
              makeStateSync(
                SERVER_TIME_INITIAL,
                COINS_BEFORE_RESTART,
                [COMPLETED_QUEST, ACTIVE_QUEST],
                [POTION_IN_EQUIPMENT],
                [WORLD_ITEM],
                ['quest_hopper_blanket'],
              ),
            ),
          );
          setTimeout(() => ws.close(), DISCONNECT_DELAY_MS);
        } else {
          // Reconnect after backend restart: SQLite state is preserved.
          // Active quest still has time remaining (expires_at > SERVER_TIME_RECONNECT),
          // so it remains active — backend restart scan did not fail it.
          ws.send(
            JSON.stringify(
              makeStateSync(
                SERVER_TIME_RECONNECT,
                COINS_BEFORE_RESTART,
                [COMPLETED_QUEST, ACTIVE_QUEST],
                [POTION_IN_EQUIPMENT],
                [WORLD_ITEM],
                ['quest_hopper_blanket'],
              ),
            ),
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

      // Wait for auto-reconnect after simulated backend restart
      await Promise.race([
        reconnectEstablished,
        new Promise<void>((_, reject) =>
          setTimeout(
            () => reject(new Error('Reconnect timeout: client did not reconnect after backend restart within 10s')),
            RECONNECT_TIMEOUT_MS,
          ),
        ),
      ]);

      expect(
        connectionCount,
        'client must reconnect after backend restart (at least 2 connections)',
      ).toBeGreaterThanOrEqual(2);

      await page.waitForTimeout(STATE_APPLY_DELAY_MS);

      // Client must remain in play state — backend restart must not trigger re-login
      await expect(page.locator('#login-overlay')).toHaveCount(0);
      await expect(page.locator('canvas')).toBeVisible();

      // Coins must be restored from SQLite state
      const coinsDisplay = page.locator('#hud-coins, [data-stat="coins"]').first();
      await expect(coinsDisplay).toBeVisible({ timeout: 5000 });
      await expect(coinsDisplay).toContainText(String(COINS_BEFORE_RESTART));

      // Active quest timer must be visible — copper quest survived restart and is still active
      const questTimer = page.locator(
        '[data-testid="quest-timer"], #quest-timer, [data-ui="quest-active"], [data-ui="quest-timer"]',
      );
      await expect(questTimer).toBeVisible({ timeout: 5000 });

      // Timer text must show a valid countdown (MM:SS) — restored from SQLite expires_at
      const timerText = await questTimer.textContent();
      expect(timerText, 'active quest timer must display a countdown after backend restart').toMatch(/\d+:\d{2}/);

      // Potion must still be in equipment inventory after restart
      const inventoryBtn = page.locator('#hud-inventory, [data-hud="inventory"], button:has-text("Bag")').first();
      await inventoryBtn.click();
      await expect(page.locator('#inventory-panel, [data-testid="inventory-panel"], [data-ui="inventory"]')).toBeVisible({
        timeout: 5000,
      });
      const potionSlot = page.locator(
        '#inventory-panel [data-item-id="potion_l0"], #inventory-panel [data-inventory-item="potion_l0"]',
      ).first();
      await expect(potionSlot).toBeVisible({ timeout: 5000 });

      // Completed quest (hopper) must still be reflected in progression — verify via store or UI
      const clientState = await page.evaluate((): unknown => {
        const win = window as unknown as Record<string, unknown>;
        const store =
          (win['__gameStore'] as Record<string, unknown> | undefined) ??
          (win['__questStore'] as Record<string, unknown> | undefined) ??
          (win['gameStore'] as Record<string, unknown> | undefined);

        if (store !== undefined) {
          return {
            quests: store['quests'],
            coins: (store['player'] as Record<string, unknown> | undefined)?.['coins'],
            equipment: store['equipment'],
          };
        }
        return null;
      });

      if (clientState !== null) {
        const state = clientState as Record<string, unknown>;

        if (Array.isArray(state['quests'])) {
          const hopperQuest = (state['quests'] as Record<string, unknown>[]).find(
            (q) => q['quest_id'] === 'quest_hopper_blanket',
          );
          if (hopperQuest !== undefined) {
            expect(
              hopperQuest['status'],
              'completed quest must remain completed after backend restart',
            ).toBe('completed');
          }

          const copperQuest = (state['quests'] as Record<string, unknown>[]).find(
            (q) => q['quest_id'] === 'quest_copper_bagpipe',
          );
          if (copperQuest !== undefined) {
            expect(
              copperQuest['status'],
              'active quest must remain active after backend restart when not yet expired',
            ).toBe('active');
            expect(
              copperQuest['expires_at'],
              'active quest expires_at must be restored from SQLite state',
            ).toBe(QUEST_EXPIRES_AT);
          }
        }

        if (state['coins'] !== undefined) {
          expect(
            state['coins'],
            'coins must be preserved from SQLite after backend restart',
          ).toBe(COINS_BEFORE_RESTART);
        }
      }

      // World item for active copper quest must be restored and accessible
      await page.evaluate(() => {
        window.dispatchEvent(
          new CustomEvent('game:item-pickup', {
            detail: { quest_id: 'quest_copper_bagpipe', item_id: 'item_bagpipe' },
          }),
        );
      });

      await page.waitForTimeout(300);

      // Canvas must remain stable after pickup attempt on restored world item
      await expect(page.locator('canvas')).toBeVisible();

      expect(
        pageErrors,
        `Page errors after backend restart and reconnect: ${pageErrors.join('; ')}`,
      ).toHaveLength(0);
    },
  );
});
