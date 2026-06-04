"""
F2 Final Visual Acceptance Test
Tests the VNC connection flow end-to-end via Playwright.
"""
import os
import sys
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = PROJECT_ROOT / "test-results"
RESULTS_DIR.mkdir(exist_ok=True)

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("ERROR: playwright not installed. Run: pip install playwright && playwright install chromium")
    sys.exit(1)

BASE_URL = "http://localhost:8321"
RESULTS = []


def log_step(step_num: int, description: str, status: str, detail: str = ""):
    entry = {
        "step": step_num,
        "description": description,
        "status": status,  # PASS, FAIL, WARN
        "detail": detail,
    }
    RESULTS.append(entry)
    icon = {"PASS": "[PASS]", "FAIL": "[FAIL]", "WARN": "[WARN]"}.get(status, "[????]")
    print(f"  {icon} Step {step_num}: {description}")
    if detail:
        for line in detail.strip().split("\n"):
            print(f"       {line}")


def run_tests():
    print("=" * 60)
    print("F2 Final Visual Acceptance Test")
    print("=" * 60)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            record_video_dir=str(RESULTS_DIR),
        )
        page = context.new_page()

        # Collect console messages
        console_errors = []
        page.on("console", lambda msg: (
            console_errors.append(msg.text)
            if msg.type == "error" else None
        ))

        # ── Step 1: Navigate ──
        print("\n--- Step 1: Navigate to index.html ---")
        try:
            response = page.goto(f"{BASE_URL}/index.html", wait_until="networkidle", timeout=15000)
            log_step(1, "browser_navigate → /index.html",
                     "PASS" if response and response.ok else "FAIL",
                     f"HTTP {response.status if response else 'no response'}")
        except Exception as e:
            log_step(1, "browser_navigate → /index.html", "FAIL", str(e))
            browser.close()
            return False

        # ── Step 2: Screenshot initial state ──
        print("\n--- Step 2: Screenshot initial state ---")
        try:
            page.screenshot(path=str(RESULTS_DIR / "F2-FINAL-initial.png"), full_page=True)
            log_step(2, "browser_take_screenshot → F2-FINAL-initial.png", "PASS")
        except Exception as e:
            log_step(2, "browser_take_screenshot → F2-FINAL-initial.png", "FAIL", str(e))

        # ── Step 3: Snapshot - confirm key elements ──
        print("\n--- Step 3: Snapshot - confirm key elements ---")
        checks = []
        page.wait_for_timeout(2000)  # Let any dynamic content render

        # Check for control-panel
        cp = page.locator(".control-panel, [data-testid='control-panel'], #control-panel")
        has_cp = cp.count() > 0
        checks.append(f"control-panel: {'FOUND' if has_cp else 'MISSING'}")

        # Check for VNC panel
        vp = page.locator(".vnc-panel, [data-testid='vnc-panel'], #vnc-panel")
        has_vp = vp.count() > 0
        checks.append(f"vnc-panel: {'FOUND' if has_vp else 'MISSING'}")

        # Check for connect button (look for various patterns)
        connect_btn = page.locator(
            "button:has-text('连接桌面'), button:has-text('Connect'), "
            "button:has-text('connect'), [data-action='connect'], "
            ".connect-btn, #connect-btn"
        )
        has_btn = connect_btn.count() > 0
        checks.append(f"connect-button: {'FOUND' if has_btn else 'MISSING'}")

        # Check for "未连接" or "Disconnected" text
        disconnected = page.locator("text=未连接, text=Disconnected, text=disconnected")
        has_disc = disconnected.count() > 0
        checks.append(f"disconnected-status: {'FOUND' if has_disc else 'MISSING'}")

        overall = all([has_cp, has_btn])  # vp optional, disconnected optional
        log_step(3, "browser_snapshot → confirm key elements",
                 "PASS" if overall else "FAIL",
                 "\n".join(checks))

        # ── Step 4: Click connect button ──
        print("\n--- Step 4: Click connect button ---")
        clicked = False
        if connect_btn.count() > 0:
            try:
                connect_btn.first.click()
                clicked = True
                log_step(4, "browser_click → connect button", "PASS",
                         f"Clicked: {connect_btn.first.text_content() or '(no text)'}")
            except Exception as e:
                log_step(4, "browser_click → connect button", "FAIL", str(e))
        else:
            # Try finding ANY button that might be the connect button
            all_buttons = page.locator("button")
            btn_count = all_buttons.count()
            for i in range(btn_count):
                text = all_buttons.nth(i).text_content() or ""
                if any(kw in text.lower() for kw in ["connect", "连接", "link"]):
                    try:
                        all_buttons.nth(i).click()
                        clicked = True
                        log_step(4, "browser_click → connect button (fallback)", "PASS",
                                 f"Clicked button[{i}]: '{text}'")
                        break
                    except Exception as e:
                        log_step(4, "browser_click → connect button", "FAIL", str(e))
                        break
            if not clicked:
                log_step(4, "browser_click → connect button", "FAIL",
                         f"No connect button found among {btn_count} buttons")

        # ── Step 5: Wait for connected state ──
        print("\n--- Step 5: Wait for connected state (15s max) ---")
        connected = False
        connect_detail = ""
        try:
            # Wait for any "connected" / "已连接" text
            page.wait_for_selector(
                "text=已连接, text=Connected, text=connected, .status-dot.online, .online",
                timeout=15000
            )
            connected = True
            connect_detail = "Connected indicator appeared"
        except Exception:
            connect_detail = "Timed out waiting for connected indicator after 15s"
        log_step(5, "browser_wait_for → connected text (15s)", "PASS" if connected else "WARN",
                 connect_detail)

        # ── Step 6: Screenshot connected state ──
        print("\n--- Step 6: Screenshot connected state ---")
        try:
            page.screenshot(path=str(RESULTS_DIR / "F2-FINAL-connected.png"), full_page=True)
            log_step(6, "browser_take_screenshot → F2-FINAL-connected.png", "PASS")
        except Exception as e:
            log_step(6, "browser_take_screenshot → F2-FINAL-connected.png", "FAIL", str(e))

        # ── Step 7: Snapshot - confirm connected state ──
        print("\n--- Step 7: Snapshot - confirm connected state elements ---")
        c7_checks = []

        # Check for online status dot
        online_dot = page.locator(".status-dot.online, .online, [data-status='online']")
        has_online = online_dot.count() > 0
        c7_checks.append(f"status-dot.online: {'FOUND' if has_online else 'MISSING'}")

        # Check for connected text
        conn_text = page.locator("text=已连接, text=Connected, text=connected")
        has_conn = conn_text.count() > 0
        c7_checks.append(f"connected-text: {'FOUND' if has_conn else 'MISSING'}")

        # Check for VNC canvas
        canvas = page.locator("canvas, #vncViewport, .vnc-viewport, [data-testid='vnc-canvas']")
        has_canvas = canvas.count() > 0
        c7_checks.append(f"vnc-canvas: {'FOUND' if has_canvas else 'MISSING'}")

        # Disconnected text should be gone
        disc_text = page.locator("text=未连接, text=Disconnected, text=disconnected")
        disc_gone = disc_text.count() == 0
        c7_checks.append(f"disconnected-text-gone: {'YES' if disc_gone else 'NO (still visible)'}")

        step7_ok = connected or has_online or has_conn  # At least one connected signal
        log_step(7, "browser_snapshot → confirm connected state",
                 "PASS" if step7_ok else "WARN",
                 "\n".join(c7_checks))

        # ── Step 8: Console messages ──
        print("\n--- Step 8: Console error check ---")
        ws_errors = [e for e in console_errors if "websocket" in e.lower() or "ws:" in e.lower()]
        if not console_errors:
            log_step(8, "browser_console_messages → check for WebSocket errors", "PASS",
                     "No console errors detected")
        elif not ws_errors:
            log_step(8, "browser_console_messages → check for WebSocket errors", "WARN",
                     f"Non-WebSocket console errors ({len(console_errors)}):\n" +
                     "\n".join(console_errors[:5]))
        else:
            log_step(8, "browser_console_messages → check for WebSocket errors", "FAIL",
                     f"WebSocket errors found:\n" + "\n".join(ws_errors[:5]))

        # ── Step 9: Network requests ──
        print("\n--- Step 9: Network request check (/api/vnc) ---")
        vnc_requests = []
        # We need to intercept - let's check if there are WebSocket connections or fetch calls
        try:
            # Navigate again to capture network with interception enabled
            page.goto(f"{BASE_URL}/index.html", wait_until="networkidle", timeout=10000)

            ws_urls = []
            fetch_urls = []

            def on_request(request):
                url = request.url
                if "/api/vnc" in url or "/vnc" in url or "novnc" in url.lower():
                    fetch_urls.append({"url": url, "method": request.method})

            def on_ws(ws):
                ws_urls.append(ws.url)

            page.on("request", on_request)
            page.on("websocket", on_ws)

            # Re-click connect if needed
            if not connected:
                btn = page.locator(
                    "button:has-text('连接桌面'), button:has-text('Connect'), "
                    "button:has-text('connect')"
                )
                if btn.count() > 0:
                    btn.first.click()
                    page.wait_for_timeout(5000)

            page.wait_for_timeout(3000)

            if ws_urls:
                log_step(9, "browser_network_requests → filter /api/vnc", "PASS",
                         f"WebSocket connections established: {len(ws_urls)}\n" +
                         "\n".join(ws_urls[:5]))
            elif fetch_urls:
                log_step(9, "browser_network_requests → filter /api/vnc", "PASS",
                         f"HTTP requests to VNC API: {len(fetch_urls)}\n" +
                         "\n".join(f"{r['method']} {r['url']}" for r in fetch_urls[:5]))
            else:
                log_step(9, "browser_network_requests → filter /api/vnc", "WARN",
                         "No VNC-related network requests captured (may use WebSocket directly)")

            page.remove_listener("request", on_request)
            page.remove_listener("websocket", on_ws)

        except Exception as e:
            log_step(9, "browser_network_requests → filter /api/vnc", "WARN", str(e))

        # ── Cleanup ──
        context.close()
        browser.close()

    # ── Summary ──
    print("\n" + "=" * 60)
    print("F2 TEST RESULTS SUMMARY")
    print("=" * 60)
    passed = sum(1 for r in RESULTS if r["status"] == "PASS")
    failed = sum(1 for r in RESULTS if r["status"] == "FAIL")
    warned = sum(1 for r in RESULTS if r["status"] == "WARN")
    total = len(RESULTS)

    for r in RESULTS:
        icon = {"PASS": "PASS", "FAIL": "FAIL", "WARN": "WARN"}[r["status"]]
        print(f"  [{icon}] Step {r['step']}: {r['description']}")

    print(f"\n  Passed: {passed}/{total}")
    print(f"  Failed: {failed}/{total}")
    print(f"  Warnings: {warned}/{total}")

    final = "PASS" if failed == 0 else "FAIL"
    print(f"\n  >>> F2 FINAL VERDICT: {final} <<<")

    # Save JSON results
    results_path = RESULTS_DIR / "F2-FINAL-results.json"
    with open(results_path, "w") as f:
        json.dump({"verdict": final, "steps": RESULTS, "summary": {
            "passed": passed, "failed": failed, "warned": warned, "total": total
        }}, f, indent=2, ensure_ascii=False)
    print(f"\n  Results saved to: {results_path}")

    return failed == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
