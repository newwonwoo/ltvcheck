"""
api/vworld-diag.py — VWorld 인증키 전용 정밀 진단

INCORRECT_KEY의 진짜 원인을 격리하기 위해, 같은 키로 여러 VWorld API를
각도별로 실제 호출하고 원시 응답까지 보여준다.

테스트 항목:
  1) 주소검색 API (req/address)        — 키 자체가 유효한가? (기본 API)
  2) 공동주택가격 (ned/data, 도메인 없이) — 우리가 쓰는 것
  3) 공동주택가격 (ned/data, 도메인 붙여) — 도메인 유무로 결과가 바뀌나?
  4) 개별공시지가 (ned/data, 다른 데이터 API) — 데이터 API 전체가 막힌 건가 이것만인가?

각 호출의 status/resultCode/원시응답 일부를 그대로 노출해 원인을 확정한다.

호출: GET /api/vworld-diag        (기본 PNU로)
      GET /api/vworld-diag?pnu=1156010100106470000

★ 키 값은 마스킹. 응답 일부만 노출(민감정보 아님, VWorld 공개 데이터).
"""

import os
import json
import datetime
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs


def _mask(v):
    if not v:
        return {"set": False}
    return {"set": True, "length": len(v), "preview": v[:4] + "…"}


def _http_get(url, timeout=8):
    req = urllib.request.Request(url, headers={"User-Agent": "ltvcheck-vworld-diag"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return None, f"__EXC__:{type(e).__name__}:{e}"


def _summarize(raw):
    """VWorld 응답에서 상태/에러코드/메시지를 뽑고 원시 일부를 남긴다."""
    if raw.startswith("__EXC__:"):
        return {"outcome": "예외", "raw": raw[:200]}
    info = {"raw": raw[:280]}
    try:
        j = json.loads(raw)
    except Exception:
        info["outcome"] = "JSON아님(HTML/텍스트 응답)"
        return info
    # 주소검색 형태
    resp = j.get("response")
    if isinstance(resp, dict) and "status" in resp:
        info["status"] = resp.get("status")
        info["outcome"] = "정상" if resp.get("status") == "OK" else f"status={resp.get('status')}"
        if resp.get("error"):
            info["error"] = resp.get("error")
        return info
    # ned/data 형태
    root = j.get("apartHousingPrices") or j.get("indvdLandPrices") or j
    rc = root.get("resultCode") if isinstance(root, dict) else None
    if rc:
        info["resultCode"] = rc
        info["resultMsg"] = root.get("resultMsg")
        info["outcome"] = f"에러코드 {rc}"
    else:
        total = root.get("totalCount") if isinstance(root, dict) else None
        info["totalCount"] = total
        info["outcome"] = "정상(데이터 있음)" if total else "정상(데이터 0건)"
    return info


def _run(pnu):
    key = os.environ.get("VWORLD_API_KEY", "").strip()
    domain = os.environ.get("VWORLD_DOMAIN", "").strip()
    year = str(datetime.date.today().year)

    result = {
        "service": "VWorld 정밀 진단",
        "time": datetime.datetime.now().isoformat(timespec="seconds"),
        "key": _mask(key),
        "domain_env": {"set": bool(domain), "value": domain or "(미설정)"},
        "test_pnu": pnu,
        "tests": [],
        "conclusion": "",
    }
    if not key:
        result["conclusion"] = "VWORLD_API_KEY 미설정 — 환경변수부터 설정하세요."
        return result

    tests = []

    # 1) 주소검색 API (키 기본 유효성)
    p1 = {"service": "address", "request": "getcoord", "crs": "epsg:4326",
          "address": "서울특별시 강서구 화곡동 504-32", "format": "json",
          "type": "PARCEL", "key": key}
    if domain:
        p1["domain"] = domain
    s1, r1 = _http_get("https://api.vworld.kr/req/address?" + urllib.parse.urlencode(p1))
    t1 = {"name": "1. 주소검색 API (req/address)", "http": s1}
    t1.update(_summarize(r1))
    tests.append(t1)

    # 2) 공동주택가격 — domain 3종을 실제로 때려서 뭐가 통과하는지 확인
    #    (개발키는 등록 서비스URL을 domain으로 넣어야 통과하는 경우가 있음)
    domain_variants = [
        ("도메인 없이", None),
        ("domain=ltvcheck.vercel.app", "ltvcheck.vercel.app"),
        ("domain=https://ltvcheck.vercel.app", "https://ltvcheck.vercel.app"),
    ]
    if domain:
        domain_variants.append((f"domain={domain} (환경변수)", domain))

    for label, dv in domain_variants:
        pv = {"pnu": pnu, "format": "json", "numOfRows": 10, "pageNo": 1,
              "stdrYear": year, "key": key}
        if dv:
            pv["domain"] = dv
        s, r = _http_get("https://api.vworld.kr/ned/data/getApartHousingPriceAttr?" + urllib.parse.urlencode(pv))
        t = {"name": f"2. 공동주택가격 [{label}]", "http": s}
        t.update(_summarize(r))
        tests.append(t)

    # 4) 개별공시지가 (다른 데이터 API) — 데이터 API 전체 문제인지 격리
    p4 = {"pnu": pnu, "format": "json", "numOfRows": 5, "pageNo": 1,
          "stdrYear": year, "key": key}
    s4, r4 = _http_get("https://api.vworld.kr/ned/data/getIndvdLandPriceAttr?" + urllib.parse.urlencode(p4))
    t4 = {"name": "4. 개별공시지가 (다른 데이터 API)", "http": s4}
    t4.update(_summarize(r4))
    tests.append(t4)

    result["tests"] = tests

    # ── 종합 판정 (인덱스 대신 이름으로 찾아 도메인 유무에 무관) ──
    def find(kw):
        for t in tests:
            if kw in t["name"]:
                return t
        return None
    def is_ok(t):
        return t is not None and "정상" in t.get("outcome", "")
    def is_incorrect(t):
        return t is not None and "INCORRECT_KEY" in json.dumps(t, ensure_ascii=False)

    t_addr = find("주소검색")
    t_land = find("개별공시지가")
    apt_tests = [t for t in tests if "공동주택가격" in t["name"]]

    addr_ok = is_ok(t_addr)
    land_ok = is_ok(t_land)
    land_incorrect = is_incorrect(t_land)

    # 공동주택 domain 변형 중 통과한 게 있나?
    passed = next((t for t in apt_tests if "정상" in t.get("outcome", "")), None)
    all_apt_incorrect = all(is_incorrect(t) for t in apt_tests) if apt_tests else False

    if passed:
        # 통과한 domain 값을 추출해 추천
        name = passed["name"]
        if "도메인 없이" in name:
            rec = "VWORLD_DOMAIN을 비워두세요(도메인 파라미터 안 보냄)."
        elif "https://" in name:
            rec = "VWORLD_DOMAIN = https://ltvcheck.vercel.app 로 설정하세요."
        else:
            rec = "VWORLD_DOMAIN = ltvcheck.vercel.app 로 설정하세요."
        result["conclusion"] = f"✅ 공동주택가격 API 통과 조합 발견! [{name}] → {rec} 그 후 재배포."
    elif all_apt_incorrect and addr_ok and land_incorrect:
        result["conclusion"] = (
            "★ 주소검색은 되나 모든 데이터 API가 INCORRECT_KEY. 활용API는 켜져 있으므로 "
            "'개발키'라서 서버호출이 막혔을 가능성. → VWorld에서 '운영키 신청'으로 운영키를 "
            "발급받아 VWORLD_API_KEY를 교체하세요. (개발키는 등록 도메인/브라우저 호출 전제)")
    elif all_apt_incorrect and addr_ok and land_ok:
        result["conclusion"] = (
            "★ 개별공시지가는 되는데 공동주택가격만 모든 domain 조합에서 INCORRECT_KEY. "
            "→ 공동주택가격 API 활용 승인/상태를 VWorld에서 재확인.")
    elif not addr_ok:
        result["conclusion"] = (
            "★ 주소검색 API조차 실패 → 키 값 자체 또는 도메인 불일치. 키 재확인.")
    else:
        result["conclusion"] = "혼합 결과 — 각 test의 outcome/raw를 확인하세요."

    return result


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
            pnu = (qs.get("pnu") or ["1150010300105040032"])[0]
            self._send(200, _run(pnu))
        except Exception as e:
            self._send(500, {"ok": False, "error": f"{type(e).__name__}: {e}"})
