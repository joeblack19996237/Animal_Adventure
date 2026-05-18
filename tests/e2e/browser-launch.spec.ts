import { test, expect, chromium, webkit } from '@playwright/test';
import { existsSync } from 'fs';

const PROJECT_CHROMIUM = 'chromium';
const PROJECT_WEBKIT_IPAD = 'webkit-ipad';

test.describe('browser preflight', () => {
  test('browser_launches_chromium', async () => {
    test.skip(
      test.info().project.name !== PROJECT_CHROMIUM,
      'Chromium preflight: skipped in non-chromium projects',
    );

    const execPath = chromium.executablePath();
    if (!existsSync(execPath)) {
      throw new Error(
        `PREFLIGHT FAILURE: Chromium not installed. Expected at: ${execPath}. ` +
          `Run: npx playwright install chromium`,
      );
    }

    const browser = await chromium.launch();
    try {
      const page = await browser.newPage();
      const pageErrors: Error[] = [];
      page.on('pageerror', (err) => pageErrors.push(err));
      page.on('console', (msg) => {
        if (msg.type() === 'error') {
          pageErrors.push(new Error(`Console error: ${msg.text()}`));
        }
      });

      await page.goto('about:blank');
      expect(page.url()).toBe('about:blank');
      expect(pageErrors).toHaveLength(0);
    } finally {
      await browser.close();
    }
  });

  test('browser_launches_webkit_ipad', async () => {
    test.skip(
      test.info().project.name !== PROJECT_WEBKIT_IPAD,
      'WebKit-iPad preflight: skipped in non-webkit-ipad projects',
    );

    const execPath = webkit.executablePath();
    if (!existsSync(execPath)) {
      throw new Error(
        `PREFLIGHT FAILURE: WebKit not installed. Expected at: ${execPath}. ` +
          `Run: npx playwright install webkit`,
      );
    }

    const browser = await webkit.launch();
    try {
      const page = await browser.newPage();
      const pageErrors: Error[] = [];
      page.on('pageerror', (err) => pageErrors.push(err));
      page.on('console', (msg) => {
        if (msg.type() === 'error') {
          pageErrors.push(new Error(`Console error: ${msg.text()}`));
        }
      });

      await page.goto('about:blank');
      expect(page.url()).toBe('about:blank');
      expect(pageErrors).toHaveLength(0);
    } finally {
      await browser.close();
    }
  });
});
