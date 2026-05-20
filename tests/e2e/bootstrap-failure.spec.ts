import { test, expect, type Page } from '@playwright/test';

/**
 * Tests for issue 16.2: Frontend silently ignores bootstrap failure.
 *
 * These tests fail against the current code because GameScene.loadBootstrapAsync()
 * at src/scenes/GameScene.ts:221 silently returns on failure instead of showing
 * a blocking overlay. They pass once a blocking error overlay is rendered.
 */

const BOOTSTRAP_API = '**/api/v1/config/bootstrap';
const PLAYERS_API = '**/api/v1/players';
const WS_GLOB = '**/ws/**';
const PLAYER_ID_KEY = 'animal_adventure_player_id';
const PLAYER_NAME = 'BootstrapFailTestPlayer';
const PLAYER_ID = 'bootstrap-fail-test-player';

const MOCK_PLAYER = {
  player_id: PLAYER_ID,
  name: PLAYER_NAME,
  normalized_name: 'bootstrapfailtestplayer',
  character_id: 'penguin',
};

async function setupPlayerSession(page: Page): Promise<void> {
  await page.addInitScript(
    ({ key, id }) => {
      localStorage.setItem(key, id);
    },
    { key: PLAYER_ID_KEY, id: PLAYER_ID },
  );
}

async function mockPlayersApi(page: Page): Promise<void> {
  await page.route(PLAYERS_API, (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(MOCK_PLAYER),
    });
  });
}

async function mockWebSocket(page: Page): Promise<void> {
  await page.route(WS_GLOB, (route) => route.abort());
}

test('bootstrap failure shows a blocking overlay element', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (err) => errors.push(`pageerror: ${err.message}`));

  await mockPlayersApi(page);
  await setupPlayerSession(page);

  await page.route(BOOTSTRAP_API, (route) => {
    route.fulfill({ status: 500, body: 'Internal Server Error' });
  });

  await page.goto('/');

  // Wait for the login flow to complete and bootstrap to be attempted.
  await page.waitForTimeout(3000);

  // A blocking overlay must be visible. Accept any visible element that
  // contains error/retry messaging (id, class, or text-based selector).
  const overlaySelectors = [
    '[data-testid="bootstrap-error"]',
    '[id*="bootstrap"][id*="error"]',
    '[class*="bootstrap"][class*="error"]',
    '[class*="error-overlay"]',
    '[class*="blocking-overlay"]',
    'text=Configuration failed',
    'text=failed to load',
    'text=retry',
    'text=Retry',
  ];

  let overlayFound = false;
  for (const selector of overlaySelectors) {
    try {
      const el = page.locator(selector).first();
      if (await el.isVisible({ timeout: 500 })) {
        overlayFound = true;
        break;
      }
    } catch {
      // selector not found, try next
    }
  }

  expect(overlayFound, 'A blocking error overlay must be visible when bootstrap fails').toBe(true);
});

test('bootstrap failure prevents shop button from being interactive', async ({ page }) => {
  await mockPlayersApi(page);
  await setupPlayerSession(page);

  await page.route(BOOTSTRAP_API, (route) => {
    route.fulfill({ status: 500, body: 'Internal Server Error' });
  });

  await page.goto('/');
  await page.waitForTimeout(3000);

  // The shop button should be absent or disabled when bootstrap fails.
  // If it is visible and enabled, the game is allowing interaction despite bootstrap failure.
  const shopButton = page.locator('button:has-text("Shop"), [data-testid="shop-button"], #shop-button').first();
  const shopVisible = await shopButton.isVisible({ timeout: 500 }).catch(() => false);
  const shopEnabled = shopVisible ? await shopButton.isEnabled({ timeout: 500 }).catch(() => false) : false;

  expect(shopEnabled, 'Shop button must not be interactable when bootstrap fails').toBe(false);
});
