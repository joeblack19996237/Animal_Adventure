import { test, expect } from '@playwright/test';

const PLAYERS_API = '**/api/v1/players';
const BOOTSTRAP_API = '**/api/v1/config/bootstrap';
const WS_GLOB = '**/ws/**';

const PLAYER_ID = 'touch-joystick-e2e-player';

const MOCK_PLAYER = {
  player_id: PLAYER_ID,
  name: 'TouchTester',
  normalized_name: 'touchtester',
  character_id: 'penguin',
};

const MOCK_STATE_SYNC = {
  type: 'state_sync',
  server_time: '2026-05-18T10:00:00Z',
  player: {
    id: PLAYER_ID,
    name: 'TouchTester',
    normalized_name: 'touchtester',
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
  items: [],
  shop: { items: [] },
  characters: [
    { id: 'penguin', name: 'Penguin', scale: 1, anchor_x: 0.5, anchor_y: 0.5, collision_radius: 32, directions: {} },
    { id: 'arctic_fox', name: 'Arctic Fox', scale: 1, anchor_x: 0.5, anchor_y: 0.5, collision_radius: 32, directions: {} },
    { id: 'cat_snowman', name: 'Cat Snowman', scale: 1, anchor_x: 0.5, anchor_y: 0.5, collision_radius: 32, directions: {} },
  ],
  preset_phrases: [],
  progression: { levels: [] },
  assets: {},
};

test.describe('e2e_touch_joystick_moves_player', () => {
  test('touch joystick simulates player movement in WebKit', async ({ page, browserName }) => {
    test.skip(browserName !== 'webkit', 'touch joystick test targets WebKit (iPad) only');

    const pageErrors: string[] = [];
    page.on('pageerror', (err) => pageErrors.push(err.message));
    page.on('console', (msg) => {
      if (msg.type() === 'error') pageErrors.push(msg.text());
    });

    const playerMoveMessages: Array<Record<string, unknown>> = [];

    await page.routeWebSocket(WS_GLOB, (ws) => {
      ws.send(JSON.stringify(MOCK_STATE_SYNC));
      ws.onMessage((msg) => {
        try {
          const raw = typeof msg === 'string' ? msg : (msg as Buffer).toString('utf-8');
          const parsed = JSON.parse(raw) as Record<string, unknown>;
          if (parsed['type'] === 'player_move') {
            playerMoveMessages.push(parsed);
          }
        } catch {
          // ignore non-JSON messages
        }
      });
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
    await overlay.locator('input[type="text"]').fill('TouchTester');
    await overlay.locator('button', { hasText: 'Play' }).click();
    await expect(page.locator('#login-overlay')).toHaveCount(0, { timeout: 5000 });

    const joystickBase = page.locator('#joystick-base');
    await expect(joystickBase).toBeVisible({ timeout: 10000 });

    const box = await joystickBase.boundingBox();
    expect(box, 'joystick bounding box must not be null').not.toBeNull();
    if (!box) throw new Error('joystick bounding box is null');

    const centerX = box.x + box.width / 2;
    const centerY = box.y + box.height / 2;
    // Move right: shift pointer by 40% of joystick width
    const moveX = centerX + box.width * 0.4;

    // Use Playwright pointer API — avoids new Touch() constructor which is
    // unavailable in Playwright's WebKit build. On real touch devices,
    // pointerdown/pointermove events fire alongside touch events.
    await page.mouse.move(centerX, centerY);
    await page.mouse.down();
    await page.mouse.move(moveX, centerY);

    // Allow up to 500ms for the 20Hz game loop to emit at least one player_move
    await page.waitForTimeout(500);

    const moveMsgs = playerMoveMessages.filter((m) => typeof m['x'] === 'number');
    expect(
      moveMsgs.length,
      'expected at least one player_move message after touch joystick input',
    ).toBeGreaterThan(0);

    const lastMove = moveMsgs[moveMsgs.length - 1];
    expect(
      lastMove['x'],
      'player x must increase when joystick is pushed right',
    ).toBeGreaterThan(2715);

    expect(pageErrors, `Page errors: ${pageErrors.join('; ')}`).toHaveLength(0);
  });
});
