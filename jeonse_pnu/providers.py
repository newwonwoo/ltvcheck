"""
providers.py — 주소 정제 어댑터 (juso 1차 → 카카오 2차 폴백)

우리 연구의 결론을 코드로 옮긴 부분이에요. 핵심 아이디어:

  "도로명주소만으로는 PNU를 못 만든다. 하지만 juso/카카오 API가 응답에
   지번 4요소(법정동코드 + 산여부 + 본번 + 부번)를 함께 주므로, 그걸 받아
   PNU를 직접 조립하면 된다."

그래서 이 모듈은 주소를 넣으면 'PNU 4요소가 담긴 PnuParts'를 돌려줘요.
PNU 조립 자체는 pnu.build_pnu()가 하고, 여기선 '재료를 구해오는' 일만 합니다.

설계 포인트(우리가 찾은 정제 패치 반영):
  - juso의 mtYn(0/1)과 카카오의 mountain_yn(Y/N)을 PnuParts에 그대로 담고,
    PNU 조립 단계에서 규약(1/2)으로 변환 (pnu.normalize_mountain_flag).
  - 본번/부번은 문자열로 받고 조립 단계에서 zfill(4).
  - 1차(juso)가 실패하면 2차(카카오)로 폴백, 둘 다 결과를 tier로 표시.
  - 키는 절대 코드에 안 박고 환경변수에서만 읽음(엔벨롭).

키 없이도 파싱 로직을 테스트할 수 있게, 실제 HTTP 호출 함수를 '주입'받습니다.
(http_get 인자에 mock을 넣으면 네트워크 없이 검증 가능)
"""

import os
import json
import urllib.request
import urllib.parse
from dataclasses import dataclass

from .pnu import PnuParts


# ── 환경변수에서만 키를 읽는다 (코드/클라이언트에 절대 노출 안 함) ──────────
def _env(name):
    v = os.environ.get(name, "").strip()
    return v or None


def default_http_get(url, *, timeout=5):
    """실제 HTTP GET (stdlib만 사용). 테스트에선 이 자리에 mock을 주입."""
    req = urllib.request.Request(url, headers={"User-Agent": "jeonse-pnu/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def default_http_get_with_headers(url, headers, *, timeout=5):
    """헤더가 필요한 GET(카카오 Authorization 등)."""
    req = urllib.request.Request(url, headers={**headers, "User-Agent": "jeonse-pnu/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


@dataclass
class GeocodeResult:
    parts: PnuParts = None      # PNU 4요소 (성공 시)
    tier: int = 0               # 1=juso, 2=카카오, 0=실패
    provider: str = None
    refined_address: str = None  # 정제된 표준 지번주소
    road_address: str = None     # 정제된 도로명주소(juso 제공 시)
    is_apartment: bool = None    # 공동주택 여부(juso 제공 시)
    candidates: int = 0          # 매칭 후보 수(다중매칭 감지용)
    region_candidates: list = None  # 동명이지: 행정구역이 다른 후보들 [{시도,시군구,읍면동,pnu_prefix,대표주소}]
    ambiguous: bool = False      # 행정구역 모호(상위 행정구역 입력 필요)
    warnings: list = None

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []
        if self.region_candidates is None:
            self.region_candidates = []

    @property
    def ok(self):
        return self.parts is not None


# ── 1차: 행안부 juso 검색 API ──────────────────────────────────────────────
JUSO_URL = "https://business.juso.go.kr/addrlink/addrLinkApi.do"


def _parts_from_juso(item):
    """juso 응답 1건 → PnuParts."""
    return PnuParts(
        beopjeongdong_code=item.get("admCd"),
        bonbun=item.get("lnbrMnnm"),
        bubun=item.get("lnbrSlno"),
        mountain=item.get("mtYn", "0"),
        mountain_source="juso",
    )


def _group_by_region(juso_list):
    """
    동명이지(同名異地) 처리: juso 후보들을 행정구역(법정동코드 10자리=PNU prefix)으로 묶는다.
    같은 법정동이면 도로명/지번 표현이 달라도 1개 지역으로 압축.
    진짜 다른 시군구(예: 중앙동이 여러 시)는 각각 살린다.
    반환: 지역 후보 리스트 [{시도,시군구,읍면동,pnu_prefix,대표주소,_item}]
    """
    groups = {}
    for it in juso_list:
        admcd = it.get("admCd") or ""
        prefix = admcd[:10]  # 시도2+시군구3+읍면동3+리2
        if not prefix:
            continue
        if prefix not in groups:
            groups[prefix] = {
                "시도": it.get("siNm"),
                "시군구": it.get("sggNm"),
                "읍면동": it.get("emdNm"),
                "pnu_prefix": prefix,
                "대표주소": it.get("roadAddr") or it.get("jibunAddr"),
                "우편번호": it.get("zipNo"),
                "_item": it,  # 대표 1건(번지까지 확정용)
            }
    return list(groups.values())


def geocode_juso(query, *, http_get=None, key=None):
    """
    juso 검색 API로 주소를 정제하고 PNU 4요소를 추출한다.
    응답의 admCd(법정동코드10), mtYn(0/1), lnbrMnnm(본번), lnbrSlno(부번)을 사용.

    동명이지 정책(설계 반영): 후보가 여러 행정구역에 걸치면 1순위로 단정하지 않고
    region_candidates로 전부 반환하고 ambiguous=True로 표시(상위 행정구역 입력 유도).
    같은 법정동 내 복수 표현은 prefix로 묶어 자동 압축.
    """
    http_get = http_get or default_http_get
    key = key or _env("JUSO_API_KEY")
    res = GeocodeResult(provider="juso")
    if not key:
        res.warnings.append("JUSO_API_KEY 미설정")
        return res

    params = urllib.parse.urlencode({
        "confmKey": key, "currentPage": 1, "countPerPage": 10,
        "keyword": query, "resultType": "json",
    })
    try:
        raw = http_get(f"{JUSO_URL}?{params}")
        data = json.loads(raw)
        common = data.get("results", {}).get("common", {})
        if common.get("errorCode") not in ("0", 0, None):
            res.warnings.append(f"juso 오류: {common.get('errorMessage')}")
            return res
        juso_list = data.get("results", {}).get("juso") or []
        res.candidates = len(juso_list)
        if not juso_list:
            res.warnings.append("juso 결과 없음")
            return res

        # 동명이지: 행정구역(법정동 prefix)으로 묶기
        regions = _group_by_region(juso_list)
        res.region_candidates = [{k: v for k, v in r.items() if k != "_item"} for r in regions]

        if len(regions) > 1:
            # 여러 행정구역에 걸침 → 단정 금지, 상위 행정구역 입력 유도
            res.ambiguous = True
            names = " / ".join(
                f"{r['시도']} {r['시군구']} {r['읍면동']}" for r in regions[:5])
            res.warnings.append(f"동명이지 {len(regions)}곳 매칭({names}) - 상위 행정구역 필요")
            return res

        # 단일 행정구역 → 확정
        top = regions[0]["_item"]
        res.parts = _parts_from_juso(top)
        res.refined_address = top.get("jibunAddr") or top.get("roadAddr")
        res.road_address = top.get("roadAddr")
        res.is_apartment = (top.get("bdKdcd") == "1")  # 1=공동주택
        res.tier = 1
        if top.get("hstryYn") == "1":
            res.warnings.append("변동이력 있는 주소(과거주소 가능)")
    except Exception as e:  # 네트워크/파싱 실패 -> 폴백으로 넘어가게
        res.warnings.append(f"juso 호출 실패: {type(e).__name__}")
    return res


# ── 2차 폴백: 카카오 로컬 주소검색 ─────────────────────────────────────────
KAKAO_URL = "https://dapi.kakao.com/v2/local/search/address.json"


def geocode_kakao(query, *, http_get=None, key=None):
    """
    카카오 로컬 주소검색으로 폴백. 응답 address 객체의
    b_code(법정동코드10), mountain_yn(Y/N), main_address_no(본번), sub_address_no(부번) 사용.
    """
    http_get = http_get or default_http_get_with_headers
    key = key or _env("KAKAO_REST_KEY")
    res = GeocodeResult(provider="kakao")
    if not key:
        res.warnings.append("KAKAO_REST_KEY 미설정")
        return res

    params = urllib.parse.urlencode({"query": query})
    try:
        raw = http_get(f"{KAKAO_URL}?{params}", {"Authorization": f"KakaoAK {key}"})
        data = json.loads(raw)
        docs = data.get("documents") or []
        res.candidates = len(docs)
        if not docs:
            res.warnings.append("카카오 결과 없음")
            return res
        # 지번주소(address) 우선, 없으면 도로명의 지번 정보 사용
        top = docs[0]
        addr = top.get("address") or {}
        if not addr:
            res.warnings.append("카카오 지번주소 없음")
            return res
        res.parts = PnuParts(
            beopjeongdong_code=addr.get("b_code"),
            bonbun=addr.get("main_address_no"),
            bubun=addr.get("sub_address_no"),
            mountain=addr.get("mountain_yn", "N"),
            mountain_source="kakao",
        )
        res.refined_address = addr.get("address_name")
        res.tier = 2
    except Exception as e:
        res.warnings.append(f"카카오 호출 실패: {type(e).__name__}")
    return res


# ── 오케스트레이터: 캐스케이드 폴백 사다리 (설계 반영) ──────────────────────
import re as _re

# 동/호/층 꼬리 토큰(juso 검색을 방해하는 상세주소)
_DETAIL_TAIL = _re.compile(
    r"\s*(제?\s*\d+\s*동)?\s*(제?\s*[B]?\d+\s*층)?\s*(제?\s*[\dA-Za-z\-]+\s*호)\s*$")


def _strip_detail(query):
    """동·호·층 상세주소를 제거(juso 검색용). 제거본과 제거여부 반환."""
    stripped = _DETAIL_TAIL.sub("", query).strip()
    return stripped, (stripped != query.strip())


def geocode(query, *, juso_http=None, kakao_http=None,
            juso_key=None, kakao_key=None):
    """
    주소를 PNU 4요소로 정제한다. 설계의 캐스케이드 사다리:
      1) 원문 그대로 juso
      2) 동/호 제거본으로 juso 재검색
      3) 카카오 키워드 폴백(건물명·아파트명)
      4) 점진적 절삭: 뒤 토큰부터 떼며 juso 재검색
    동명이지(ambiguous)면 즉시 반환해 상위 행정구역 입력을 유도(잘못 단정 방지).
    반환: GeocodeResult
    """
    tried = []

    # 1) 원문 juso
    r = geocode_juso(query, http_get=juso_http, key=juso_key)
    if r.ok or r.ambiguous:
        return r
    tried += r.warnings

    # 2) 동/호 제거본 juso
    stripped, changed = _strip_detail(query)
    if changed and stripped:
        r2 = geocode_juso(stripped, http_get=juso_http, key=juso_key)
        if r2.ok or r2.ambiguous:
            r2.warnings = tried + r2.warnings
            return r2
        tried += r2.warnings

    # 3) 카카오 폴백 (건물명·아파트명 등 juso가 못 잡는 영역)
    r3 = geocode_kakao(query, http_get=kakao_http, key=kakao_key)
    if r3.ok:
        r3.warnings = tried + r3.warnings
        return r3
    tried += r3.warnings

    # 4) 점진적 절삭: 뒤 토큰부터 하나씩 떼며 juso 재검색
    toks = stripped.split()
    for cut in range(1, min(3, len(toks))):  # 최대 2토큰까지만 절삭
        sub = " ".join(toks[:-cut])
        if len(sub) < 4:
            break
        r4 = geocode_juso(sub, http_get=juso_http, key=juso_key)
        if r4.ok or r4.ambiguous:
            r4.warnings = tried + [f"절삭검색 적용('{sub}')"] + r4.warnings
            return r4

    # 전부 실패
    r.warnings = tried + ["정제 실패 - 모든 폴백 소진"]
    return r
