"""
api/refine.py — 도로명/지번 주소 정제 (독립 엔드포인트)

이 서비스의 핵심 엔진. 도로명주소든 지번주소든 넣으면:
  - 입력 종류 판별(도로명/지번/등기고유번호)
  - juso(행정안전부)로 표준 지번주소 + 도로명주소 확보
  - PNU 19자리 + 4요소(법정동코드/본번/부번/산여부) 조립
  - 공동주택 여부, 신뢰도, 다중매칭 경고

공시가(VWorld)와 무관하게 juso만으로 동작하므로 VWorld 키 없이도 즉시 사용 가능.

호출:
  GET  /api/refine?q=경인로 302
  GET  /api/refine?q=서울 강서구 화곡동 504-32
  POST /api/refine   {"q": "..."}
"""

import os
import sys
import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _refine(q):
    from jeonse_pnu.inputs import route_input
    from jeonse_pnu.registry_parser import parse_registry_address
    from jeonse_pnu.providers import geocode

    out = {
        "input": q,
        "ok": False,
        "input_type": None,
        "road_address": None,
        "jibun_address": None,
        "pnu": None,
        "pnu_parts": None,
        "is_apartment": None,
        "dong": None,
        "ho": None,
        "tier": 0,
        "candidates": 0,
        "ambiguous": False,
        "region_candidates": [],
        "warnings": [],
    }

    routed = route_input(q)
    out["input_type"] = routed.종류

    # 등기고유번호는 주소가 아니므로 별도 안내
    if routed.종류 == "등기고유번호":
        out["warnings"].append("등기고유번호는 주소 정제 대상이 아님(보증DB 역조회 필요)")
        return out

    # 등기부/일반 주소 파싱 → 동/호, 도로명 여부
    parsed = parse_registry_address(routed.원본)
    out["dong"] = parsed.건물동
    out["ho"] = parsed.호
    if parsed.도로명여부:
        out["input_type"] = "도로명주소"
    elif parsed.본번:
        out["input_type"] = "지번주소"

    query = parsed.검색질의 or routed.원본

    juso_key = os.environ.get("JUSO_API_KEY", "").strip() or None
    kakao_key = os.environ.get("KAKAO_REST_KEY", "").strip() or None
    geo = geocode(query, juso_key=juso_key, kakao_key=kakao_key)

    out["warnings"].extend(geo.warnings)
    out["tier"] = geo.tier
    out["candidates"] = geo.candidates

    # 동명이지: 여러 행정구역 매칭 시 후보 전부 노출 + 상위 행정구역 요구
    if geo.ambiguous:
        out["ambiguous"] = True
        out["region_candidates"] = geo.region_candidates
        out["warnings"].append("상위 행정구역(시/도·시군구)을 함께 입력하면 정확해져요")
        return out

    if not geo.ok:
        out["warnings"].append("정제 실패 - 주소를 찾지 못함")
        return out

    out["jibun_address"] = geo.refined_address
    out["road_address"] = geo.road_address
    out["is_apartment"] = geo.is_apartment
    out["pnu"] = geo.parts.to_pnu()
    out["pnu_parts"] = {
        "법정동코드": geo.parts.beopjeongdong_code,
        "본번": geo.parts.bonbun,
        "부번": geo.parts.bubun,
        "산여부": geo.parts.mountain,
    }
    out["ok"] = True
    return out


class handler(BaseHTTPRequestHandler):
    def _send(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            qs = parse_qs(urlparse(self.path).query)
            q = (qs.get("q") or [""])[0].strip()
            if not q:
                self._send(400, {"ok": False, "error": "q 파라미터 필요 (예: /api/refine?q=경인로 302)"})
                return
            self._send(200, _refine(q))
        except Exception as e:
            self._send(500, {"ok": False, "error": f"{type(e).__name__}: {e}"})

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8") if length else "{}"
            q = (json.loads(body).get("q") or "").strip()
            if not q:
                self._send(400, {"ok": False, "error": "q 필요"})
                return
            self._send(200, _refine(q))
        except Exception as e:
            self._send(500, {"ok": False, "error": f"{type(e).__name__}: {e}"})
