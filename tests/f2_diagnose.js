const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();

  const errors = [];
  page.on('console', msg => {
    if (msg.type() === 'error') console.log(`[CONSOLE_ERROR] ${msg.text()}`);
    else console.log(`[CONSOLE_${msg.type().toUpperCase()}] ${msg.text()}`);
  });
  page.on('pageerror', err => console.log(`[PAGE_ERROR] ${err.message}`));
  page.on('requestfailed', req => {
    if (req.url().includes('8001') || req.url().includes('6901') || req.url().includes('vnc'))
      console.log(`[REQ_FAILED] ${req.method()} ${req.url()} -> ${req.failure()?.errorText}`);
  });
  page.on('response', resp => {
    if (resp.url().includes('vnc/config'))
      console.log(`[RESPONSE] ${resp.request().method()} ${resp.url()} -> ${resp.status()}`);
  });

  await page.goto('http://localhost:8321/index.html', { waitUntil: 'networkidle' });
  console.log('[TEST] Page loaded');

  const btn = page.locator('button').filter({ hasText: /连接桌面/ }).first();
  const visible = await btn.isVisible({ timeout: 3000 });
  console.log(`[TEST] Button visible: ${visible}`);
  const label = await btn.textContent();
  console.log(`[TEST] Button label: "${label?.trim()}"`);

  await btn.click();
  console.log('[TEST] Button clicked');

  // Wait up to 20s
  await page.waitForTimeout(1000);

  // Check console and network
  console.log('[TEST] Checking VNC status...');
  const statusDot = page.locator('.status-dot');
  const dotClass = await statusDot.getAttribute('class');
  console.log(`[TEST] status-dot class: ${dotClass}`);

  const statusText = page.locator('#vncStatusText');
  const text = await statusText.textContent();
  console.log(`[TEST] Status text: "${text}"`);

  const iframe = page.locator('#vncFrame');
  const iframeSrc = await iframe.getAttribute('src');
  console.log(`[TEST] VNC iframe src: ${iframeSrc}`);
  const iframeDisplay = await iframe.evaluate(el => el.style.display);
  console.log(`[TEST] VNC iframe display: ${iframeDisplay}`);

  // Wait a bit more for the iframe to potentially load
  await page.waitForTimeout(5000);

  const dotClass2 = await statusDot.getAttribute('class');
  console.log(`[TEST] After 6s, status-dot class: ${dotClass2}`);
  const text2 = await statusText.textContent();
  console.log(`[TEST] After 6s, Status text: "${text2}"`);

  const iframeSrc2 = await iframe.getAttribute('src');
  console.log(`[TEST] After 6s, VNC iframe src: ${iframeSrc2}`);

  await page.screenshot({ path: '/Users/danielli/.openclaw/workspace/projects/boss-recruitment-system/test-results/F2-final.png', fullPage: true });

  await browser.close();
})();
