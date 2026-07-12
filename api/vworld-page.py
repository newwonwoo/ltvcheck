"""Temporary research endpoint: page through VWorld apartment housing price data.
Returns public fields only; API key is never exposed.
"""
import os, json, urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

URL = "https://api.vworld.kr/ned/data/getApartHousingPriceAttr"

def run(pnu, year, page, rows):
    key = os.environ.get("VWORLD_API_KEY", "").strip()
    domain = os.environ.get("VWORLD_DOMAIN", "ltvcheck.vercel.app").strip() or "ltvcheck.vercel.app"
    if not key:
        return {"ok": False, "error": "key_not_set"}
    rows = max(1, min(int(rows), 1000))
    page = max(1, int(page))
    params = {
        "pnu": str(pnu), "stdrYear": str(year), "format": "json",
        "numOfRows": rows, "pageNo": page, "key": key, "domain": domain,
    }
    req = urllib.request.Request(URL + "?" + urllib.parse.urlencode(params), headers={"User-Agent":"ltvcheck-research/1.0"})
    with urllib.request.urlopen(req, timeout=25) as resp:
        data = json.loads(resp.read().decode("utf-8", "replace"))
    root = data.get("apartHousingPrices", data)
    if root.get("resultCode"):
        return {"ok": False, "resultCode": root.get("resultCode"), "resultMsg": root.get("resultMsg")}
    fields = root.get("fields") or root.get("field") or []
    if isinstance(fields, dict): fields = fields.get("field", fields)
    if isinstance(fields, dict): fields = [fields]
    return {"ok": True, "totalCount": int(root.get("totalCount", 0) or 0), "page": page, "rows": rows, "fields": fields or []}

class handler(BaseHTTPRequestHandler):
    def send_json(self, code, obj):
        body=json.dumps(obj,ensure_ascii=False).encode("utf-8")
        self.send_response(code); self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Cache-Control","no-store"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        try:
            q=parse_qs(urlparse(self.path).query)
            pnu=(q.get("pnu") or [""])[0]
            year=(q.get("year") or ["2025"])[0]
            page=(q.get("page") or ["1"])[0]
            rows=(q.get("rows") or ["1000"])[0]
            if len(pnu) < 8: return self.send_json(400,{"ok":False,"error":"pnu_prefix_min_8"})
            self.send_json(200,run(pnu,year,page,rows))
        except Exception as e:
            self.send_json(500,{"ok":False,"error":f"{type(e).__name__}:{e}"})
