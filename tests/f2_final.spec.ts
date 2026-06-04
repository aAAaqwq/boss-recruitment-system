import { test, expect } from '@playwright/test';
import path from 'path';

const ARTIFACT_DIR = path.resolve(__dirname, '..', 'test-results');

test.describe('F2: 最终验收 (Final Acceptance)', () => {

  test('F2-FINAL-001: 连接桌面按钮 -> 已连接状态', async ({ page }) => {
    // Step 1: Navigate
    console.log('[F2-FINAL] Step 1: Navigating to http://localhost:8321/index.html');
    await page.goto('http://localhost:8321/index.html', { waitUntil: 'networkidle' });

    // Step 2: Snapshot - confirm "连接桌面" button exists
    console.log('[F2-FINAL] Step 2: Checking for 连接桌面 button');
    const connectBtn = page.locator('button').filter({ hasText: /连接桌面/ }).first();
    await expect(connectBtn, '应能找到"连接桌面"按钮').toBeVisible({ timeout: 5000 });
    const btnLabel = await connectBtn.textContent();
    console.log(`[F2-FINAL] Found button: "${btnLabel?.trim()}"`);

    // Step 3: Click "连接桌面"
    console.log('[F2-FINAL] Step 3: Clicking 连接桌面');
    await connectBtn.click();

    // Step 4: Wait for "已连接" status (timeout 15s)
    console.log('[F2-FINAL] Step 4: Waiting for "已连接" (15s timeout)');
    const statusText = page.locator('#vncStatusText');
    let connected = false;
    try {
      await expect(statusText).toContainText('已连接', { timeout: 15000 });
      connected = true;
      console.log('[F2-FINAL] "已连接" text appeared');
    } catch {
      console.log('[F2-FINAL] "已连接" text did NOT appear within 15s');
    }

    // Step 5: Take screenshot
    console.log('[F2-FINAL] Step 5: Taking screenshot');
    await page.screenshot({ path: path.join(ARTIFACT_DIR, 'F2-final.png'), fullPage: true });
    console.log('[F2-FINAL] Screenshot saved to test-results/F2-final.png');

    // Step 6: Check status-dot.online exists
    console.log('[F2-FINAL] Step 6: Checking status-dot.online');
    const statusDot = page.locator('.status-dot.online');
    const dotVisible = await statusDot.isVisible().catch(() => false);
    const dotCount = await statusDot.count();

    console.log(`[F2-FINAL] status-dot.online visible: ${dotVisible}`);
    console.log(`[F2-FINAL] status-dot.online count: ${dotCount}`);

    // Final verdict
    console.log(`\n[F2-FINAL] === FINAL VERDICT ===`);
    if (connected && dotVisible) {
      console.log('[F2-FINAL] RESULT: PASS -- VNC connected and status dot online');
    } else if (connected && !dotVisible) {
      console.log('[F2-FINAL] RESULT: PASS (PARTIAL) -- "已连接" text shown but status-dot.online missing');
    } else {
      console.log('[F2-FINAL] RESULT: FAIL -- "已连接" not detected within 15s');
    }

    // Fail the test if not connected
    expect(connected, 'VNC should be connected ("已连接" should appear)').toBe(true);
  });
});
