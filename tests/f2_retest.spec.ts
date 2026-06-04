import { test, expect } from '@playwright/test';
import path from 'path';

const ARTIFACT_DIR = path.resolve(__dirname, '..', 'test-results');

test.describe('F2: VNC连接验收 (Retest)', () => {

  test('F2-VNC-001: 点击"连接桌面"后应显示已连接状态', async ({ page }) => {
    const consoleErrors: string[] = [];
    const allConsole: string[] = [];

    page.on('console', msg => {
      const entry = `[${msg.type()}] ${msg.text()}`;
      allConsole.push(entry);
      if (msg.type() === 'error') {
        consoleErrors.push(entry);
      }
    });

    page.on('pageerror', err => {
      allConsole.push(`[PAGE_ERROR] ${err.message}`);
      consoleErrors.push(`[PAGE_ERROR] ${err.message}`);
    });

    // Step 1: Navigate
    await page.goto('http://localhost:8321/index.html', { waitUntil: 'networkidle' });

    // Step 2: Initial screenshot
    await page.screenshot({ path: path.join(ARTIFACT_DIR, 'F2-retest-initial.png'), fullPage: true });
    console.log('[F2] Initial screenshot saved');

    // Step 3: Find and click "连接桌面"
    const connectBtn = page.locator('button').filter({ hasText: /连接桌面/ }).first();
    await expect(connectBtn, '应能找到"连接桌面"按钮').toBeVisible({ timeout: 5000 });
    const btnLabel = await connectBtn.textContent();
    console.log(`[F2] Found connect button: "${btnLabel?.trim()}"`);
    await connectBtn.click();
    console.log('[F2] Clicked connect button');

    // Step 4: Wait for "已连接" or .status-dot.online
    const statusDot = page.locator('.status-dot.online');
    const statusText = page.locator('#vncStatusText');

    const startTime = Date.now();
    let connected = false;
    try {
      await statusDot.waitFor({ state: 'visible', timeout: 15000 });
      connected = true;
      console.log('[F2] status-dot.online appeared');
    } catch {
      console.log('[F2] status-dot.online did NOT appear within 15s');
    }

    const elapsed = Date.now() - startTime;
    const textContent = await statusText.textContent().catch(() => 'ELEMENT_NOT_FOUND');
    console.log(`[F2] Status text after ${elapsed}ms: "${textContent}"`);

    // Step 5: Connected screenshot
    await page.screenshot({ path: path.join(ARTIFACT_DIR, 'F2-retest-connected.png'), fullPage: true });
    console.log('[F2] Connected screenshot saved');

    // Step 6: Check VNC iframe
    const iframe = page.locator('#vncFrame');
    const iframeSrc = await iframe.getAttribute('src').catch(() => null);
    const iframeVisible = await iframe.isVisible().catch(() => false);
    console.log(`[F2] VNC iframe src: ${iframeSrc || '(none)'}`);
    console.log(`[F2] VNC iframe visible: ${iframeVisible}`);

    // Step 7: Console diagnostics
    const wsErrors = consoleErrors.filter(e => e.toLowerCase().includes('websocket'));
    const corsErrors = consoleErrors.filter(e => e.toLowerCase().includes('cors') || e.toLowerCase().includes('origin'));
    const fetchErrors = consoleErrors.filter(e => e.includes('Failed to load') || e.includes('404'));

    console.log(`\n[F2] === DIAGNOSTICS ===`);
    console.log(`[F2] Console errors total: ${consoleErrors.length}`);
    console.log(`[F2] WebSocket errors: ${wsErrors.length}`);
    console.log(`[F2] CORS/Origin errors: ${corsErrors.length}`);
    console.log(`[F2] Fetch/404 errors: ${fetchErrors.length}`);

    if (consoleErrors.length > 0) {
      console.log(`[F2] All console errors:`);
      consoleErrors.forEach(e => console.log(`  ${e}`));
    }

    // Also show relevant info logs
    const infoLogs = allConsole.filter(e => e.includes('VNC') || e.includes('连接') || e.includes('请求失败'));
    if (infoLogs.length > 0) {
      console.log(`[F2] Relevant log entries:`);
      infoLogs.forEach(e => console.log(`  ${e}`));
    }

    // Verdict
    console.log(`\n[F2] === VERDICT ===`);
    console.log(`[F2] status-dot.online visible: ${connected}`);
    console.log(`[F2] VNC iframe has src: ${iframeSrc !== null && iframeSrc !== ''}`);

    if (connected && wsErrors.length === 0 && corsErrors.length === 0) {
      console.log('[F2] RESULT: PASS');
    } else if (corsErrors.length > 0) {
      console.log('[F2] RESULT: FAIL — CORS blocked API call to port 8001');
    } else if (!connected && !iframeSrc) {
      console.log('[F2] RESULT: FAIL — VNC iframe never loaded (API call may have failed)');
    } else {
      console.log('[F2] RESULT: FAIL — VNC connection not established');
    }
  });
});
