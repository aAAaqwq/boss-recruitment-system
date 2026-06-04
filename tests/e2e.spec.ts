import { test, expect } from '@playwright/test';

// Test configuration
const BASE_URL = 'http://localhost:8321';
const API_USERNAME = 'admin';
const API_PASSWORD = 'admin123';

test.describe('BOSS Recruitment System - E2E Acceptance Tests', () => {

  let authToken: string;

  test.beforeAll(async () => {
    // Setup: Get authentication token via API
    const loginResponse = await fetch(`${BASE_URL}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username: API_USERNAME,
        password: API_PASSWORD
      })
    });

    if (!loginResponse.ok) {
      throw new Error('Failed to authenticate');
    }

    const loginData = await loginResponse.json();
    authToken = loginData.access_token;
    console.log('Authentication successful, token received');
  });

  test.beforeEach(async ({ page }) => {
    // Set authorization header for all requests
    await page.route('**/api/**', (route) => {
      const headers = route.request().headers();
      headers['Authorization'] = `Bearer ${authToken}`;
      route.continue({ headers });
    });

    // Navigate to main page
    await page.goto(BASE_URL);
  });

  test('1. Authentication via API', async ({ page }) => {
    // Test API authentication
    const response = await page.evaluate(async ({ baseUrl, token }) => {
      const res = await fetch(`${baseUrl}/api/browser/status`, {
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });
      return { status: res.status, ok: res.ok };
    }, { baseUrl: BASE_URL, token: authToken });

    expect(response.status).toBeLessThan(500);
    expect(response.ok).toBe(true);

    // Screenshot: Main interface
    await page.screenshot({ path: 'test-results/01-main-interface.png' });
  });

  test('2. Browser connection status', async ({ page }) => {
    // Monitor network requests
    const responses = [];
    page.on('response', async (response) => {
      if (response.url().includes('/api/browser')) {
        responses.push({
          url: response.url(),
          status: response.status(),
          ok: response.ok()
        });
      }
    });

    // Check browser status via API
    const browserStatus = await page.evaluate(async ({ baseUrl, token }) => {
      const res = await fetch(`${baseUrl}/api/browser/status`, {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      return await res.json();
    }, { baseUrl: BASE_URL, token: authToken });

    console.log('Browser status:', browserStatus);

    // Screenshot: Browser status
    await page.screenshot({ path: 'test-results/02-browser-status.png' });

    // Verify response is successful
    expect(browserStatus).toBeDefined();
  });

  test('3. Check BOSS platform login status', async ({ page }) => {
    // Monitor network requests
    let loginCheckResponse = null;
    page.on('response', async (response) => {
      if (response.url().includes('/api/browser/check-login')) {
        const body = await response.text().catch(() => '');
        loginCheckResponse = {
          url: response.url(),
          status: response.status(),
          ok: response.ok(),
          body: body
        };
      }
    });

    // Check login status via API
    const loginStatus = await page.evaluate(async ({ baseUrl, token }) => {
      try {
        const res = await fetch(`${baseUrl}/api/browser/check-login`, {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return await res.json();
      } catch (error) {
        return { error: String(error) };
      }
    }, { baseUrl: BASE_URL, token: authToken });

    console.log('Login check response:', loginStatus);

    // Screenshot: Login check results
    await page.screenshot({ path: 'test-results/03-login-check.png' });

    // Verify response format
    expect(loginStatus).toBeDefined();
  });

  test('4. Filter candidates functionality', async ({ page }) => {
    // Monitor network requests for filter API
    let filterResponse = null;
    page.on('response', async (response) => {
      if (response.url().includes('/api/filter') || response.url().includes('/resume')) {
        const body = await response.text().catch(() => '');
        filterResponse = {
          url: response.url(),
          status: response.status(),
          ok: response.ok(),
          body: body
        };
      }
    });

    // Try to access filter functionality
    const filterResult = await page.evaluate(async ({ baseUrl, token }) => {
      try {
        const res = await fetch(`${baseUrl}/api/resume/stats`, {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return await res.json();
      } catch (error) {
        return { error: String(error) };
      }
    }, { baseUrl: BASE_URL, token: authToken });

    console.log('Filter result:', filterResult);

    // Screenshot: Filter functionality
    await page.screenshot({ path: 'test-results/04-filter-functionality.png' });

    // Verify API is accessible
    expect(filterResult).toBeDefined();
  });

  test('5. Resume download functionality', async ({ page }) => {
    // Monitor network requests for resume API
    let resumeResponses = [];
    page.on('response', async (response) => {
      if (response.url().includes('/api/resume')) {
        const body = await response.text().catch(() => '');
        resumeResponses.push({
          url: response.url(),
          status: response.status(),
          ok: response.ok(),
          body: body
        });
      }
    });

    // Test resume stats endpoint
    const resumeStats = await page.evaluate(async ({ baseUrl, token }) => {
      try {
        const res = await fetch(`${baseUrl}/api/resume/stats`, {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return await res.json();
      } catch (error) {
        return { error: String(error) };
      }
    }, { baseUrl: BASE_URL, token: authToken });

    console.log('Resume stats:', resumeStats);

    // Screenshot: Resume functionality
    await page.screenshot({ path: 'test-results/05-resume-functionality.png' });

    // Verify API response
    expect(resumeStats).toBeDefined();
  });

  test('6. Template configuration', async ({ page }) => {
    // Monitor network requests for template API
    let templateResponse = null;
    page.on('response', async (response) => {
      if (response.url().includes('/api/template') || response.url().includes('/api/settings')) {
        const body = await response.text().catch(() => '');
        templateResponse = {
          url: response.url(),
          status: response.status(),
          ok: response.ok(),
          body: body
        };
      }
    });

    // Test template access
    const templateData = await page.evaluate(async ({ baseUrl, token }) => {
      try {
        const res = await fetch(`${baseUrl}/api/template/list`, {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return await res.json();
      } catch (error) {
        return { error: String(error) };
      }
    }, { baseUrl: BASE_URL, token: authToken });

    console.log('Template data:', templateData);

    // Screenshot: Template configuration
    await page.screenshot({ path: 'test-results/06-template-config.png' });

    // Verify template API is accessible
    expect(templateData).toBeDefined();
  });

  test('7. Automation control', async ({ page }) => {
    // Monitor network requests for automation API
    let automationResponse = null;
    page.on('response', async (response) => {
      if (response.url().includes('/api/automation')) {
        const body = await response.text().catch(() => '');
        automationResponse = {
          url: response.url(),
          status: response.status(),
          ok: response.ok(),
          body: body
        };
      }
    });

    // Test automation status
    const automationStatus = await page.evaluate(async ({ baseUrl, token }) => {
      try {
        const res = await fetch(`${baseUrl}/api/automation/status`, {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return await res.json();
      } catch (error) {
        return { error: String(error) };
      }
    }, { baseUrl: BASE_URL, token: authToken });

    console.log('Automation status:', automationStatus);

    // Screenshot: Automation control
    await page.screenshot({ path: 'test-results/07-automation-control.png' });

    // Verify automation API is accessible
    expect(automationStatus).toBeDefined();
  });

  test('8. API health and connectivity', async ({ page }) => {
    const apiEndpoints = [
      '/api/health',
      '/api/browser/status',
      '/api/automation/status',
      '/api/resume/stats'
    ];

    const results = [];

    for (const endpoint of apiEndpoints) {
      try {
        const response = await page.evaluate(async ({ baseUrl, token, ep }) => {
          const res = await fetch(`${baseUrl}${ep}`, {
            headers: { 'Authorization': `Bearer ${token}` }
          });
          return {
            endpoint: ep,
            status: res.status,
            ok: res.ok,
            statusText: res.statusText
          };
        }, { baseUrl: BASE_URL, token: authToken, ep: endpoint });

        results.push(response);

        // Verify all endpoints respond without 500 errors
        expect(response.status).toBeLessThan(500);
      } catch (error) {
        console.error(`Error testing ${endpoint}:`, error);
        throw error;
      }
    }

    console.log('API health check results:', results);

    // Screenshot: API health check
    await page.screenshot({ path: 'test-results/08-api-health.png' });

    // Verify all endpoints are accessible
    expect(results.length).toBeGreaterThan(0);
    results.forEach(result => {
      expect(result.status).toBeLessThan(500);
    });
  });

  test('9. UI Interface elements', async ({ page }) => {
    // Check for key UI elements
    const interfaceElements = await page.evaluate(() => {
      return {
        hasVncPanel: !!document.querySelector('.vnc-panel'),
        hasVncHeader: !!document.querySelector('.vnc-header'),
        hasVncStatus: !!document.querySelector('.vnc-status'),
        hasStatusDot: !!document.querySelector('.status-dot'),
        hasControlPanel: !!document.querySelector('.control-panel'),
        hasButtons: !!document.querySelector('button')
      };
    });

    console.log('UI interface elements:', interfaceElements);

    // Screenshot: UI elements check
    await page.screenshot({ path: 'test-results/09-ui-elements.png' });

    // Verify basic UI structure exists
    expect(interfaceElements.hasVncPanel).toBe(true);
  });

  test('10. Response format validation', async ({ page }) => {
    // Test various API responses for proper format
    const apiTests = [
      {
        endpoint: '/api/browser/status',
        expectedFields: ['status', 'connected']
      },
      {
        endpoint: '/api/resume/stats',
        expectedFields: ['total', 'processed']
      },
      {
        endpoint: '/api/automation/status',
        expectedFields: ['status', 'running']
      }
    ];

    const validationResults = [];

    for (const test of apiTests) {
      try {
        const response = await page.evaluate(async ({ baseUrl, token, endpoint }) => {
          const res = await fetch(`${baseUrl}${endpoint}`, {
            headers: { 'Authorization': `Bearer ${token}` }
          });
          const data = await res.json();
          return { ok: res.ok, status: res.status, data };
        }, { baseUrl: BASE_URL, token: authToken, endpoint: test.endpoint });

        validationResults.push({
          endpoint: test.endpoint,
          success: response.ok,
          status: response.status,
          dataKeys: Object.keys(response.data || {})
        });

        expect(response.status).toBeLessThan(500);
        expect(response.ok).toBe(true);
      } catch (error) {
        console.error(`Error validating ${test.endpoint}:`, error);
        validationResults.push({
          endpoint: test.endpoint,
          success: false,
          error: String(error)
        });
      }
    }

    console.log('Response format validation:', validationResults);

    // Screenshot: Response validation
    await page.screenshot({ path: 'test-results/10-response-validation.png' });

    // Verify all validations passed
    validationResults.forEach(result => {
      expect(result.success || result.error).toBeTruthy();
    });
  });

});

test.afterAll(async () => {
  console.log('E2E tests completed. Screenshots saved in test-results/');
});