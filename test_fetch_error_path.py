"""Canary check: a failing API call must not leak the request token into stdout.

Run with plain python, no framework:  python3 test_fetch_error_path.py
"""

import http.server
import os
import subprocess
import sys
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parent
CANARY = "CANARYSUPERSECRETtokenabcdef1234567890"


class EchoingAuthError(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = (
            '{"error":"invalid credentials","echo":{"X-Pectrified-Auth":"%s"}}' % CANARY
        ).encode()
        self.send_response(401)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def build(env_extra):
    return subprocess.run(
        [sys.executable, "build.py"],
        env=dict(os.environ, **env_extra),
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=60,
    )


def check(r, out, expected):
    assert r.returncode == 1, f"want exit 1, got {r.returncode}: {out}"
    assert CANARY not in out, f"LEAK: token reached the logs\n{out}"
    assert expected in out, f"missing {expected!r} in output\n{out}"
    print(f"OK {expected}: {out.strip().splitlines()[0]}")


srv = http.server.HTTPServer(("127.0.0.1", 0), EchoingAuthError)
threading.Thread(target=srv.serve_forever, daemon=True).start()
port = srv.server_address[1]

r = build({"PECTRIFIED_TOKEN": CANARY, "PECTRIFIED_URL": f"http://127.0.0.1:{port}"})
check(r, r.stdout + r.stderr, "HTTP 401")
srv.shutdown()

r = build({"PECTRIFIED_TOKEN": CANARY, "PECTRIFIED_URL": "http://127.0.0.1:1"})
check(r, r.stdout + r.stderr, "ConnectionError")
