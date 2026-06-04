import { test, expect } from '@playwright/test';
import path from 'path';

const SCREENSHOT_DIR = path.resolve(__dirname, '..', 'test-results');

test('F2 VNC connection final acceptance', async ({ page }) => {
  // Capture console messages for debugging
  const consoleLogs: string[] = [];
  page.on('console', msg => consoleLogs.push(`[${msg.type()}] ${msg.text()}`));

  // Capture page errors
  const pageErrors: string[] = [];
  page.on('pageerror', err => pageErrors.push(err.message));

  // Step 1: Navigate to the page
  await page.goto('http://localhost:8321/index.html', { waitUntil: 'networkidle' });

  // Step 2: Take initial screenshot
  await page.screenshot({
    path: path.join(SCREENSHOT_DIR, 'F2-FINAL-fixed-initial.png'),
    fullPage: true,
  });
  console.log('[TEST] Initial screenshot saved');

  // Step 3: Verify the connect button exists
  const connectBtn = page.locator('button:has-text("连接桌面")');
  await expect(connectBtn).toBeVisible({ timeout: 10000 });
  console.log('[TEST] Connect button found');

  // Step 4: Click it and wait for network activity
  await connectBtn.click();

  // Wait a moment for the API call to happen
  await page.waitForTimeout(2000);

  // Dump console logs so far
  console.log('[TEST] Console logs so far:');
  consoleLogs.forEach(l => console.log('  ' + l));
  if (pageErrors.length > 0) {
    console.log('[TEST] Page errors:');
    pageErrors.forEach(e => console.log('  ' + e));
  }

  // Step 5: Wait for "已连接" to appear in the status text
  const statusText = page.locator('#vncStatusText');
  await expect(statusText).toContainText('已连接', { timeout: 25000 });

  // Step 6: Take connected screenshot
  await page.screenshot({
    path: path.join(SCREENSHOT_DIR, 'F2-FINAL-fixed-connected.png'),
    fullPage: true,
  });
  console.log('[TEST] Connected screenshot saved');

  // Step 7: Confirm status-dot.online + "已连接"
  const statusDot = page.locator('#vncStatusDot');
  await expect(statusDot).toHaveClass(/online/, { timeout: 5000 });
  console.log('[TEST] status-dot.online confirmed');

  const connectedText = statusText;
  await expect(connectedText).toHaveText('已连接');

  // Print final page state
  const statusDotClass = await statusDot.getAttribute('class');
  const statusTextContent = await statusText.textContent();
  console.log(`[TEST] Final State: dot="${statusDotClass}", text="${statusTextContent}"`);
  console.log('[TEST] PASS: VNC connection established successfully');
});
