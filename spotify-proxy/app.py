#!/usr/bin/env python3
"""Spotify OAuth proxy — stdlib only.

Holds a cached client_credentials access token and forwards GET /v1/* to
api.spotify.com with the bearer header attached. Refreshes the token 30s
before expiry. Listens on :8080 (override via PORT env).
"""
import base64
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET")
LISTEN_PORT = int(os.environ.get("PORT", "8080"))
UPSTREAM = "https://api.spotify.com"
TOKEN_URL = "https://accounts.spotify.com/api/token"

if not CLIENT_ID or not CLIENT_SECRET:
    sys.exit("SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET must be set in env")

# Single-process token cache. Lock guards refresh races between concurrent threads.
_cache = {"access_token": None, "expires_at": 0.0}
_lock = threading.Lock()


def _fetch_token():
    creds = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    req = urllib.request.Request(
        TOKEN_URL,
        data=b"grant_type=client_credentials",
        headers={
            "Authorization": f"Basic {creds}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.load(r)
    return data["access_token"], time.time() + int(data.get("expires_in", 3600)) - 30


def get_token():
    if _cache["access_token"] and time.time() < _cache["expires_at"]:
        return _cache["access_token"]
    with _lock:
        if _cache["access_token"] and time.time() < _cache["expires_at"]:
            return _cache["access_token"]
        tok, exp = _fetch_token()
        _cache["access_token"] = tok
        _cache["expires_at"] = exp
        sys.stderr.write(
            f"[spotify-proxy] token refreshed; valid ~{int(exp - time.time())}s\n"
        )
        sys.stderr.flush()
    return _cache["access_token"]


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._send_json(
                200, {"ok": True, "token_cached": bool(_cache["access_token"])}
            )
            return
        if not self.path.startswith("/v1/"):
            self._send_json(404, {"error": "use /v1/<spotify-endpoint>"})
            return
        try:
            token = get_token()
        except Exception as e:
            self._send_json(502, {"error": f"token fetch failed: {e}"})
            return
        url = UPSTREAM + self.path
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                body = r.read()
                ctype = r.headers.get("Content-Type", "application/json")
                self.send_response(r.status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        except urllib.error.HTTPError as e:
            body = e.read()
            ctype = e.headers.get("Content-Type", "application/json")
            self.send_response(e.code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            self._send_json(502, {"error": f"upstream: {e}"})

    def log_message(self, fmt, *args):
        # Quiet 2xx logs; print 4xx/5xx
        try:
            code = int(args[1])
            if code >= 400:
                super().log_message(fmt, *args)
        except (IndexError, ValueError):
            super().log_message(fmt, *args)


if __name__ == "__main__":
    print(f"[spotify-proxy] listening on :{LISTEN_PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", LISTEN_PORT), Handler).serve_forever()
