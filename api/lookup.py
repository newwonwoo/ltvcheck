"""
api/lookup.py — Vercel 서버리스 함수 (실시간 공시가 조회 엔드포인트)

흐름: 클라이언트가 주소(또는 등기번호)를 보내면
      → jeonse_pnu.lookup() 이 juso/카카오로 PNU를 만들고
      → 공시가 API로 구·신 공시가를 실시간 조회해
      → 구/신 공시가 + 변동 + 신뢰도를 JSON으로 돌려준다.

★ 키 엔벨롭: API 키들은 오직 이 서버 함수의 os.environ 에서만 읽는다.
  - 로컬:   .env.local 에 저장(.gitignore로 보호 = 깃에 안 올라감)
  - 운영:   Vercel 대시보드 Environment Variables 에 저장
  키는 절대 클라이언트(브라우저)로 내려가지 않는다. 응답엔 결과값만 담긴다.

호출 예:
  GET  /api/lookup?q=서울 강서구 화곡동 504-32 정원빌라 제202호
  POST /api/lookup   body={"q": "..."}
"""

import os
import sys
import json
import datetime
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# 같은 레포의 jeonse_pnu 패키지를 import 할 수 있게 경로 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jeonse_pnu import lookup  # noqa: E402


def _years():
    """올해/작년 공시연도. 공시는 1월 1일 기준이라 현재 연도를 신(this)으로."""
    y = datetime.date.today().year
    return str(y), str(y - 1)


def _run(query, dong=None, ho=None, pnu=None):
    if not query or not query.strip():
        return {"ok": False, "error": "주소 또는 등기고유번호를 입력하세요."}

    this_year, last_year = _years()
    # 키는 환경변수에서 자동 주입(인자로 넘기지 않으면 lookup 내부가 os.environ 사용)
    result = lookup(query.strip(), this_year=this_year, last_year=last_year,
                    dong=dong or None, ho=ho or None, pnu=pnu or None)
    return result.to_dict()


class handler(BaseHTTPRequestHandler):
    def _send(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            qs = parse_qs(urlparse(self.path).query)
            query = (qs.get("q") or [""])[0]
            dong = (qs.get("dong") or [""])[0]
            ho = (qs.get("ho") or [""])[0]
            pnu = (qs.get("pnu") or [""])[0]
            self._send(200, _run(query, dong, ho, pnu))
        except Exception as e:
            self._send(500, {"ok": False, "error": f"{type(e).__name__}"})

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            data = json.loads(raw or "{}")
            self._send(200, _run(data.get("q", ""), data.get("dong", ""),
                                 data.get("ho", ""), data.get("pnu", "")))
        except Exception as e:
            self._send(500, {"ok": False, "error": f"{type(e).__name__}"})
