import { test, expect, type Page } from '@playwright/test';

const PLAYERS_API = '**/api/v1/players';
const BOOTSTRAP_API = '**/api/v1/config/bootstrap';
const WS_GLOB = '**/ws/**';
const PLAYER_ID_KEY = 'animal_adventure_player_id';

const PLAYER_ID = 'p14smoke-player';
const PLAYER_NAME = 'SmokeL3Player';
const FUTURE_EXPIRES = '2030-01-01T00:00:00Z';
const SERVER_NOW = '2026-05-19T00:00:00Z';

const MOCK_PLAYER = {
  player_id: PLAYER_ID,
  name: PLAYER_NAME,
  normalized_name: 'smokel3player',
  character_id: 'penguin',
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
    {
      id: 'copper',
      name: 'Copper',
      x: 3150,
      y: 3620,
      interaction_radius: 160,
      quest_id: 'quest_copper_bagpipe',
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
      rewards: [
        { type: 'coins', amount: 25 },
        { type: 'equipment', item_id: 'accessory_sleepy_hat', quantity: 1 },
      ],
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
    { id: 'accessory_sleepy_hat', name: 'Sleepy Hat', stackable: false, slot_type: 'equipment', type: 'accessory' },
  ],
  shop: { items: [{ item_id: 'potion_l0', price: 10, unlock_level: 0 }] },
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

function makeStateSync(coins: number): Record<string, unknown> {
  return {
    type: 'state_sync',
    server_time: SERVER_NOW,
    player: {
      id: PLAYER_ID,
      name: PLAYER_NAME,
      normalized_name: 'smokel3player',
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

async function setupRestMocks(page: Page): Promise<void> {
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
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'character_required' }),
      });
      return;
    }
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

async function loginNewPlayer(page: Page): Promise<void> {
  await page.goto('/');
  const overlay = page.locator('#login-overlay');
  await expect(overlay).toBeVisible({ timeout: 15000 });
  await overlay.locator('input[type="text"]').fill(PLAYER_NAME);
  await overlay.locator('button', { hasText: 'Play' }).click();
  const charButtons = overlay.locator('button[data-character-id]');
  await expect(charButtons.first()).toBeVisible({ timeout: 10000 });
  await overlay.locator('button[data-character-id="penguin"]').click();
  await expect(page.locator('#login-overlay')).toHaveCount(0, { timeout: 5000 });
}

async function waitForGameReady(page: Page): Promise<void> {
  await page.waitForFunction(
    () => {
      const store = (window as unknown as Record<string, unknown>)['__gameStore'] as
        | Record<string, unknown>
        | undefined;
      return store?.['ready'] === true && store?.['stateSyncReceived'] === true && store?.['wsOpen'] === true;
    },
    undefined,
    { timeout: 15000 },
  );
}

test.describe('@phase14-smoke', () => {
  test('new player can complete the short MVP L3 loop', async ({ page }) => {
    test.setTimeout(90000);
    const pageErrors: string[] = [];
    page.on('pageerror', (err) => pageErrors.push(err.message));
    page.on('console', (msg) => {
      if (msg.type() === 'error') pageErrors.push(msg.text());
    });

    let questsCompleted = 0;
    let potionsUsed = 0;
    let coinsBalance = 25;
    let resolveL3!: () => void;
    const l3Reached = new Promise<void>((resolve) => {
      resolveL3 = resolve;
    });

    await page.routeWebSocket(WS_GLOB, (ws) => {
      ws.send(JSON.stringify(makeStateSync(25)));

      ws.onMessage((rawMsg: string | Buffer) => {
        let msg: Record<string, unknown>;
        try {
          msg = JSON.parse(typeof rawMsg === 'string' ? rawMsg : rawMsg.toString()) as Record<string, unknown>;
        } catch {
          return;
        }
        const msgType = msg['type'];

        if (msgType === 'npc_interact_request') {
          const npcId = String(msg['npc_id'] ?? '');
          if (npcId === 'hopper') {
            ws.send(
              JSON.stringify({
                type: 'quest_offer',
                npc_id: 'hopper',
                quest_id: 'quest_hopper_blanket',
                title: "Find Hopper's Blanket",
                time_limit_seconds: 300,
                rewards: [
                  { type: 'coins', amount: 25 },
                  { type: 'equipment', item_id: 'accessory_sleepy_hat', quantity: 1 },
                ],
              }),
            );
          } else if (npcId === 'copper') {
            ws.send(
              JSON.stringify({
                type: 'quest_offer',
                npc_id: 'copper',
                quest_id: 'quest_copper_bagpipe',
                title: "Find Copper's Bagpipe",
                time_limit_seconds: 300,
                rewards: [{ type: 'coins', amount: 25 }],
              }),
            );
          }
        } else if (msgType === 'quest_accept') {
          const questId = String(msg['quest_id'] ?? '');
          if (questId === 'quest_hopper_blanket') {
            ws.send(
              JSON.stringify({
                type: 'quest_started',
                quest_id: 'quest_hopper_blanket',
                expires_at: FUTURE_EXPIRES,
                world_items: [
                  { id: 'wi-blanket', item_id: 'item_blanket', quest_instance_id: 1, x: 2600, y: 3100, status: 'spawned' },
                ],
              }),
            );
          } else if (questId === 'quest_copper_bagpipe') {
            ws.send(
              JSON.stringify({
                type: 'quest_started',
                quest_id: 'quest_copper_bagpipe',
                expires_at: FUTURE_EXPIRES,
                world_items: [
                  { id: 'wi-bagpipe', item_id: 'item_bagpipe', quest_instance_id: 2, x: 3330, y: 3500, status: 'spawned' },
                ],
              }),
            );
          }
        } else if (msgType === 'item_pickup_request') {
          const questId = String(msg['quest_id'] ?? '');
          const itemId = questId === 'quest_hopper_blanket' ? 'item_blanket' : 'item_bagpipe';
          ws.send(
            JSON.stringify({
              type: 'item_picked_up',
              quest_id: questId,
              item_id: itemId,
              inventory: [{ item_id: itemId, quantity: 1, slot_type: 'inventory' }],
            }),
          );
        } else if (msgType === 'quest_turn_in') {
          questsCompleted++;
          const questId = String(msg['quest_id'] ?? '');
          coinsBalance += 25;
          ws.send(
            JSON.stringify({
              type: 'quest_completed',
              quest_id: questId,
              coins_awarded: 25,
              coins_balance: coinsBalance,
              rewards_granted:
                questId === 'quest_hopper_blanket'
                  ? [{ type: 'coins', amount: 25 }, { type: 'equipment', item_id: 'accessory_sleepy_hat', quantity: 1 }]
                  : [{ type: 'coins', amount: 25 }],
            }),
          );
        } else if (msgType === 'shop_buy') {
          const itemId = String(msg['item_id'] ?? '');
          if (itemId === 'potion_l0' && coinsBalance >= 10) {
            coinsBalance -= 10;
            ws.send(
              JSON.stringify({ type: 'shop_purchase_ok', item_id: 'potion_l0', coins_balance: coinsBalance }),
            );
            ws.send(
              JSON.stringify({
                type: 'inventory_updated',
                inventory: [],
                equipment: [{ item_id: 'potion_l0', quantity: 1, slot_type: 'equipment' }],
              }),
            );
          }
        } else if (msgType === 'use_item') {
          const itemId = String(msg['item_id'] ?? '');
          if (itemId === 'potion_l0') {
            potionsUsed++;
            ws.send(
              JSON.stringify({
                type: 'item_used',
                item_id: 'potion_l0',
                used_potion_count: potionsUsed,
                coins_balance: coinsBalance,
              }),
            );
            ws.send(JSON.stringify({ type: 'inventory_updated', inventory: [], equipment: [] }));
            if (questsCompleted >= 2 && potionsUsed >= 2) {
              ws.send(JSON.stringify({ type: 'level_up', level: 3, unlocked_regions: ['spawn', 'playground'] }));
              resolveL3();
            }
          }
        }
      });
    });

    await setupRestMocks(page);
    await loginNewPlayer(page);

    await expect(page.locator('canvas')).toBeVisible({ timeout: 15000 });
    await waitForGameReady(page);
    const storedId = await page.evaluate((key) => localStorage.getItem(key), PLAYER_ID_KEY);
    expect(storedId).toBe(PLAYER_ID);

    // Quest 1: Hopper's Blanket — trigger via game event, accept, pickup, turn in
    await page.evaluate(() => {
      window.dispatchEvent(new CustomEvent('game:npc-interact', { detail: { npc_id: 'hopper' } }));
    });

    const questDialog = page.locator('#quest-dialog, [data-testid="quest-dialog"], [data-ui="quest"]');
    await expect(questDialog).toBeVisible({ timeout: 15000 });
    await questDialog.locator('button', { hasText: /accept/i }).click();

    await expect(page.locator('[data-testid="quest-active"], #quest-timer, [data-ui="quest-active"]')).toBeVisible({
      timeout: 15000,
    });

    await page.evaluate(() => {
      window.dispatchEvent(
        new CustomEvent('game:item-pickup', { detail: { quest_id: 'quest_hopper_blanket', item_id: 'item_blanket' } }),
      );
    });

    const turnInBtn = page.locator('button:has-text("Turn In"), button:has-text("Complete"), [data-action="turn-in"]');
    await expect(turnInBtn).toBeVisible({ timeout: 15000 });
    await turnInBtn.click();

    const questComplete = page.locator('[data-testid="quest-completed"]').first();
    await expect(questComplete).toBeVisible({ timeout: 15000 });
    await expect(questComplete).toContainText(/Quest complete|earned \$25/i);

    // Quest 2: Copper's Bagpipe
    await waitForGameReady(page);
    await page.evaluate(() => {
      window.dispatchEvent(new CustomEvent('game:npc-interact', { detail: { npc_id: 'copper' } }));
    });

    await expect(questDialog).toBeVisible({ timeout: 15000 });
    await questDialog.locator('button', { hasText: /accept/i }).click();

    await expect(page.locator('[data-testid="quest-active"], #quest-timer, [data-ui="quest-active"]')).toBeVisible({
      timeout: 15000,
    });

    await page.evaluate(() => {
      window.dispatchEvent(
        new CustomEvent('game:item-pickup', { detail: { quest_id: 'quest_copper_bagpipe', item_id: 'item_bagpipe' } }),
      );
    });

    await expect(turnInBtn).toBeVisible({ timeout: 15000 });
    await turnInBtn.click();

    await expect(questComplete).toBeVisible({ timeout: 15000 });
    await expect(questComplete).toContainText(/Quest complete|earned \$25/i);

    // Buy and use Potion 1
    const shopBtn = page.locator('#hud-shop, [data-hud="shop"], button:has-text("Shop")');
    await expect(shopBtn).toBeVisible({ timeout: 15000 });
    await shopBtn.click();

    const shopPanel = page.locator('#shop-panel, [data-testid="shop-panel"], [data-ui="shop"]');
    await expect(shopPanel).toBeVisible({ timeout: 15000 });
    await shopPanel.locator('[data-buy-item="potion_l0"], button:has-text("Buy")').click();

    const inventoryBtn = page.locator('#hud-inventory, [data-hud="inventory"], button:has-text("Bag")');
    await expect(inventoryBtn).toBeVisible({ timeout: 15000 });
    await inventoryBtn.click();

    const inventoryPanel = page.locator('#inventory-panel, [data-testid="inventory-panel"], [data-ui="inventory"]');
    await expect(inventoryPanel).toBeVisible({ timeout: 15000 });
    await inventoryPanel.locator('[data-use-item="potion_l0"], button:has-text("Use")').click();

    // Buy and use Potion 2 — triggers level_up from WS mock
    await shopBtn.click();
    await expect(shopPanel).toBeVisible({ timeout: 15000 });
    await shopPanel.locator('[data-buy-item="potion_l0"], button:has-text("Buy")').click();

    await inventoryBtn.click();
    await expect(inventoryPanel).toBeVisible({ timeout: 15000 });
    await inventoryPanel.locator('[data-use-item="potion_l0"], button:has-text("Use")').click();

    // Wait for level_up WS message
    await Promise.race([
      l3Reached,
      new Promise<never>((_, reject) =>
        setTimeout(() => reject(new Error('Level-up not triggered within 20s')), 20000),
      ),
    ]);

    // Verify level-up notification visible
    const levelUpNotification = page.locator('[data-testid="level-up"], #level-up-notification').first();
    await expect(levelUpNotification).toBeVisible({ timeout: 15000 });
    await expect(levelUpNotification).toContainText(/Level 3|level up/i);

    await expect(page.locator('canvas')).toBeVisible();
    await expect(page.locator('#login-overlay')).toHaveCount(0);

    expect(
      pageErrors,
      `Smoke console errors: ${pageErrors.join('; ')}`,
    ).toHaveLength(0);
  });
});
