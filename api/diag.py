"""
api/diag.py — 시스템 진단 엔드포인트

각 구성요소(주소정제 juso / 공동주택 VWorld / 오피스텔 DB)가
실제로 동작하는지 점검해 어디서 막혔는지 한눈에 보여준다.

호출:  GET /api/diag
       GET /api/diag?pnu=1168010100108080000   (특정 PNU로 VWorld 실호출 테스트)

★ 보안: 키 값 자체는 절대 노출하지 않는다. "설정됨/미설정"과 앞 4자리 마스킹만.
"""

import os
import sys
import json
import datetime
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _mask(v):
    """키 마스킹: 설정 여부 + 길이 + 앞 4자만."""
    if not v:
        return {"set": False}
    return {"set": True, "length": len(v), "preview": v[:4] + "…"}


def _check_juso():
    """juso 키로 실제 주소 1건을 정제해본다."""
    out = {"name": "주소정제(juso)", "ok": False, "detail": ""}
    key = os.environ.get("JUSO_API_KEY", "").strip()
    out["key"] = _mask(key)
    if not key:
        out["detail"] = "JUSO_API_KEY 미설정"
        return out
    try:
        from jeonse_pnu.providers import geocode_juso
        r = geocode_juso("서울 강서구 화곡동 504-32", key=key)
        if r.ok and r.parts:
            out["ok"] = True
            out["detail"] = f"정제 성공 → PNU {r.parts.to_pnu()}"
        else:
            out["detail"] = "정제 실패: " + "; ".join(r.warnings or ["응답 비정상"])
    except Exception as e:
        out["detail"] = f"예외: {type(e).__name__}: {e}"
    return out


def _check_vworld(pnu):
    """VWorld 키로 (1)주소검색 API (2)공동주택가격 API 각각 호출해 원인을 가른다."""
    import urllib.parse
    import urllib.request

    out = {"name": "공동주택공시가(VWorld)", "ok": False, "detail": ""}
    key = os.environ.get("VWORLD_API_KEY", "").strip()
    domain = os.environ.get("VWORLD_DOMAIN", "").strip()
    out["key"] = _mask(key)
    out["domain"] = {"set": bool(domain), "value": domain or "(없음 - 도메인 미등록 키)"}
    if not key:
        out["detail"] = "VWORLD_API_KEY 미설정"
        return out

    def _get(url):
        req = urllib.request.Request(url, headers={"User-Agent": "ltvcheck-diag"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            return resp.read().decode("utf-8", "replace")

    # (1) 기본 주소검색 API — 키 자체가 유효한지(대부분의 키에 열려있음)
    probe = {"service": "address", "request": "getcoord", "crs": "epsg:4326",
             "address": "서울특별시 강서구 화곡동 504-32", "format": "json", "type": "PARCEL",
             "key": key}
    if domain:
        probe["domain"] = domain
    addr_url = "https://api.vworld.kr/req/address?" + urllib.parse.urlencode(probe)
    try:
        raw = _get(addr_url)
        status = None
        try:
            j = json.loads(raw)
            status = j.get("response", {}).get("status")
        except Exception:
            pass
        if status == "OK":
            out["probe_address_api"] = "정상(키 유효)"
            addr_ok = True
        elif status in ("NOT_FOUND", "EMPTY"):
            out["probe_address_api"] = f"키 유효(결과 {status})"
            addr_ok = True
        else:
            # 에러 응답에 INCORRECT_KEY 등이 있는지
            snippet = raw[:120]
            out["probe_address_api"] = f"실패({status or snippet})"
            addr_ok = False
    except Exception as e:
        out["probe_address_api"] = f"예외: {type(e).__name__}"
        addr_ok = None

    # (2) 공동주택가격 데이터 API — 실제 우리가 쓰는 것
    from jeonse_pnu.gongsiga import fetch_price_by_pnu
    this_year = str(datetime.date.today().year)
    r = fetch_price_by_pnu(pnu, this_year, key=key, domain=domain or "")
    if r.ok:
        out["ok"] = True
        out["detail"] = f"조회 성공 → {r.price:,}원 (세대 {r.total_count}건)"
        return out

    w = "; ".join(r.warnings or ["응답 비정상"])
    out["detail"] = f"공동주택 데이터 API 실패: {w}"
    incorrect = any("INCORRECT_KEY" in x for x in (r.warnings or []))

    # 두 결과를 종합해 원인 진단
    if incorrect and addr_ok is True:
        out["diagnosis"] = ("★ 키는 유효(주소검색 API 성공)하나 공동주택가격(ned/data) API만 "
                            "INCORRECT_KEY. → 이 키에 '데이터 API(국가공간정보)' 활용신청이 "
                            "안 됐을 가능성. VWorld 마이페이지에서 해당 키의 활용 API에 "
                            "데이터API/국가중점데이터가 포함됐는지 확인하세요.")
    elif incorrect and addr_ok is False:
        out["diagnosis"] = ("★ 주소검색 API도 실패 → 키 값 자체 또는 도메인 문제. "
                            "키 재확인, 도메인 미등록 키면 VWORLD_DOMAIN 비우기.")
    elif any("INVALID_KEY" in x for x in (r.warnings or [])):
        out["diagnosis"] = "INVALID_KEY = 등록되지 않은 인증키. 키 값을 다시 확인하세요."
    elif any("OVER_REQUEST_LIMIT" in x for x in (r.warnings or [])):
        out["diagnosis"] = "일일 사용량 초과."
    return out


def _check_officetel():
    """오피스텔 DB(Postgres/Turso/로컬 SQLite) 연결 점검."""
    out = {"name": "오피스텔기준시가(DB)", "ok": False, "detail": ""}
    pg = os.environ.get("POSTGRES_URL", "").strip() or os.environ.get("DATABASE_URL", "").strip()
    turso = os.environ.get("TURSO_DATABASE_URL", "").strip()
    token = os.environ.get("TURSO_AUTH_TOKEN", "").strip()
    local = os.environ.get("OFFICETEL_DB_PATH", "").strip()
    out["mode"] = "Postgres" if pg else ("Turso" if turso else ("로컬SQLite" if local else "미설정"))
    out["postgres_url"] = {"set": bool(pg)}
    out["turso_url"] = {"set": bool(turso)}
    out["turso_token"] = {"set": bool(token)}
    if not pg and not turso and not local:
        out["detail"] = "오피스텔 DB 미설정(POSTGRES_URL / TURSO_DATABASE_URL / OFFICETEL_DB_PATH). 연립·다세대는 영향 없음."
        return out
    try:
        from jeonse_pnu.officetel import fetch_officetel_by_pnu
        # 강서 인터시티오피스텔로 연결+조회 테스트
        r = fetch_officetel_by_pnu("1150010300103430032", str(datetime.date.today().year), ho="201")
        if r.ok:
            out["ok"] = True
            out["detail"] = f"조회 성공 → {r.price:,}원"
        elif r.total_count > 0 or r.needs_unit:
            out["ok"] = True
            out["detail"] = f"DB 연결됨(총 {r.total_count}건)"
        else:
            out["detail"] = "DB 연결됐으나 데이터 없음: " + "; ".join(r.warnings or [])
            if any("미설치" in x for x in (r.warnings or [])):
                out["hint"] = "DB 드라이버 미설치 → requirements.txt(psycopg 또는 libsql-client) 확인"
    except Exception as e:
        out["detail"] = f"예외: {type(e).__name__}: {e}"
    return out


def _run(pnu):
    checks = [_check_juso(), _check_vworld(pnu), _check_officetel()]
    all_ok = all(c["ok"] for c in checks[:2])  # 핵심은 juso+vworld
    return {
        "service": "ltvcheck 진단",
        "time": datetime.datetime.now().isoformat(timespec="seconds"),
        "summary": "정상" if all_ok else "일부 점검 필요",
        "test_pnu": pnu,
        "checks": checks,
    }


class handler(BaseHTTPRequestHandler):
    def _send(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            qs = parse_qs(urlparse(self.path).query)
            # 기본 테스트 PNU: 강서 화곡동(연립·다세대 존재 지역)
            pnu = (qs.get("pnu") or ["1150010300105040032"])[0]
            self._send(200, _run(pnu))
        except Exception as e:
            self._send(500, {"ok": False, "error": f"{type(e).__name__}: {e}"})
