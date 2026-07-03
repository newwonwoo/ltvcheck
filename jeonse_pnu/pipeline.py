"""
pipeline.py — 전체 정제 파이프라인 (입력 → 공시가 + 신뢰도)

지금까지 만든 조각들을 하나로 엮어요:

  입력(등기번호/등기부주소/일반주소)
    → route_input()        무엇이 들어왔나 분기
    → (등기부 주소면) 지번주소 + 동/호 추출
    → geocode()            juso→카카오로 PNU 4요소 확보
    → build_pnu()          PNU 19자리 조립
    → fetch_two_years()    구·신 공시가 실시간 조회
    → score_confidence()   신뢰도 등급

이 함수 하나가 Vercel 서버리스 함수의 '본체'가 됩니다.
HTTP 호출 함수들을 인자로 주입할 수 있어 키 없이 테스트 가능.
"""

from dataclasses import dataclass, asdict

from .inputs import route_input
from .pnu import PnuError
from .providers import geocode
from .gongsiga import fetch_two_years as fetch_apart_two_years
from .officetel import fetch_two_years as fetch_officetel_two_years
from .confidence import score_confidence


@dataclass
class LookupResult:
    ok: bool = False
    input_type: str = None
    refined_address: str = None
    pnu: str = None
    dong: str = None
    ho: str = None
    property_type: str = None  # "아파트"|"연립"|"다세대"|"오피스텔"
    is_target: bool = True     # 이 서비스 대상 여부(아파트면 False)
    needs_unit: bool = False   # 여러 세대라 동·호 입력이 필요함
    building_name: str = None  # 단지/건물명
    ambiguous: bool = False         # 동명이지(여러 행정구역) 여부
    region_candidates: list = None  # 동명이지 후보 [{시도,시군구,읍면동,pnu_prefix,대표주소}]
    price_last: int = None     # 구 공시가/기준시가(작년)
    price_this: int = None     # 신 공시가/기준시가(올해)
    price_delta: int = None
    confidence_score: int = 0
    confidence_grade: str = "F"
    needs_manual_check: bool = True
    warnings: list = None

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []
        if self.region_candidates is None:
            self.region_candidates = []

    def to_dict(self):
        return asdict(self)


def lookup(text, *, this_year, last_year,
           registry_lookup=None,
           juso_http=None, kakao_http=None, gongsiga_http=None,
           juso_key=None, kakao_key=None, gongsiga_key=None,
           gongsiga_domain=None,
           officetel_conn=None, officetel_db_path=None):
    """
    입력 문자열 하나로 구·신 공시가와 신뢰도를 반환한다.

    this_year/last_year: 비교할 두 공시연도(예: "2026","2025")
    registry_lookup    : 등기고유번호 → 주소 콜백(보증 DB 조회)
    *_http / *_key     : 테스트/운영용 주입(없으면 환경변수 사용)
    """
    out = LookupResult(input_type=None)

    # 1) 입력 분기
    routed = route_input(text, registry_lookup=registry_lookup)
    out.input_type = routed.종류

    if routed.needs_address_lookup:
        out.warnings.append("등기고유번호만 입력됨 - 보증DB 주소조회 필요")
        return out

    parsed = routed.parsed
    if parsed is None:
        out.warnings.append("주소 파싱 실패")
        return out

    # 빌라는 보통 단일 동이라 동(건물 101동 등)은 비워두고 호만 매칭에 사용.
    # (아파트 단지처럼 동이 여러 개면 추후 parsed에서 동 추출 확장)
    out.dong = None
    out.ho = parsed.호
    out.warnings.extend(parsed.경고)

    # 2) 정제: 검색질의로 PNU 4요소 확보 (도로명이면 juso가 지번을 채움)
    query = parsed.검색질의 or routed.원본
    geo = geocode(query, juso_http=juso_http, kakao_http=kakao_http,
                  juso_key=juso_key, kakao_key=kakao_key)
    out.warnings.extend(geo.warnings)

    if not geo.ok:
        # 동명이지(여러 행정구역) → 정직하게 상위 행정구역 요구 + 후보 전달
        if getattr(geo, "ambiguous", False):
            out.ambiguous = True
            out.region_candidates = geo.region_candidates
            out.warnings.append("여러 지역에 같은 동명 - 시/도·시군구를 함께 입력하세요")
        # 정제 실패 → 신뢰도 F로 마감
        c = score_confidence(refine_tier=0, has_jibun=bool(parsed.본번),
                             has_ho=bool(parsed.호), warnings=out.warnings)
        out.confidence_score, out.confidence_grade = c.score, c.grade
        out.needs_manual_check = c.needs_manual_check
        return out

    out.refined_address = geo.refined_address

    # 3) PNU 조립
    try:
        pnu = geo.parts.to_pnu()
        out.pnu = pnu
    except PnuError as e:
        out.warnings.append(f"PNU 조립 실패: {e}")
        return out

    # 4) 구·신 공시가 조회 — 두 경로 모두 시도해 값이 나오는 쪽 채택
    #    (한 물건은 연립·다세대[VWorld API] 또는 오피스텔[국세청 DB] 중 하나에만 존재)
    ho_matched = False

    # 4-a) 연립·다세대: VWorld 공동주택가격 실시간 API
    apt_prev, apt_cur = fetch_apart_two_years(
        pnu, this_year=this_year, last_year=last_year,
        dong=out.dong, ho=out.ho,
        http_get=gongsiga_http, key=gongsiga_key, domain=gongsiga_domain,
    )

    # 4-b) 오피스텔: 국세청 기준시가 DB
    ofc_prev, ofc_cur = fetch_officetel_two_years(
        pnu, this_year=this_year, last_year=last_year, ho=out.ho,
        conn=officetel_conn, db_path=officetel_db_path,
    )

    # 채택: 신(this_year) 값이 나온 경로를 우선. 둘 다면 공동주택 우선.
    if apt_cur.price is not None:
        prev, cur = apt_prev, apt_cur
        chosen = apt_cur.matched or (apt_cur.units[0] if apt_cur.units else None)
        out.building_name = getattr(chosen, "aphusNm", None)
        ho_matched = (apt_cur.matched is not None) or (apt_prev.matched is not None)

        # VWorld 응답의 공동주택구분(아파트/연립/다세대)으로 실제 종류 판정
        se = (getattr(chosen, "aphusSeCodeNm", None) or "").strip()
        out.property_type = se or "공동주택"
        out.is_target = ("아파트" not in se)
    elif apt_cur.needs_unit:
        # 여러 세대인데 동·호로 특정 못 함 → 값 내지 않고 동·호 요구
        prev, cur = apt_prev, apt_cur
        rep = apt_cur.units[0] if apt_cur.units else None
        out.building_name = getattr(rep, "aphusNm", None)
        se = (getattr(rep, "aphusSeCodeNm", None) or "").strip()
        out.property_type = se or "공동주택"
        out.is_target = ("아파트" not in se)
        out.needs_unit = True
        out.warnings.extend(apt_cur.warnings)
        # 신뢰도만 매겨 조기 반환(값 없음 = 임의값 안 냄)
        c = score_confidence(refine_tier=geo.tier, has_jibun=bool(parsed.본번),
                             has_ho=False, warnings=out.warnings)
        out.confidence_score, out.confidence_grade = c.score, c.grade
        out.needs_manual_check = c.needs_manual_check
        return out
    elif ofc_cur.price is not None:
        out.property_type = "오피스텔"
        out.is_target = True
        prev, cur = ofc_prev, ofc_cur
        chosen = ofc_cur.matched or (ofc_cur.units[0] if ofc_cur.units else None)
        out.building_name = getattr(chosen, "building", None)
        ho_matched = (ofc_cur.matched is not None) or (ofc_prev.matched is not None)
    elif ofc_cur.needs_unit:
        # 오피스텔 여러 호인데 호 미특정 → 값 없이 호 요구
        prev, cur = ofc_prev, ofc_cur
        rep = ofc_cur.units[0] if ofc_cur.units else None
        out.property_type = "오피스텔"
        out.is_target = True
        out.building_name = getattr(rep, "building", None)
        out.needs_unit = True
        out.warnings.extend(ofc_cur.warnings)
        c = score_confidence(refine_tier=geo.tier, has_jibun=bool(parsed.본번),
                             has_ho=False, warnings=out.warnings)
        out.confidence_score, out.confidence_grade = c.score, c.grade
        out.needs_manual_check = c.needs_manual_check
        return out
    else:
        # 둘 다 없음 — 경고만 모아 전달
        prev, cur = apt_prev, apt_cur
        out.warnings.append("공시가격 미확인(공동주택·오피스텔 모두 없음)")

    out.warnings.extend(prev.warnings + cur.warnings)
    out.price_last = prev.price
    out.price_this = cur.price
    if prev.price is not None and cur.price is not None:
        out.price_delta = cur.price - prev.price
        out.ok = True
    elif cur.price is not None:
        # 신 공시가만 있는 경우(예: 오피스텔 구년도 파일 미보유)도 표시는 가능
        out.ok = True
        out.warnings.append("구 공시가 없음 - 변동 비교 불가(현재값만)")

    # 5) 신뢰도
    c = score_confidence(
        refine_tier=geo.tier,
        has_jibun=bool(parsed.본번),
        has_ho=ho_matched or bool(parsed.호),
        registry_cross_checked=(routed.종류 == "등기고유번호"),
        warnings=out.warnings,
    )
    out.confidence_score, out.confidence_grade = c.score, c.grade
    out.needs_manual_check = c.needs_manual_check
    return out
