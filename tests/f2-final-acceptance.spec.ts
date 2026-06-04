import { test, expect } from '@playwright/test';
import path from 'path';

const SCREENSHOT_DIR = path.resolve(__dirname, '..', 'test-results');

test('F2 Final Acceptance: connect and verify', async ({ page }) => {
  // Step 1: Navigate
  console.log('[STEP 1] navigate -> http://localhost:8321/index.html');
  await page.goto('http://localhost:8321/index.html', { waitUntil: 'networkidle' });

  // Step 2: Initial screenshot
  console.log('[STEP 2] screenshot -> test-results/F2-FINAL-OK-initial.png');
  await page.screenshot({
    path: path.join(SCREENSHOT_DIR, 'F2-FINAL-OK-initial.png'),
    fullPage: true,
  });

  // Step 3: Click the connect button using semantic locator
  console.log('[STEP 3] click -> "连接桌面" button');
  const connectBtn = page.getByRole('button', { name: /连接桌面/ });
  await expect(connectBtn).toBeVisible({ timeout: 5000 });
  await connectBtn.click();

  // Step 4: Wait for connected confirmation
  // Two elements contain "已连接": the status dot text AND the log entry.
  // Use .first() to pick the first match and avoid strict-mode failures.
  console.log('[STEP 4] wait -> text="已连接" timeout=20s');
  await expect(page.getByText('已连接').first()).toBeVisible({ timeout: 20_000 });

  // Step 5: Connected screenshot
  console.log('[STEP 5] screenshot -> test-results/F2-FINAL-OK-connected.png');
  await page.screenshot({
    path: path.join(SCREENSHOT_DIR, 'F2-FINAL-OK-connected.png'),
    fullPage: true,
  });

  console.log('\n[RESULT] PASS');
});
