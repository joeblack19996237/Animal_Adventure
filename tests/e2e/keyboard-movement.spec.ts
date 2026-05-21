import { test, expect, type Page } from '@playwright/test';

const PLAYERS_API = '**/api/v1/players';
const BOOTSTRAP_API = '**/api/v1/config/bootstrap';
const WS_GLOB = '**/ws/**';
const PLAYER_ID = 'keyboard-movement-player';
const PLAYER_NAME = 'KeyboardMover';

const MOCK_PLAYER = {
  player_id: PLAYER_ID,
  name: PLAYER_NAME,
  normalized_name: 'keyboardmover',
  character_id: 'penguin',
};

const MINIMAL_BOOTSTRAP = {
  map: {},
  map_tiles: {},
  npcs: [],
  quests: [],
  items: [],
  shop: { items: [] },
  characters: [],
  preset_phrases: [],
  progression: {},
  assets: {},
};

async function setupRestMocks(page: Page): Promise<void> {
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

async function login(page: Page): Promise<void> {
  await page.goto('/');
  await page.getByPlaceholder('Enter your name').fill(PLAYER_NAME);
  await page.getByRole('button', { name: 'Play' }).click();
  await expect(page.locator('#login-overlay')).toBeHidden({ timeout: 5000 });
  await expect(page.locator('canvas')).toBeVisible({ timeout: 15000 });
}

test('keyboard movement sends player_move messages', async ({ page }) => {
  const moves: Record<string, unknown>[] = [];

  await setupRestMocks(page);
  await page.routeWebSocket(WS_GLOB, (ws) => {
    ws.send(
      JSON.stringify({
        type: 'state_sync',
        server_time: new Date().toISOString(),
        player: {
          id: PLAYER_ID,
          name: PLAYER_NAME,
          x: 2715,
          y: 3620,
          direction: 'down',
          coins: 25,
          level: 0,
        },
        progress: {},
        inventory: [],
        equipment: [],
        quests: [],
        online_players: {},
        world_items: [],
      }),
    );
    ws.onMessage((raw: string | Buffer) => {
      const msg = JSON.parse(typeof raw === 'string' ? raw : raw.toString()) as Record<string, unknown>;
      if (msg['type'] === 'player_move') moves.push(msg);
    });
  });

  await login(page);
  await page.waitForFunction(
    () => {
      const store = (window as unknown as Record<string, unknown>)['__gameStore'] as
        | Record<string, unknown>
        | undefined;
      return store?.['stateSyncReceived'] === true;
    },
    undefined,
    { timeout: 10000 },
  );
  await page.locator('canvas').click();
  await page.keyboard.down('ArrowRight');
  await expect.poll(() => moves.length, { timeout: 5000 }).toBeGreaterThan(0);
  await page.keyboard.up('ArrowRight');

  expect(moves[0]['direction']).toBe('right');
  expect(Number(moves[0]['x'])).toBeGreaterThan(2715);
});
