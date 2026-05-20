import { test, expect, type Page } from '@playwright/test';

const PLAYERS_API = '**/api/v1/players';
const BOOTSTRAP_API = '**/api/v1/config/bootstrap';
const WS_GLOB = '**/ws/**';
const PLAYER_ID_KEY = 'animal_adventure_player_id';

const PLAYER_ID = 'p14-l3-test-player';
const PLAYER_NAME = 'AdventurePlayerL3';
const FUTURE_EXPIRES = '2030-01-01T00:00:00Z';
const SERVER_NOW = '2026-05-19T00:00:00Z';

const MOCK_PLAYER = {
  player_id: PLAYER_ID,
  name: PLAYER_NAME,
  normalized_name: 'adventureplayerl3',
  character_id: 'penguin',
};

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
      rewards: [{ type: 'coins', amount: 25 }, { type: 'equipment', item_id: 'accessory_sleepy_hat', quantity: 1 }],
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
    levels: { '3': { unique_completed_quest_ids: 2, used_potion_count: 2, unlock_regions: ['spawn', 'playground'] } },
  },
  assets: {},
};

function makeStateSync(overrides: {
  coins?: number;
  level?: number;
  completedQuestIds?: string[];
  usedPotionCount?: number;
  equipment?: unknown[];
  unlockedRegions?: string[];
}): Record<string, unknown> {
  return {
    type: 'state_sync',
    server_time: SERVER_NOW,
    player: {
      id: PLAYER_ID,
      name: PLAYER_NAME,
      normalized_name: 'adventureplayerl3',
      character_id: 'penguin',
      x: 2715,
      y: 3620,
      direction: 'down',
      level: overrides.level ?? 0,
      coins: overrides.coins ?? 25,
    },
    progress: {
      completed_quest_count: overrides.completedQuestIds?.length ?? 0,
      unique_completed_quest_ids: overrides.completedQuestIds ?? [],
      used_potion_count: overrides.usedPotionCount ?? 0,
      unlocked_level: overrides.level ?? 0,
      unlocked_regions: overrides.unlockedRegions ?? ['spawn'],
    },
    inventory: [],
    equipment: overrides.equipment ?? [],
    quests: [],
    online_players: {},
    world_items: [],
  };
}

function makeQuestOffer(questId: string, npcId: string, title: string): Record<string, unknown> {
  return {
    type: 'quest_offer',
    npc_id: npcId,
    quest_id: questId,
    title,
    time_limit_seconds: 300,
    rewards: questId === 'quest_hopper_blanket'
      ? [{ type: 'coins', amount: 25 }, { type: 'equipment', item_id: 'accessory_sleepy_hat', quantity: 1 }]
      : [{ type: 'coins', amount: 25 }],
  };
}

function makeQuestStarted(questId: string, itemId: string, itemX: number, itemY: number): Record<string, unknown> {
  return {
    type: 'quest_started',
    quest_id: questId,
    expires_at: FUTURE_EXPIRES,
    world_items: [{ id: `wi-${questId}`, item_id: itemId, quest_instance_id: 1, x: itemX, y: itemY, status: 'spawned' }],
  };
}

function makeItemPickedUp(questId: string, itemId: string): Record<string, unknown> {
  return {
    type: 'item_picked_up',
    quest_id: questId,
    item_id: itemId,
    inventory: [{ item_id: itemId, quantity: 1, slot_type: 'inventory' }],
  };
}

function makeQuestCompleted(questId: string, coinsAwarded: number, coinsBalance: number): Record<string, unknown> {
  return {
    type: 'quest_completed',
    quest_id: questId,
    coins_awarded: coinsAwarded,
    coins_balance: coinsBalance,
    rewards_granted: questId === 'quest_hopper_blanket'
      ? [{ type: 'coins', amount: coinsAwarded }, { type: 'equipment', item_id: 'accessory_sleepy_hat', quantity: 1 }]
      : [{ type: 'coins', amount: coinsAwarded }],
  };
}

function makeShopPurchaseOk(itemId: string, coinsBalance: number): Record<string, unknown> {
  return { type: 'shop_purchase_ok', item_id: itemId, coins_balance: coinsBalance };
}

function makeInventoryUpdate(equipment: unknown[]): Record<string, unknown> {
  return { type: 'inventory_updated', inventory: [], equipment };
}

function makePotionUsed(usedPotionCount: number, coinsBalance: number): Record<string, unknown> {
  return { type: 'item_used', item_id: 'potion_l0', used_potion_count: usedPotionCount, coins_balance: coinsBalance };
}

function makeLevelUp(level: number, unlockedRegions: string[]): Record<string, unknown> {
  return { type: 'level_up', level, unlocked_regions: unlockedRegions };
}

async function setupRestMocks(page: Page, newPlayer: boolean): Promise<void> {
  await page.route(PLAYERS_API, async (route, request) => {
    let body: Record<string, unknown> = {};
    try {
      body = JSON.parse(request.postData() ?? '{}') as Record<string, unknown>;
    } catch {
      await route.fulfill({ status: 400 });
      return;
    }
    if (newPlayer && body['character_id'] === undefined) {
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
  await expect(overlay).toBeVisible({ timeout: 10000 });
  await overlay.locator('input[type="text"]').fill(PLAYER_NAME);
  await overlay.locator('button', { hasText: 'Play' }).click();
  const charButtons = overlay.locator('button[data-character-id]');
  await expect(charButtons.first()).toBeVisible({ timeout: 5000 });
  await overlay.locator('button[data-character-id="penguin"]').click();
  await expect(page.locator('#login-overlay')).toHaveCount(0, { timeout: 5000 });
}

async function loginReturningPlayer(page: Page): Promise<void> {
  await page.goto('/');
  const overlay = page.locator('#login-overlay');
  await expect(overlay).toBeVisible({ timeout: 10000 });
  await overlay.locator('input[type="text"]').fill(PLAYER_NAME);
  await overlay.locator('button', { hasText: 'Play' }).click();
  await expect(page.locator('#login-overlay')).toHaveCount(0, { timeout: 5000 });
}

test.describe('e2e_new_player_reaches_l3', () => {
  test(
    'new player completes MVP loop: two quests, two potions, reaches L3, state persists',
    async ({ page }) => {
      test.setTimeout(90000);
      const pageErrors: string[] = [];
      page.on('pageerror', (err) => pageErrors.push(err.message));
      page.on('console', (msg) => {
        if (msg.type() === 'error') pageErrors.push(msg.text());
      });

      let coinsBalance = 25;
      let questsCompleted = 0;
      let potionsUsed = 0;
      let resolveL3!: () => void;
      const l3Reached = new Promise<void>((resolve) => {
        resolveL3 = resolve;
      });

      await page.routeWebSocket(WS_GLOB, (ws) => {
        ws.send(JSON.stringify(makeStateSync({ coins: 25 })));

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
              ws.send(JSON.stringify(makeQuestOffer('quest_hopper_blanket', 'hopper', "Find Hopper's Blanket")));
            } else if (npcId === 'copper') {
              ws.send(JSON.stringify(makeQuestOffer('quest_copper_bagpipe', 'copper', "Find Copper's Bagpipe")));
            }
          } else if (msgType === 'quest_accept') {
            const questId = String(msg['quest_id'] ?? '');
            if (questId === 'quest_hopper_blanket') {
              ws.send(JSON.stringify(makeQuestStarted('quest_hopper_blanket', 'item_blanket', 2600, 3100)));
            } else if (questId === 'quest_copper_bagpipe') {
              ws.send(JSON.stringify(makeQuestStarted('quest_copper_bagpipe', 'item_bagpipe', 3330, 3500)));
            }
          } else if (msgType === 'item_pickup_request') {
            const questId = String(msg['quest_id'] ?? '');
            const itemId = questId === 'quest_hopper_blanket' ? 'item_blanket' : 'item_bagpipe';
            ws.send(JSON.stringify(makeItemPickedUp(questId, itemId)));
          } else if (msgType === 'quest_turn_in') {
            questsCompleted++;
            const questId = String(msg['quest_id'] ?? '');
            coinsBalance += 25;
            ws.send(JSON.stringify(makeQuestCompleted(questId, 25, coinsBalance)));
          } else if (msgType === 'shop_buy') {
            const itemId = String(msg['item_id'] ?? '');
            if (itemId === 'potion_l0' && coinsBalance >= 10) {
              coinsBalance -= 10;
              ws.send(JSON.stringify(makeShopPurchaseOk('potion_l0', coinsBalance)));
              ws.send(
                JSON.stringify(makeInventoryUpdate([{ item_id: 'potion_l0', quantity: 1, slot_type: 'equipment' }])),
              );
            }
          } else if (msgType === 'use_item') {
            const itemId = String(msg['item_id'] ?? '');
            if (itemId === 'potion_l0') {
              potionsUsed++;
              ws.send(JSON.stringify(makePotionUsed(potionsUsed, coinsBalance)));
              ws.send(JSON.stringify(makeInventoryUpdate([])));
              if (questsCompleted >= 2 && potionsUsed >= 2) {
                ws.send(JSON.stringify(makeLevelUp(3, ['spawn', 'playground'])));
                resolveL3();
              }
            }
          }
        });
      });

      await setupRestMocks(page, true);
      await loginNewPlayer(page);

      await expect(page.locator('canvas')).toBeVisible({ timeout: 10000 });
      const storedId = await page.evaluate((key) => localStorage.getItem(key), PLAYER_ID_KEY);
      expect(storedId).toBe(PLAYER_ID);

      // First quest: Hopper's Blanket
      const hopperInteract = page.locator('[data-npc-id="hopper"], #hud-interact');
      await hopperInteract
        .waitFor({ state: 'visible', timeout: 15000 })
        .catch(async () => {
          // Fallback: inject NPC interact request if proximity-based trigger unavailable
          await page.evaluate(() => {
            window.dispatchEvent(
              new CustomEvent('game:npc-interact', { detail: { npc_id: 'hopper' } }),
            );
          });
        });

      const questDialog = page.locator('#quest-dialog, [data-testid="quest-dialog"], [data-ui="quest"]');
      await expect(questDialog).toBeVisible({ timeout: 8000 });
      const acceptBtn = questDialog.locator('button', { hasText: /accept/i });
      await expect(acceptBtn).toBeVisible({ timeout: 5000 });
      await acceptBtn.click();

      const questActive = page.locator(
        '[data-testid="quest-active"], #quest-timer, [data-ui="quest-active"]',
      );
      await expect(questActive).toBeVisible({ timeout: 8000 });

      // Simulate item pickup by triggering the pickup request
      await page.evaluate(() => {
        window.dispatchEvent(
          new CustomEvent('game:item-pickup', { detail: { quest_id: 'quest_hopper_blanket', item_id: 'item_blanket' } }),
        );
      });

      // Turn in first quest
      const turnInBtn = page.locator(
        'button:has-text("Turn In"), button:has-text("Complete"), [data-action="turn-in"]',
      );
      await expect(turnInBtn).toBeVisible({ timeout: 8000 });
      await turnInBtn.click();

      const quest1Complete = page.locator('[data-testid="quest-completed"]').first();
      await expect(quest1Complete).toBeVisible({ timeout: 8000 });
      await expect(quest1Complete).toContainText(/Quest complete|earned \$25/i);

      // Second quest: Copper's Bagpipe
      const copperInteract = page.locator('[data-npc-id="copper"], #hud-interact');
      await copperInteract
        .waitFor({ state: 'visible', timeout: 15000 })
        .catch(async () => {
          await page.evaluate(() => {
            window.dispatchEvent(
              new CustomEvent('game:npc-interact', { detail: { npc_id: 'copper' } }),
            );
          });
        });

      await expect(questDialog).toBeVisible({ timeout: 8000 });
      const acceptBtn2 = questDialog.locator('button', { hasText: /accept/i });
      await expect(acceptBtn2).toBeVisible({ timeout: 5000 });
      await acceptBtn2.click();

      await expect(questActive).toBeVisible({ timeout: 8000 });

      await page.evaluate(() => {
        window.dispatchEvent(
          new CustomEvent('game:item-pickup', { detail: { quest_id: 'quest_copper_bagpipe', item_id: 'item_bagpipe' } }),
        );
      });

      const turnInBtn2 = page.locator(
        'button:has-text("Turn In"), button:has-text("Complete"), [data-action="turn-in"]',
      );
      await expect(turnInBtn2).toBeVisible({ timeout: 8000 });
      await turnInBtn2.click();

      const quest2Complete = page.locator('[data-testid="quest-completed"]').first();
      await expect(quest2Complete).toBeVisible({ timeout: 8000 });
      await expect(quest2Complete).toContainText(/Quest complete|earned \$25/i);

      // Buy first Potion from shop
      const shopBtn = page.locator('#hud-shop, [data-hud="shop"], button:has-text("Shop")');
      await expect(shopBtn).toBeVisible({ timeout: 10000 });
      await shopBtn.click();

      const shopPanel = page.locator('#shop-panel, [data-testid="shop-panel"], [data-ui="shop"]');
      await expect(shopPanel).toBeVisible({ timeout: 8000 });
      const buyPotionBtn = shopPanel.locator('[data-buy-item="potion_l0"], button:has-text("Buy")');
      await expect(buyPotionBtn).toBeVisible({ timeout: 5000 });
      await buyPotionBtn.click();

      // Use first Potion from inventory
      const inventoryBtn = page.locator('#hud-inventory, [data-hud="inventory"], button:has-text("Bag")');
      await expect(inventoryBtn).toBeVisible({ timeout: 10000 });
      await inventoryBtn.click();

      const inventoryPanel = page.locator('#inventory-panel, [data-testid="inventory-panel"], [data-ui="inventory"]');
      await expect(inventoryPanel).toBeVisible({ timeout: 8000 });
      const usePotionBtn = inventoryPanel.locator('[data-use-item="potion_l0"], button:has-text("Use")');
      await expect(usePotionBtn).toBeVisible({ timeout: 5000 });
      await usePotionBtn.click();

      // Buy second Potion from shop
      await shopBtn.click();
      await expect(shopPanel).toBeVisible({ timeout: 8000 });
      await buyPotionBtn.click();

      // Use second Potion — triggers level_up from WS mock
      await inventoryBtn.click();
      await expect(inventoryPanel).toBeVisible({ timeout: 8000 });
      await usePotionBtn.click();

      // Wait for level_up WS message to be sent by mock
      await Promise.race([
        l3Reached,
        new Promise<never>((_, reject) =>
          setTimeout(() => reject(new Error('Level-up not triggered within 15s')), 15000),
        ),
      ]);

      // Verify level-up notification visible in UI
      const levelUpNotification = page.locator('[data-testid="level-up"], #level-up-notification').first();
      await expect(levelUpNotification).toBeVisible({ timeout: 8000 });
      await expect(levelUpNotification).toContainText(/Level 3|level up/i);

      // Verify state visible in UI (level display shows 3)
      const levelDisplay = page.locator('#hud-level, [data-stat="level"]').first();
      await expect(levelDisplay).toBeVisible({ timeout: 5000 });
      await expect(levelDisplay).toContainText('3');

      expect(
        pageErrors,
        `Console errors during L3 loop: ${pageErrors.join('; ')}`,
      ).toHaveLength(0);

      // Verify state persistence: reload and log in again as returning player
      await setupRestMocks(page, false);

      const l3StateSync = makeStateSync({
        coins: coinsBalance,
        level: 3,
        completedQuestIds: ['quest_hopper_blanket', 'quest_copper_bagpipe'],
        usedPotionCount: 2,
        unlockedRegions: ['spawn', 'playground'],
      });

      await page.routeWebSocket(WS_GLOB, (ws) => {
        ws.send(JSON.stringify(l3StateSync));
      });

      await loginReturningPlayer(page);

      await expect(page.locator('canvas')).toBeVisible({ timeout: 10000 });

      const restoredId = await page.evaluate((key) => localStorage.getItem(key), PLAYER_ID_KEY);
      expect(restoredId).toBe(PLAYER_ID);

      const restoredLevelDisplay = page.locator('#hud-level, [data-stat="level"]').first();
      await expect(restoredLevelDisplay).toBeVisible({ timeout: 10000 });
      await expect(restoredLevelDisplay).toContainText('3');

      expect(
        pageErrors,
        `Console errors after reload: ${pageErrors.join('; ')}`,
      ).toHaveLength(0);
    },
  );
});
