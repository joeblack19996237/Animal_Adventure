import { expect, test, type Page } from '@playwright/test';

const PLAYERS_API = '**/api/v1/players';
const BOOTSTRAP_API = '**/api/v1/config/bootstrap';
const WS_GLOB = '**/ws/**';
const PLAYER_ID = 'layout-overlap-player';

const MOCK_PLAYER = {
  player_id: PLAYER_ID,
  name: 'LayoutTester',
  normalized_name: 'layouttester',
  character_id: 'penguin',
};

const MOCK_STATE_SYNC = {
  type: 'state_sync',
  server_time: '2026-05-23T10:00:00Z',
  player: {
    id: PLAYER_ID,
    name: 'LayoutTester',
    normalized_name: 'layouttester',
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
  quests: [],
  online_players: {},
  world_items: [],
};

const MINIMAL_BOOTSTRAP = {
  map: { width: 5430, height: 7240 },
  map_tiles: { tiles: [], map_width: 5430, map_height: 7240 },
  npcs: [],
  quests: [],
  items: [{ id: 'potion_l0', name: 'Potion', asset_id: 'potion_l0', stackable: true, slot_type: 'equipment', type: 'consumable' }],
  shop: { items: [{ item_id: 'potion_l0', price: 10, unlock_level: 0 }] },
  characters: [
    { id: 'penguin', name: 'Penguin', scale: 1, anchor_x: 0.5, anchor_y: 0.5, collision_radius: 32, directions: {} },
    { id: 'arctic_fox', name: 'Arctic Fox', scale: 1, anchor_x: 0.5, anchor_y: 0.5, collision_radius: 32, directions: {} },
    { id: 'cat_snowman', name: 'Cat Snowman', scale: 1, anchor_x: 0.5, anchor_y: 0.5, collision_radius: 32, directions: {} },
  ],
  preset_phrases: [],
  progression: { levels: [] },
  assets: {},
};

async function setupLayoutPage(page: Page): Promise<void> {
  await page.route(PLAYERS_API, async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_PLAYER) });
  });

  await page.route(BOOTSTRAP_API, async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MINIMAL_BOOTSTRAP) });
  });

  await page.routeWebSocket(WS_GLOB, (ws) => {
    ws.send(JSON.stringify(MOCK_STATE_SYNC));
    ws.onMessage((msg) => {
      const raw = typeof msg === 'string' ? msg : (msg as Buffer).toString('utf-8');
      const parsed = JSON.parse(raw) as Record<string, unknown>;
      if (parsed['type'] === 'npc_interact_request') {
        ws.send(JSON.stringify({
          type: 'quest_offer',
          quest_id: 'quest_hopper_blanket',
          npc_id: 'hopper',
          title: "Find Elisa's Dance Shoes",
          rewards: [{ type: 'coins', amount: 25 }],
        }));
      }
    });
  });

  await page.goto('/');
  const overlay = page.locator('#login-overlay');
  await expect(overlay).toBeVisible({ timeout: 10000 });
  await overlay.locator('input[type="text"]').fill('LayoutTester');
  await overlay.locator('button', { hasText: 'Play' }).click();
  await expect(page.locator('#game-menu')).toBeVisible({ timeout: 10000 });
}

async function boxFor(page: Page, selector: string): Promise<DOMRect> {
  return page.locator(selector).evaluate((el) => el.getBoundingClientRect().toJSON() as DOMRect);
}

function expectInside(inner: DOMRect, outer: DOMRect): void {
  expect(inner.left).toBeGreaterThanOrEqual(outer.left);
  expect(inner.top).toBeGreaterThanOrEqual(outer.top);
  expect(inner.right).toBeLessThanOrEqual(outer.right);
  expect(inner.bottom).toBeLessThanOrEqual(outer.bottom);
}

test.describe('layout overlap regression checks', () => {
  test('quest dialog content and shop item stay inside their safe panel areas', async ({ page }) => {
    await setupLayoutPage(page);

    await page.evaluate(() => {
      const dialog = document.querySelector('#quest-dialog') as HTMLElement;
      const title = dialog.querySelector('h3') as HTMLElement;
      const rewards = dialog.querySelector('p') as HTMLElement;
      const actions = dialog.querySelector('div') as HTMLElement;
      title.textContent = "Find Elisa's Dance Shoes";
      rewards.textContent = '$25';
      actions.style.display = 'flex';
      dialog.style.display = 'block';
    });
    const dialog = page.locator('#quest-dialog');
    await expect(dialog).toBeVisible({ timeout: 10000 });

    const dialogBox = await boxFor(page, '#quest-dialog');
    expectInside(await boxFor(page, '#quest-dialog h3'), dialogBox);
    expectInside(await boxFor(page, '#quest-dialog p'), dialogBox);
    for (const button of await page.locator('#quest-dialog button').all()) {
      const box = await button.evaluate((el) => el.getBoundingClientRect().toJSON() as DOMRect);
      expectInside(box, dialogBox);
    }

    await page.locator('#hud-shop').click();
    await expect(page.locator('#shop-panel')).toBeVisible();
    const panel = await boxFor(page, '#shop-panel');
    const body = await boxFor(page, '[data-testid="shop-panel-body"]');
    const item = await boxFor(page, '[data-buy-item="potion_l0"]');
    const close = await boxFor(page, '#shop-panel button[aria-label="Close"]');

    expectInside(body, panel);
    expectInside(item, body);
    expect(close.width).toBeGreaterThanOrEqual(44);
    expect(close.height).toBeGreaterThanOrEqual(44);
    expect(close.bottom).toBeLessThanOrEqual(body.top);
  });

  test('menu icons do not overlap and joystick visibility follows platform touch support', async ({ page, browserName }) => {
    await setupLayoutPage(page);

    const menu = page.locator('#game-menu');
    await expect(menu).toBeVisible();
    await expect(menu).toHaveCSS('background-image', 'none');

    const buttons = await page.locator('#game-menu button').all();
    expect(buttons).toHaveLength(4);
    let previousRight = 0;
    for (const button of buttons) {
      const box = await button.evaluate((el) => el.getBoundingClientRect().toJSON() as DOMRect);
      expect(box.left).toBeGreaterThanOrEqual(previousRight);
      previousRight = box.right;
    }

    const joystick = page.locator('#joystick-base');
    if (browserName === 'webkit') {
      await expect(joystick).toBeVisible();
      await expect(joystick).toHaveCSS('pointer-events', 'auto');
    } else {
      await expect(joystick).toBeHidden();
      await expect(joystick).toHaveCSS('pointer-events', 'none');
    }
  });
});
