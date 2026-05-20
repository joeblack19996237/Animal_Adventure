import { test, expect, type Page, type APIRequestContext } from '@playwright/test';
import sharp from 'sharp';

const PLAYERS_API = '**/api/v1/players';
const BOOTSTRAP_API = '**/api/v1/config/bootstrap';
const WS_GLOB = '**/ws/**';
const PLAYER_ID_KEY = 'animal_adventure_player_id';

const PLAYER_ID = 'p16-smoke-player';
const PLAYER_NAME = 'Phase16SmokePlayer';
const FUTURE_EXPIRES = '2030-01-01T00:00:00Z';
const SERVER_NOW = '2026-05-20T00:00:00Z';

const MOCK_PLAYER = {
  player_id: PLAYER_ID,
  name: PLAYER_NAME,
  normalized_name: 'phase16smokeplayer',
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

function attachBrowserErrorMonitor(page: Page): string[] {
  const failures: string[] = [];
  page.on('pageerror', (err) => failures.push(`pageerror: ${err.message}`));
  page.on('console', (msg) => {
    if (msg.type() === 'error') failures.push(`console: ${msg.text()}`);
  });
  page.on('response', (response) => {
    const url = response.url();
    const status = response.status();
    const isCriticalResource =
      /\.(js|css|png|jpg|jpeg|webp|json)(?:$|\?)/i.test(url) ||
      url.includes('/api/') ||
      url.endsWith('/health') ||
      url.endsWith('/ready');
    if (isCriticalResource && status >= 400) {
      failures.push(`response ${status}: ${url}`);
    }
  });
  return failures;
}

function makeStateSync(coins: number): Record<string, unknown> {
  return {
    type: 'state_sync',
    server_time: SERVER_NOW,
    player: {
      id: PLAYER_ID,
      name: PLAYER_NAME,
      normalized_name: 'phase16smokeplayer',
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

async function expectOk(request: APIRequestContext, path: string): Promise<void> {
  const response = await request.get(path);
  expect(response.status(), `${path} returned ${response.status()}`).toBe(200);
}

async function expectHeadOk(request: APIRequestContext, path: string): Promise<void> {
  const response = await request.head(path);
  expect(response.status(), `${path} returned ${response.status()}`).toBe(200);
}

async function expectBuiltFrontendAssetOk(request: APIRequestContext): Promise<void> {
  const response = await request.get('/');
  expect(response.status(), `/ returned ${response.status()}`).toBe(200);
  const html = await response.text();
  const match = html.match(/["']\/(assets\/[^"']+\.(?:js|css))["']/);
  expect(match?.[1], 'index.html must reference a built JS or CSS asset under /assets/').toBeTruthy();
  const assetPath = `/${match?.[1]}`;
  await expectHeadOk(request, assetPath);
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
  await expect(overlay.locator('button[data-character-id="penguin"]')).toBeVisible({ timeout: 10000 });
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

async function expectCanvasNonblank(page: Page): Promise<void> {
  const canvas = page.locator('#game-container canvas, canvas').first();
  await expect(canvas).toBeVisible({ timeout: 15000 });
  const box = await canvas.boundingBox();
  expect(box, 'canvas bounding box must not be null').not.toBeNull();
  if (!box) throw new Error('canvas bounding box is null');
  expect(box.width).toBeGreaterThan(0);
  expect(box.height).toBeGreaterThan(0);
  const screenshot = await canvas.screenshot();
  const { data, info } = await sharp(screenshot).ensureAlpha().raw().toBuffer({ resolveWithObject: true });
  const strideX = Math.max(1, Math.floor(info.width / 40));
  const strideY = Math.max(1, Math.floor(info.height / 40));
  let visiblePixels = 0;
  for (let y = 0; y < info.height; y += strideY) {
    for (let x = 0; x < info.width; x += strideX) {
      const index = (y * info.width + x) * info.channels;
      const red = data[index] ?? 0;
      const green = data[index + 1] ?? 0;
      const blue = data[index + 2] ?? 0;
      const alpha = data[index + 3] ?? 0;
      if (alpha > 0 && (red !== 0 || green !== 0 || blue !== 0)) {
        visiblePixels++;
        if (visiblePixels >= 5) return;
      }
    }
  }
  expect(visiblePixels, 'canvas screenshot must contain visible non-black pixels').toBeGreaterThanOrEqual(5);
}

test.describe('@phase16-smoke', () => {
  test('nginx serves frontend, assets, and backend health routes', async ({ request }) => {
    await expectOk(request, '/');
    await expectBuiltFrontendAssetOk(request);
    await expectOk(request, '/health');
    await expectOk(request, '/ready');
    await expectHeadOk(request, '/assets/images/MapTiles/map_tile_0_0.png');
    await expectHeadOk(request, '/assets/images/Items/game_map_full.png');
  });

  test('duplicate session is enforced through nginx WebSocket routing', async ({ page, request }) => {
    const playerName = `Phase16Duplicate${Date.now()}`;
    const createResponse = await request.post('/api/v1/players', {
      data: { name: playerName, character_id: 'penguin' },
    });
    expect(createResponse.status(), `player creation returned ${createResponse.status()}`).toBe(200);
    const player = (await createResponse.json()) as Record<string, unknown>;
    const playerId = String(player['player_id']);
    expect(playerId).toBeTruthy();

    await page.goto('/');
    const result = await page.evaluate(async (id) => {
      const wsUrl = `${window.location.origin.replace(/^http:\/\//, 'ws://').replace(/^https:\/\//, 'wss://')}/ws/${id}`;
      const firstMessages: unknown[] = [];
      const secondMessages: unknown[] = [];

      function waitForMessage(socket: WebSocket, sink: unknown[], predicate: (msg: Record<string, unknown>) => boolean) {
        return new Promise<Record<string, unknown>>((resolve, reject) => {
          const timeout = window.setTimeout(() => reject(new Error('WebSocket message timeout')), 10000);
          socket.addEventListener('message', (event) => {
            const parsed = JSON.parse(String(event.data)) as Record<string, unknown>;
            sink.push(parsed);
            if (predicate(parsed)) {
              window.clearTimeout(timeout);
              resolve(parsed);
            }
          });
          socket.addEventListener('error', () => {
            window.clearTimeout(timeout);
            reject(new Error('WebSocket error'));
          });
        });
      }

      const first = new WebSocket(wsUrl);
      await waitForMessage(first, firstMessages, (msg) => msg['type'] === 'state_sync');

      const duplicatePromise = waitForMessage(
        first,
        firstMessages,
        (msg) => msg['type'] === 'error' && msg['code'] === 'duplicate_session',
      );
      const second = new WebSocket(wsUrl);
      await waitForMessage(second, secondMessages, (msg) => msg['type'] === 'state_sync');
      await duplicatePromise;

      first.close();
      second.close();
      return { firstMessages, secondMessages };
    }, playerId);

    const firstMessages = result.firstMessages as Record<string, unknown>[];
    const secondMessages = result.secondMessages as Record<string, unknown>[];
    expect(firstMessages.some((msg) => msg['type'] === 'state_sync')).toBe(true);
    expect(firstMessages.some((msg) => msg['type'] === 'error' && msg['code'] === 'duplicate_session')).toBe(true);
    expect(secondMessages.some((msg) => msg['type'] === 'state_sync')).toBe(true);
  });

  test('nginx browser smoke completes L3 loop with reconnect-safe UI state', async ({ page }) => {
    test.setTimeout(90000);
    const browserFailures = attachBrowserErrorMonitor(page);

    let questsCompleted = 0;
    let potionsUsed = 0;
    let coinsBalance = 25;
    let connectionCount = 0;
    let resolveReconnect!: () => void;
    const reconnectEstablished = new Promise<void>((resolve) => {
      resolveReconnect = resolve;
    });
    let resolveL3!: () => void;
    const l3Reached = new Promise<void>((resolve) => {
      resolveL3 = resolve;
    });

    await page.routeWebSocket(WS_GLOB, (ws) => {
      connectionCount++;
      ws.send(JSON.stringify(makeStateSync(coinsBalance)));
      if (connectionCount === 1) {
        setTimeout(() => ws.close(), 250);
      } else {
        resolveReconnect();
      }

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
          const questId = npcId === 'hopper' ? 'quest_hopper_blanket' : 'quest_copper_bagpipe';
          const title = npcId === 'hopper' ? "Find Hopper's Blanket" : "Find Copper's Bagpipe";
          ws.send(
            JSON.stringify({
              type: 'quest_offer',
              npc_id: npcId,
              quest_id: questId,
              title,
              time_limit_seconds: 300,
              rewards:
                questId === 'quest_hopper_blanket'
                  ? [{ type: 'coins', amount: 25 }, { type: 'equipment', item_id: 'accessory_sleepy_hat', quantity: 1 }]
                  : [{ type: 'coins', amount: 25 }],
            }),
          );
        } else if (msgType === 'quest_accept') {
          const questId = String(msg['quest_id'] ?? '');
          const itemId = questId === 'quest_hopper_blanket' ? 'item_blanket' : 'item_bagpipe';
          ws.send(
            JSON.stringify({
              type: 'quest_started',
              quest_id: questId,
              expires_at: FUTURE_EXPIRES,
              world_items: [
                { id: `wi-${questId}`, item_id: itemId, quest_instance_id: questsCompleted + 1, x: 2600, y: 3100, status: 'spawned' },
              ],
            }),
          );
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
          if (String(msg['item_id'] ?? '') === 'potion_l0' && coinsBalance >= 10) {
            coinsBalance -= 10;
            ws.send(JSON.stringify({ type: 'shop_purchase_ok', item_id: 'potion_l0', coins_balance: coinsBalance }));
            ws.send(
              JSON.stringify({
                type: 'inventory_updated',
                inventory: [],
                equipment: [{ item_id: 'potion_l0', quantity: 1, slot_type: 'equipment' }],
              }),
            );
          }
        } else if (msgType === 'use_item') {
          if (String(msg['item_id'] ?? '') === 'potion_l0') {
            potionsUsed++;
            ws.send(JSON.stringify({ type: 'item_used', item_id: 'potion_l0', used_potion_count: potionsUsed, coins_balance: coinsBalance }));
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
    await expectCanvasNonblank(page);
    await waitForGameReady(page);

    await Promise.race([
      reconnectEstablished,
      new Promise<never>((_, reject) => setTimeout(() => reject(new Error('Reconnect not established')), 15000)),
    ]);
    expect(connectionCount).toBeGreaterThanOrEqual(2);

    const storedId = await page.evaluate((key) => localStorage.getItem(key), PLAYER_ID_KEY);
    expect(storedId).toBe(PLAYER_ID);

    const questDialog = page.locator('#quest-dialog, [data-testid="quest-dialog"], [data-ui="quest"]');
    const questActive = page.locator('[data-testid="quest-active"], #quest-timer, [data-ui="quest-active"]');
    const turnInBtn = page.locator('button:has-text("Turn In"), button:has-text("Complete"), [data-action="turn-in"]');

    for (const [npcId, questId, itemId] of [
      ['hopper', 'quest_hopper_blanket', 'item_blanket'],
      ['copper', 'quest_copper_bagpipe', 'item_bagpipe'],
    ] as const) {
      await waitForGameReady(page);
      await page.evaluate((id) => {
        window.dispatchEvent(new CustomEvent('game:npc-interact', { detail: { npc_id: id } }));
      }, npcId);
      await expect(questDialog).toBeVisible({ timeout: 15000 });
      await questDialog.locator('button', { hasText: /accept/i }).click();
      await expect(questActive).toBeVisible({ timeout: 15000 });
      await page.evaluate(
        ({ questId: qid, itemId: iid }) => {
          window.dispatchEvent(new CustomEvent('game:item-pickup', { detail: { quest_id: qid, item_id: iid } }));
        },
        { questId, itemId },
      );
      await expect(turnInBtn).toBeVisible({ timeout: 15000 });
      await turnInBtn.click();
      await expect(page.locator('[data-testid="quest-completed"]').first()).toBeVisible({ timeout: 15000 });
    }

    const shopBtn = page.locator('#hud-shop, [data-hud="shop"], button:has-text("Shop")');
    const inventoryBtn = page.locator('#hud-inventory, [data-hud="inventory"], button:has-text("Bag")');
    const shopPanel = page.locator('#shop-panel, [data-testid="shop-panel"], [data-ui="shop"]');
    const inventoryPanel = page.locator('#inventory-panel, [data-testid="inventory-panel"], [data-ui="inventory"]');

    for (let index = 0; index < 2; index++) {
      await shopBtn.click();
      await expect(shopPanel).toBeVisible({ timeout: 15000 });
      await shopPanel.locator('[data-buy-item="potion_l0"], button:has-text("Buy")').click();
      await inventoryBtn.click();
      await expect(inventoryPanel).toBeVisible({ timeout: 15000 });
      await inventoryPanel.locator('[data-use-item="potion_l0"], button:has-text("Use")').click();
    }

    await Promise.race([
      l3Reached,
      new Promise<never>((_, reject) => setTimeout(() => reject(new Error('Level-up not triggered')), 20000)),
    ]);

    const levelUpNotification = page.locator('[data-testid="level-up"], #level-up-notification').first();
    await expect(levelUpNotification).toBeVisible({ timeout: 15000 });
    await expect(levelUpNotification).toContainText(/Level 3|level up/i);
    await expect(page.locator('#hud-level, [data-stat="level"]').first()).toContainText('3');
    await expectCanvasNonblank(page);

    expect(browserFailures, `Browser failures: ${browserFailures.join('; ')}`).toHaveLength(0);
  });
});

test.describe('soak_30_min', () => {
  test('keeps the nginx-served game alive during the opt-in soak window', async ({ page }) => {
    test.skip(process.env['HARNESS_SOAK'] !== '1', '30-minute soak is opt-in');
    test.setTimeout(31 * 60 * 1000);
    const browserFailures = attachBrowserErrorMonitor(page);
    await setupRestMocks(page);
    await page.routeWebSocket(WS_GLOB, (ws) => {
      ws.send(JSON.stringify(makeStateSync(25)));
    });
    await loginNewPlayer(page);
    await expectCanvasNonblank(page);
    await page.waitForTimeout(30 * 60 * 1000);
    expect(browserFailures, `Browser failures during soak: ${browserFailures.join('; ')}`).toHaveLength(0);
  });
});
