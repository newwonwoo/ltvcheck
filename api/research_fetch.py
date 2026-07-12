"""Temporary research-only proxy for discovering official public-data download URLs.

Allowed hosts are restricted to official VWorld and data.go.kr domains.
GET /api/research_fetch?url=<percent-encoded-url>
"""
from __future__ import annotations

import base64
import json
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler

ALLOWED = {
    "www.vworld.kr",
    "vworld.kr",
    "api.vworld.kr",
    "www.data.go.kr",
    "data.go.kr",
}
MAX_BYTES = 4_000_000


def fetch(url: str):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in ALLOWED:
        raise ValueError("host not allowed")
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; public-price-research/1.0)",
            "Accept": "*/*",
            "Referer": "https://www.vworld.kr/",
        },
    )
    with urllib.request.urlopen(req, timeout=25) as resp:
        raw = resp.read(MAX_BYTES + 1)
        truncated = len(raw) > MAX_BYTES
        raw = raw[:MAX_BYTES]
        ctype = resp.headers.get("Content-Type", "")
        enc = resp.headers.get_content_charset() or "utf-8"
        if any(x in ctype.lower() for x in ("text", "json", "javascript", "xml", "html")):
            payload = raw.decode(enc, "replace")
            mode = "text"
        else:
            payload = base64.b64encode(raw).decode("ascii")
            mode = "base64"
        return {
            "ok": True,
            "status": getattr(resp, "status", 200),
            "final_url": resp.geturl(),
            "content_type": ctype,
            "content_length": resp.headers.get("Content-Length"),
            "content_disposition": resp.headers.get("Content-Disposition"),
            "mode": mode,
            "truncated": truncated,
            "payload": payload,
        }


class handler(BaseHTTPRequestHandler):
    def _send(self, status, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            url = (qs.get("url") or [""])[0]
            if not url:
                self._send(400, {"ok": False, "error": "url required"})
                return
            self._send(200, fetch(url))
        except Exception as exc:
            self._send(500, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})
