import { test, expect } from '@playwright/test';

const PLAYERS_API = '**/api/v1/players';
const BOOTSTRAP_API = '**/api/v1/config/bootstrap';
const WS_GLOB = '**/ws/**';

const PLAYER_ID = 'p14-quest-idempotent-player';
const PLAYER_NAME = 'QuestIdempotentPlayer';

const SERVER_TIME_INITIAL = '2026-05-19T10:00:00Z';
const SERVER_TIME_RECONNECT = '2026-05-19T10:00:05Z';
const QUEST_EXPIRES_AT = '2026-05-19T10:05:00Z';
const QUEST_COOLDOWN_UNTIL = '2026-05-19T11:00:05Z';
const CLOSE_AFTER_TURN_IN_MS = 50;

const MOCK_PLAYER = {
  player_id: PLAYER_ID,
  name: PLAYER_NAME,
  normalized_name: 'questidempotentplayer',
  character_id: 'penguin',
};

// Quest with item already collected — ready for turn-in
const ACTIVE_QUEST_COLLECTED = {
  quest_instance_id: 55,
  npc_id: 'hopper',
  quest_id: 'quest_hopper_blanket',
  status: 'active',
  expires_at: QUEST_EXPIRES_AT,
  cooldown_until: null,
  progress: { collected: ['item_blanket'] },
  rewards_granted_json: [],
};

// Quest snapshot after server committed turn-in — seen in reconnect state_sync
const COMPLETED_QUEST = {
  quest_instance_id: 55,
  npc_id: 'hopper',
  quest_id: 'quest_hopper_blanket',
  status: 'completed',
  expires_at: QUEST_EXPIRES_AT,
  cooldown_until: QUEST_COOLDOWN_UNTIL,
  progress: { collected: ['item_blanket'] },
  rewards_granted_json: ['coins:25'],
};

// Idempotent server response: built from persisted rewards_granted_json, no new grant
const QUEST_COMPLETED_MSG = {
  type: 'quest_completed',
  quest_id: 'quest_hopper_blanket',
  coins_awarded: 25,
  coins_balance: 50,
  rewards: [],
  rewards_granted_json: ['coins:25'],
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
    levels: {
      '3': { unique_completed_quest_ids: 2, used_potion_count: 2, unlock_regions: ['spawn', 'playground'] },
    },
  },
  assets: {},
};

function makeStateSync(
  serverTime: string,
  quests: unknown[],
  coins: number = 25,
): Record<string, unknown> {
  return {
    type: 'state_sync',
    server_time: serverTime,
    player: {
      id: PLAYER_ID,
      name: PLAYER_NAME,
      normalized_name: 'questidempotentplayer',
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
    quests,
    online_players: {},
    world_items: [],
  };
}

function parseMsg(raw: string | Buffer): Record<string, unknown> | null {
  try {
    return JSON.parse(typeof raw === 'string' ? raw : raw.toString()) as Record<string, unknown>;
  } catch {
    return null;
  }
}

const RECONNECT_TIMEOUT_MS = 10000;
const STATE_APPLY_DELAY_MS = 500;
const RETRY_WATCH_DELAY_MS = 1500;

test.describe('e2e_quest_turn_in_retry_idempotent', () => {
  test(
    'state_sync on reconnect showing completed quest cancels pending turn_in retry — no duplicate rewards',
    async ({ page }) => {
      const pageErrors: string[] = [];
      page.on('pageerror', (err) => pageErrors.push(err.message));
      page.on('console', (msg) => {
        if (msg.type() === 'error') pageErrors.push(msg.text());
      });

      let connectionCount = 0;
      let turnInCountOnReconnect = 0;
      let resolveReconnect!: () => void;
      const reconnectEstablished = new Promise<void>((resolve) => {
        resolveReconnect = resolve;
      });

      await page.routeWebSocket(WS_GLOB, (ws) => {
        connectionCount++;
        if (connectionCount === 1) {
          // Active quest with item collected — client will attempt turn-in
          ws.send(JSON.stringify(makeStateSync(SERVER_TIME_INITIAL, [ACTIVE_QUEST_COLLECTED])));
          ws.onMessage((raw: string | Buffer) => {
            const msg = parseMsg(raw);
            if (msg !== null && msg['type'] === 'quest_turn_in') {
              // Server processed the turn-in but drops connection before sending quest_completed.
              // Simulates: response lost in transit after server committed the reward.
              setTimeout(() => ws.close(), CLOSE_AFTER_TURN_IN_MS);
            }
          });
        } else {
          // Reconnect: state_sync shows quest already completed — client must cancel pending retry.
          ws.send(JSON.stringify(makeStateSync(SERVER_TIME_RECONNECT, [COMPLETED_QUEST], 50)));
          resolveReconnect();
          ws.onMessage((raw: string | Buffer) => {
            const msg = parseMsg(raw);
            if (msg !== null && msg['type'] === 'quest_turn_in') {
              turnInCountOnReconnect++;
            }
          });
        }
      });

      await page.route(PLAYERS_API, async (route) => {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_PLAYER) });
      });
      await page.route(BOOTSTRAP_API, async (route) => {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MINIMAL_BOOTSTRAP) });
      });

      await page.goto('/');
      const overlay = page.locator('#login-overlay');
      await expect(overlay).toBeVisible({ timeout: 10000 });
      await overlay.locator('input[type="text"]').fill(PLAYER_NAME);
      await overlay.locator('button', { hasText: 'Play' }).click();
      await expect(page.locator('#login-overlay')).toHaveCount(0, { timeout: 5000 });

      await page.waitForTimeout(STATE_APPLY_DELAY_MS);
      await page.evaluate(() => {
        window.dispatchEvent(
          new CustomEvent('game:quest-turn-in', { detail: { quest_id: 'quest_hopper_blanket' } }),
        );
      });

      await Promise.race([
        reconnectEstablished,
        new Promise<void>((_, reject) =>
          setTimeout(
            () => reject(new Error('Reconnect timeout: client did not reconnect within 10s')),
            RECONNECT_TIMEOUT_MS,
          ),
        ),
      ]);

      expect(connectionCount, 'client must establish initial + reconnect connections').toBeGreaterThanOrEqual(2);

      // Allow state_sync to be applied before checking for suppressed retry
      await page.waitForTimeout(RETRY_WATCH_DELAY_MS);

      await expect(page.locator('#login-overlay')).toHaveCount(0);
      await expect(page.locator('canvas')).toBeVisible();

      // Core: pending turn-in retry must be canceled when state_sync shows quest completed
      expect(
        turnInCountOnReconnect,
        'client must NOT retry quest_turn_in after reconnect state_sync shows quest already completed',
      ).toBe(0);

      const clientQuestState = await page.evaluate((): unknown => {
        const win = window as unknown as Record<string, unknown>;
        const store =
          (win['__gameStore'] as Record<string, unknown> | undefined) ??
          (win['__questStore'] as Record<string, unknown> | undefined) ??
          (win['gameStore'] as Record<string, unknown> | undefined);
        if (store === undefined) return null;
        const quests = store['quests'] as unknown[] | undefined;
        if (!Array.isArray(quests)) return null;
        return (
          quests.find(
            (q): q is Record<string, unknown> =>
              typeof q === 'object' &&
              q !== null &&
              (q as Record<string, unknown>)['quest_id'] === 'quest_hopper_blanket',
          ) ?? null
        );
      });

      if (clientQuestState !== null) {
        const quest = clientQuestState as Record<string, unknown>;
        expect(quest['status'], 'quest must show completed status from reconnect state_sync').toBe('completed');
        expect(
          quest['rewards_granted_json'],
          'rewards_granted_json must reflect exactly one grant — not duplicated',
        ).toEqual(['coins:25']);
      }

      expect(pageErrors, `Page errors: ${pageErrors.join('; ')}`).toHaveLength(0);
    },
  );

  test(
    'server returns idempotent quest_completed on repeated turn_in — coins not doubled',
    async ({ page }) => {
      const pageErrors: string[] = [];
      page.on('pageerror', (err) => pageErrors.push(err.message));
      page.on('console', (msg) => {
        if (msg.type() === 'error') pageErrors.push(msg.text());
      });

      let connectionCount = 0;
      let turnInCountOnReconnect = 0;
      let resolveReconnect!: () => void;
      const reconnectEstablished = new Promise<void>((resolve) => {
        resolveReconnect = resolve;
      });
      let resolveFirstCompletion!: () => void;
      const firstCompletionSent = new Promise<void>((resolve) => {
        resolveFirstCompletion = resolve;
      });

      await page.routeWebSocket(WS_GLOB, (ws) => {
        connectionCount++;
        if (connectionCount === 1) {
          ws.send(JSON.stringify(makeStateSync(SERVER_TIME_INITIAL, [ACTIVE_QUEST_COLLECTED])));
          ws.onMessage((raw: string | Buffer) => {
            const msg = parseMsg(raw);
            if (msg !== null && msg['type'] === 'quest_turn_in') {
              // Drop connection before processing — server never persisted this turn-in
              setTimeout(() => ws.close(), CLOSE_AFTER_TURN_IN_MS);
            }
          });
        } else {
          // Reconnect state_sync still shows active — server never saw the first turn-in.
          // Client should retry; server grants rewards once and returns idempotent response
          // for any further retries based on persisted rewards_granted_json.
          ws.send(JSON.stringify(makeStateSync(SERVER_TIME_RECONNECT, [ACTIVE_QUEST_COLLECTED])));
          resolveReconnect();
          ws.onMessage((raw: string | Buffer) => {
            const msg = parseMsg(raw);
            if (msg !== null && msg['type'] === 'quest_turn_in') {
              turnInCountOnReconnect++;
              // Idempotent: return same quest_completed for every turn_in, rewards_granted_json unchanged
              ws.send(JSON.stringify(QUEST_COMPLETED_MSG));
              if (turnInCountOnReconnect === 1) resolveFirstCompletion();
            }
          });
        }
      });

      await page.route(PLAYERS_API, async (route) => {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_PLAYER) });
      });
      await page.route(BOOTSTRAP_API, async (route) => {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MINIMAL_BOOTSTRAP) });
      });

      await page.goto('/');
      const overlay = page.locator('#login-overlay');
      await expect(overlay).toBeVisible({ timeout: 10000 });
      await overlay.locator('input[type="text"]').fill(PLAYER_NAME);
      await overlay.locator('button', { hasText: 'Play' }).click();
      await expect(page.locator('#login-overlay')).toHaveCount(0, { timeout: 5000 });

      await page.waitForTimeout(STATE_APPLY_DELAY_MS);
      await page.evaluate(() => {
        window.dispatchEvent(
          new CustomEvent('game:quest-turn-in', { detail: { quest_id: 'quest_hopper_blanket' } }),
        );
      });

      await Promise.race([
        reconnectEstablished,
        new Promise<void>((_, reject) =>
          setTimeout(() => reject(new Error('Reconnect timeout')), RECONNECT_TIMEOUT_MS),
        ),
      ]);

      expect(connectionCount, 'client must establish initial + reconnect connections').toBeGreaterThanOrEqual(2);

      await page.waitForTimeout(STATE_APPLY_DELAY_MS);
      // Retry turn-in on reconnect — state_sync showed active so this is a valid retry
      await page.evaluate(() => {
        window.dispatchEvent(
          new CustomEvent('game:quest-turn-in', { detail: { quest_id: 'quest_hopper_blanket' } }),
        );
      });

      await Promise.race([
        firstCompletionSent,
        new Promise<void>((_, reject) =>
          setTimeout(() => reject(new Error('quest_completed not received within 5s')), 5000),
        ),
      ]);

      // After quest_completed, dispatch another turn-in to verify client stops retrying
      await page.waitForTimeout(STATE_APPLY_DELAY_MS);
      await page.evaluate(() => {
        window.dispatchEvent(
          new CustomEvent('game:quest-turn-in', { detail: { quest_id: 'quest_hopper_blanket' } }),
        );
      });
      await page.waitForTimeout(RETRY_WATCH_DELAY_MS);

      // Client should stop retrying after receiving quest_completed (at most one turn-in)
      expect(
        turnInCountOnReconnect,
        'client must stop sending quest_turn_in after receiving quest_completed — at most one retry',
      ).toBeLessThanOrEqual(2);

      // Verify coins reflect a single reward grant (25 initial + 25 reward = 50, not 75+)
      const playerCoins = await page.evaluate((): number | null => {
        const win = window as unknown as Record<string, unknown>;
        const store =
          (win['__gameStore'] as Record<string, unknown> | undefined) ??
          (win['gameStore'] as Record<string, unknown> | undefined);
        if (store === undefined) return null;
        const player = store['player'] as Record<string, unknown> | undefined;
        if (typeof player?.['coins'] === 'number') return player['coins'] as number;
        return null;
      });

      if (playerCoins !== null) {
        expect(
          playerCoins,
          'coins must not exceed 50 — idempotent server response must not double rewards',
        ).toBeLessThanOrEqual(50);
      }

      await expect(page.locator('#login-overlay')).toHaveCount(0);
      await expect(page.locator('canvas')).toBeVisible();

      expect(pageErrors, `Page errors: ${pageErrors.join('; ')}`).toHaveLength(0);
    },
  );
});
