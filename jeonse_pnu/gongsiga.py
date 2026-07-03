"""
gongsiga.py — 공동주택 공시가격 실시간 조회 (VWorld NED API)

공식 API: https://api.vworld.kr/ned/data/getApartHousingPriceAttr
  → PNU(+동/호)를 넣으면 그 물건의 공동주택 공시가격을 실시간 반환.
  정적 CSV 적재 없이 API 호출이라 항상 현행값이고 매년 자동 갱신.

[입력 파라미터 — VWorld 공식 명세]
  pnu        (필수) 고유번호 8자리 이상
  stdrYear   (옵션) 기준연도 YYYY  ← 2025/2026 구·신 비교에 사용
  dongNm     (옵션) 동명           ← 빌라 호별 매칭
  hoNm       (옵션) 호명           ← 빌라 호별 매칭
  format     (옵션) xml | json
  numOfRows  (옵션) 검색건수 최대 1000
  pageNo     (옵션) 페이지 번호
  key        (필수) 발급받은 인증키
  domain     (옵션) 키 발급 시 등록한 URL (브라우저 외 호출 시 권장)

[출력 필드 — VWorld 공식 명세]
  pnu, ldCode, ldCodeNm, regstrSeCode, regstrSeCodeNm, mnnmSlno,
  stdrYear, stdrMt, aphusCode, aphusSeCode, aphusSeCodeNm, spclLandNm,
  aphusNm, dongNm, floorNm, hoNm, prvuseAr, pblntfPc, lastUpdtDt
  → pblntfPc = 공시가격(원), 우리가 뽑는 값.

[에러코드 — VWorld 공식 명세]
  PARAM_REQUIRED / INVALID_TYPE / INVALID_RANGE / URL_TYPE (레벨1)
  INVALID_KEY / INCORRECT_KEY / UNAVAILABLE_KEY / OVER_REQUEST_LIMIT (레벨2)
  SYSTEM_ERROR / UNKNOWN_ERROR (레벨3)
  정상 응답은 resultCode 없이 <fields><field>...로 옴.

키는 환경변수 VWORLD_API_KEY / VWORLD_DOMAIN 에서만 읽는다(엔벨롭).
키 없이도 파싱 로직을 검증할 수 있게 HTTP 함수를 주입받는다.
"""

import os
import json
import urllib.request
import urllib.parse
from dataclasses import dataclass, field


VWORLD_NED_URL = "https://api.vworld.kr/ned/data/getApartHousingPriceAttr"

# 응답이 에러일 때 resultCode로 오는 코드들(레벨2 = 키/인증 문제)
_KEY_ERRORS = {
    "INVALID_KEY", "INCORRECT_KEY", "UNAVAILABLE_KEY", "OVER_REQUEST_LIMIT",
}


def _env(name, default=None):
    v = os.environ.get(name, "").strip()
    return v or default


def default_http_get(url, *, timeout=6):
    """실제 HTTP GET (stdlib만). 테스트에선 mock 주입."""
    req = urllib.request.Request(url, headers={"User-Agent": "jeonse-pnu/0.3"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


@dataclass
class UnitPrice:
    """공동주택 한 세대(호)의 공시가격."""
    pnu: str = None
    aphusNm: str = None       # 공동주택명(단지)
    aphusSeCodeNm: str = None  # 아파트/연립/다세대
    dongNm: str = None         # 동명
    floorNm: str = None        # 층명
    hoNm: str = None           # 호명
    prvuseAr: str = None       # 전용면적(㎡)
    price: int = None          # pblntfPc 공시가격(원)
    stdrYear: str = None       # 기준연도
    ldCodeNm: str = None       # 법정동명


@dataclass
class PriceResult:
    year: str = None
    units: list = field(default_factory=list)  # 조회된 세대들
    matched: UnitPrice = None   # 동/호로 특정된 세대(있으면)
    price: int = None           # 확정 공시가격(matched 또는 단일세대만)
    total_count: int = 0
    needs_unit: bool = False    # 여러 세대라 동/호 입력이 필요함
    warnings: list = field(default_factory=list)

    @property
    def ok(self):
        return self.price is not None


def _build_url(pnu, *, year=None, dong=None, ho=None, key=None, domain=None,
               num_rows=1000, page=1, fmt="json"):
    params = {
        "pnu": pnu, "format": fmt,
        "numOfRows": num_rows, "pageNo": page, "key": key,
    }
    if year:
        params["stdrYear"] = str(year)
    if dong:
        params["dongNm"] = dong
    if ho:
        params["hoNm"] = ho
    if domain:  # 빈 문자열/None이면 domain 파라미터를 아예 안 보냄(도메인 미등록 키 대응)
        params["domain"] = domain
    return f"{VWORLD_NED_URL}?{urllib.parse.urlencode(params)}"


import re as _re

def _norm(v):
    """
    동/호 비교용 정규화. 사용자가 숫자만 넣어도 인식되게:
      "제105동" / "105동" / "105" → "105"
      "1403호" / "1403" → "1403"
      "101-1403" / "101동 1403호" 류의 하이픈/구분자 제거
      "B동" / "가동" 등 숫자 없는 동은 한글/영문 그대로(소문자화)
    """
    if v is None:
        return ""
    s = str(v).strip().replace(" ", "")
    # 접두 '제' 및 단위 꼬리 제거
    s = s.lstrip("제").rstrip("호동층")
    # 핵심 숫자(+하이픈/영문 섞인 호수)가 있으면 그것만 사용
    #  - 순수 숫자면 앞 0 제거해 105==0105 매칭
    if s.isdigit():
        return str(int(s))  # "0105" -> "105"
    # 숫자+구분자+숫자(예: 101-1403) → 숫자만 이어붙임
    digits = _re.findall(r"\d+", s)
    if digits:
        # 앞 0 제거해 이어붙임
        return "".join(str(int(d)) for d in digits)
    # 숫자 없음(가동/나동/B동 등) → 소문자 원문
    return s.lower()


def _parse_json(raw):
    """
    VWorld JSON 응답을 파싱한다.
    정상: {"apartHousingPrices": {"totalCount":..,"fields":{"field":[...]}}}
          또는 {"apartHousingPrices": {"field": [...]}} 형태 변형 대응.
    에러: {"apartHousingPrices": {"resultCode":"INCORRECT_KEY","resultMsg":...}}
    반환: (fields_list, total_count, error_code_or_None)
    """
    data = json.loads(raw)
    root = data.get("apartHousingPrices") or data.get("response") or data
    # 에러 응답
    rc = root.get("resultCode")
    if rc:
        return [], 0, rc
    total = int(root.get("totalCount", 0) or 0)
    # fields 위치 변형 대응
    fields = root.get("fields") or root.get("field") or []
    if isinstance(fields, dict):
        fields = fields.get("field", fields)
    if isinstance(fields, dict):
        fields = [fields]
    if not isinstance(fields, list):
        fields = [fields] if fields else []
    return fields, total, None


def _to_unit(f):
    """응답 field 1건 → UnitPrice."""
    price = f.get("pblntfPc")
    try:
        price = int(str(price).replace(",", "")) if price not in (None, "") else None
    except ValueError:
        price = None
    return UnitPrice(
        pnu=f.get("pnu"), aphusNm=f.get("aphusNm"),
        aphusSeCodeNm=f.get("aphusSeCodeNm"),
        dongNm=f.get("dongNm"), floorNm=f.get("floorNm"), hoNm=f.get("hoNm"),
        prvuseAr=f.get("prvuseAr"), price=price, stdrYear=f.get("stdrYear"),
        ldCodeNm=f.get("ldCodeNm"),
    )


def fetch_price_by_pnu(pnu, year=None, *, dong=None, ho=None,
                       http_get=None, key=None, domain=None):
    """
    PNU로 공동주택 공시가격을 조회한다.
    dong/ho가 주어지면 응답 중 동/호가 일치하는 세대로 좁힌다(빌라 호별 매칭).

    반환: PriceResult
    """
    http_get = http_get or default_http_get
    key = key or _env("VWORLD_API_KEY")
    domain = domain if domain is not None else _env("VWORLD_DOMAIN", "")
    res = PriceResult(year=str(year) if year else None)

    if not key:
        res.warnings.append("VWORLD_API_KEY 미설정")
        return res

    # 동/호는 서버 필터링도 가능하지만, 한 PNU 전체를 받아 우리 쪽에서 매칭한다
    # (서버 dongNm/hoNm 표기와 등기부 표기가 미세히 다를 수 있어 안전)
    url = _build_url(pnu, year=year, key=key, domain=domain)
    try:
        raw = http_get(url)
        fields, total, err = _parse_json(raw)
        res.total_count = total or len(fields)
        if err:
            if err in _KEY_ERRORS:
                res.warnings.append(f"인증 오류: {err}")
            else:
                res.warnings.append(f"API 오류: {err}")
            return res
        if not fields:
            res.warnings.append("해당 PNU 공시가격 없음")
            return res

        res.units = [_to_unit(f) for f in fields]

        # 동/호 매칭 (VWorld 응답에 동 표기가 없는 단지가 흔하므로 단계적으로)
        if dong or ho:
            # 1차: 동+호 둘 다 일치(가장 엄격)
            def match(u, use_dong):
                d_ok = (not dong) or (not use_dong) or _norm(u.dongNm) == _norm(dong)
                h_ok = (not ho) or _norm(u.hoNm) == _norm(ho)
                return d_ok and h_ok

            cands = [u for u in res.units if match(u, use_dong=True)]

            # 2차: 동으로 못 좁혔고 VWorld에 동 정보가 비어있으면 → 호로만 매칭
            vworld_has_dong = any(_norm(u.dongNm) for u in res.units)
            if not cands and ho and not vworld_has_dong:
                cands = [u for u in res.units if _norm(u.hoNm) == _norm(ho)]
                if cands:
                    res.warnings.append("공시가 데이터에 동 구분이 없어 호로만 특정")

            if len(cands) == 1:
                res.matched = cands[0]
            elif len(cands) > 1:
                # 호로만 좁혔는데 여러 동에 같은 호 → 동이 꼭 필요
                res.needs_unit = True
                res.warnings.append(f"같은 호가 여러 동에 있음({len(cands)}건) - 동을 입력해야 특정 가능")

        # 값 확정 규칙 (임의 대표세대 금지):
        if res.matched is not None:
            res.price = res.matched.price
        elif res.needs_unit:
            pass  # 위에서 이미 needs_unit 설정
        elif len(res.units) == 1:
            res.price = res.units[0].price
        else:
            res.needs_unit = True  # 동/호 입력 필요 신호
            if dong or ho:
                res.warnings.append(f"동/호 미매칭 - 세대 {len(res.units)}건 중 특정 실패(동·호 확인 필요)")
            else:
                res.warnings.append(f"세대 {len(res.units)}건 - 동·호를 입력해야 특정 가능")
    except Exception as e:
        res.warnings.append(f"공시가격 호출 실패: {type(e).__name__}")
    return res


def fetch_two_years(pnu, *, this_year, last_year, dong=None, ho=None,
                    http_get=None, key=None, domain=None):
    """구·신 2개년 공시가격을 한 번에. 반환: (구, 신) PriceResult 튜플."""
    prev = fetch_price_by_pnu(pnu, last_year, dong=dong, ho=ho,
                              http_get=http_get, key=key, domain=domain)
    cur = fetch_price_by_pnu(pnu, this_year, dong=dong, ho=ho,
                             http_get=http_get, key=key, domain=domain)
    return prev, cur
