"""Minimal servers for F2 test - dashboard, API, and dummy noVNC."""
import http.server
import json
import os
import threading
import signal
import sys

BASE = '/Users/danielli/.openclaw/workspace/projects/boss-recruitment-system'

# ---- API handler ----
class API(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ('/health', '/api/health'):
            self._json(200, {"status": "healthy"})
        elif self.path == '/api/vnc/config':
            self._json(200, {
                "host": "localhost", "port": 5901, "password": "boss123",
                "novnc_url": "http://localhost:6901/vnc.html?autoconnect=true&reconnect=true&show_dot=true"
            })
        elif self.path == '/api/browser/status':
            self._json(200, {"connected": True, "status": "running"})
        else:
            self._json(200, {"status": "ok"})

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        if length > 0:
            self.rfile.read(length)
        self._json(200, {"status": "ok"})

    def _json(self, code, data):
        body = json.dumps(data).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def log_message(self, f, *a):
        print(f"[API:{self.client_address[1]}] {f % a}")


# ---- Dashboard handler (serves templates/) ----
class Dashboard(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=os.path.join(BASE, 'templates'), **kwargs)

    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        super().end_headers()

    def log_message(self, f, *a):
        print(f"[Dashboard] {f % a}")


# ---- Dummy noVNC handler ----
NOVNC_DIR = os.path.join(BASE, 'test-results', 'novnc_dummy')
os.makedirs(NOVNC_DIR, exist_ok=True)
vnc_html = os.path.join(NOVNC_DIR, 'vnc.html')
if not os.path.exists(vnc_html):
    with open(vnc_html, 'w') as f:
        f.write('<html><body><h1>noVNC</h1><p>Connected</p></body></html>')


class Novnc(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=NOVNC_DIR, **kwargs)

    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        super().end_headers()

    def log_message(self, f, *a):
        print(f"[noVNC] {f % a}")


def serve(port, handler, name):
    srv = http.server.HTTPServer(('0.0.0.0', port), handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    print(f"[{name}] Listening on port {port}")
    return srv


if __name__ == '__main__':
    servers = [
        serve(8321, Dashboard, "Dashboard"),
        serve(8001, API, "API"),
        serve(6901, Novnc, "noVNC"),
    ]
    print("\nAll servers running. Press Ctrl+C to stop.\n")
    try:
        signal.pause()
    except KeyboardInterrupt:
        pass
    finally:
        for s in servers:
            s.shutdown()
        print("Stopped.")
