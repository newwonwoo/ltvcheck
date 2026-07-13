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
    # 오피스텔 계산근거(㎡당 단가 × 면적). 연립·다세대는 None(총액 직접 제공)
    price_calc: dict = None
    confidence_score: int = 0
    confidence_grade: str = "F"
    needs_manual_check: bool = True
    available_units: list = None  # 여러 세대일 때 존재하는 동·호 목록
    # 명시적 상태코드(프론트가 문자열 grep 대신 이걸로 분기)
    status: str = None
    # 확인단계 [{key, state(PASS|FAIL|SKIP|UNKNOWN), label}]
    checks: list = None
    warnings: list = None

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []
        if self.region_candidates is None:
            self.region_candidates = []
        if self.available_units is None:
            self.available_units = []
        if self.checks is None:
            self.checks = []

    def to_dict(self):
        # 명시적 상태코드·확인단계를 최종 상태에서 파생(프론트 문자열 grep 대체)
        if self.status is None:
            self.status = _resolve_status(self)
        if not self.checks:
            self.checks = _resolve_checks(self)
        return asdict(self)


def _resolve_status(out):
    """최종 상태에서 명시적 상태코드 도출.
    값: SUCCESS / SUCCESS_CURRENT_ONLY / NEEDS_ADDRESS_SELECTION /
        NEEDS_UNIT_SELECTION / NOT_FOUND / SOURCE_ERROR / UNSUPPORTED"""
    w = " ".join(out.warnings or [])
    if "인증" in w or "INCORRECT_KEY" in w or "INVALID_KEY" in w:
        return "SOURCE_ERROR"
    if out.ambiguous and out.region_candidates:
        return "NEEDS_ADDRESS_SELECTION"
    if out.needs_unit:
        return "NEEDS_UNIT_SELECTION"
    if out.ok and out.price_this is not None:
        return "SUCCESS" if out.price_last is not None else "SUCCESS_CURRENT_ONLY"
    if out.property_type and out.is_target is False:
        return "UNSUPPORTED"          # 아파트 등 대상 외
    if out.pnu and out.price_this is None:
        return "NOT_FOUND"            # 주소는 찾았으나 가격 없음
    return "NOT_FOUND"


def _resolve_checks(out):
    """확인단계: PASS/FAIL/SKIP/UNKNOWN. 미입력은 FAIL이 아니라 SKIP."""
    def chk(key, label, state):
        return {"key": key, "label": label, "state": state}
    checks = []
    # 주소 확인
    checks.append(chk("address", "주소 확인",
                      "PASS" if out.pnu else "FAIL"))
    # 세대 확인 — 값이 나왔고 needs_unit이 아니면 세대까지 확정된 것
    if out.needs_unit:
        checks.append(chk("unit", "세대 확인", "FAIL"))
    elif out.price_this is not None:
        checks.append(chk("unit", "세대 확인", "PASS"))
    else:
        checks.append(chk("unit", "세대 확인", "UNKNOWN"))
    # 가격 확인
    checks.append(chk("price", "가격 확인",
                      "PASS" if out.price_this is not None else "FAIL"))
    # 전년도 비교 — 비교값 있으면 PASS, 없으면(세대 미확인 등) UNKNOWN
    if out.price_last is not None:
        checks.append(chk("compare", "전년도 비교", "PASS"))
    elif out.price_this is not None:
        checks.append(chk("compare", "전년도 비교", "UNKNOWN"))
    else:
        checks.append(chk("compare", "전년도 비교", "SKIP"))
    # 등기 교차확인 — 등기고유번호 입력 시에만. 아니면 SKIP(미수행, 실패 아님)
    if out.input_type == "등기고유번호":
        checks.append(chk("registry", "등기 교차확인", "PASS"))
    else:
        checks.append(chk("registry", "등기 교차확인", "SKIP"))
    return checks


def _unit_list(units, *, dong_attr="dongNm", ho_attr="hoNm"):
    """
    VWorld/오피스텔 세대 목록을 프론트 표시용으로 정리.
    반환: [{"dong": "101", "ho": "1403"}...] 동→호 순 정렬, 중복 제거.
    동 정보가 비어있으면 dong은 빈 문자열(호만 목록).
    """
    seen = set()
    out = []
    for u in units or []:
        d = (getattr(u, dong_attr, None) or "").strip()
        h = (getattr(u, ho_attr, None) or "").strip()
        key = (d, h)
        if key in seen:
            continue
        seen.add(key)
        out.append({"dong": d, "ho": h})

    def sort_key(x):
        # 숫자 우선 정렬(101 < 102 < 1403), 숫자 아니면 문자열
        def num(s):
            import re as _r
            m = _r.findall(r"\d+", s)
            return (0, int(m[0])) if m else (1, s)
        return (num(x["dong"]), num(x["ho"]))

    out.sort(key=sort_key)
    return out


def _strip_unit_tail(text, dong, ho):
    """
    건물명 검색용: 사용자가 별도 필드로 넣은 동·호가 원문 끝에 붙어있으면 제거.
    (예: 프론트가 q에 '구로구 진오피스텔', dong/ho에 '105'/'201'을 넣었는데
     원문에 그게 안 섞였으면 그대로, 섞였으면 떼어 건물명만 남긴다.)
    """
    s = " ".join((text or "").split())
    for v in (ho, dong):
        if not v:
            continue
        v = str(v).strip()
        # "105", "105동", "201호" 형태를 끝에서 제거
        for suf in (v + "호", v + "동", v):
            if s.endswith(suf):
                s = s[: -len(suf)].strip()
                break
    return s


def lookup(text, *, this_year, last_year,
           dong=None, ho=None,
           registry_lookup=None,
           juso_http=None, kakao_http=None, gongsiga_http=None,
           juso_key=None, kakao_key=None, gongsiga_key=None,
           gongsiga_domain=None,
           officetel_conn=None, officetel_db_path=None):
    """
    입력 문자열 하나로 구·신 공시가와 신뢰도를 반환한다.

    this_year/last_year: 비교할 두 공시연도(예: "2026","2025")
    dong/ho            : 명시적 동·호(입력칸에서 분리해 받은 값). 주어지면 파싱보다 우선.
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

    # 동·호: 명시적 인자(입력칸) 우선, 없으면 파싱 결과 사용.
    #   (프론트가 동·호를 별도 필드로 넘기면 문자열 파싱에 의존하지 않음)
    out.dong = (str(dong).strip() if dong else None) or parsed.건물동
    out.ho = (str(ho).strip() if ho else None) or parsed.호
    out.warnings.extend(parsed.경고)

    # 2) 정제: juso로 PNU 4요소 확보
    #   - 지번(본번)이 있으면 파서의 검색질의 사용(불필요한 상세 제거)
    #   - 지번이 없으면(건물명만 입력한 경우) 원문을 그대로 넘긴다.
    #     juso는 건물명 검색을 지원하므로 "구로구 진오피스텔" 같은 입력도 정제됨.
    #     (파서 검색질의는 건물명을 지번으로 못 봐 떨궈버리므로 원문이 정확)
    if parsed.본번:
        query = parsed.검색질의 or routed.원본
    else:
        # 동·호 상세만 떼고 건물명은 유지한 채 원문 사용
        query = _strip_unit_tail(routed.원본, out.dong, out.ho) or routed.원본
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
                             has_ho=bool(out.ho), warnings=out.warnings)
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
        ho_matched = apt_cur.matched is not None  # 최신 연도에서 입력 호가 실제 매칭된 경우만

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
        out.available_units = _unit_list(apt_cur.units)
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
        ho_matched = ofc_cur.matched is not None  # 최신 연도 매칭만
        # 계산근거: 총액 = ㎡당 단가 × (전용+공유). 사용자에게 식을 보여주기 위함
        if chosen is not None:
            out.price_calc = {
                "unit_price_per_m2": chosen.price,
                "exclusive_area_m2": chosen.prvuse,
                "share_area_m2": chosen.share,
                "total_area_m2": chosen.calc_area,
                "formula": "㎡당 기준시가 × (전용면적 + 공유면적)",
                "source": "NTS",
            }
    elif ofc_cur.needs_unit:
        # 오피스텔 여러 호인데 호 미특정 → 값 없이 호 요구
        prev, cur = ofc_prev, ofc_cur
        rep = ofc_cur.units[0] if ofc_cur.units else None
        out.property_type = "오피스텔"
        out.is_target = True
        out.building_name = getattr(rep, "building", None)
        out.needs_unit = True
        out.available_units = _unit_list(ofc_cur.units, dong_attr="dong", ho_attr="ho")
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
    #    has_jibun은 '정제 결과(geo.parts)에 본번이 있는가'로 판단한다.
    #    (도로명주소는 등기부 파싱(parsed.본번)엔 지번이 없지만, juso 정제로 지번이 확보됨)
    refined_bonbun = bool(getattr(geo.parts, "본번", None)) or bool(out.pnu)
    c = score_confidence(
        refine_tier=geo.tier,
        has_jibun=refined_bonbun,
        # 호 확인은 '원천 데이터와 실제 매칭'된 경우만. 입력만 했다고 가산하지 않음.
        has_ho=ho_matched,
        registry_cross_checked=(routed.종류 == "등기고유번호"),
        warnings=out.warnings,
    )
    out.confidence_score, out.confidence_grade = c.score, c.grade
    out.needs_manual_check = c.needs_manual_check
    return out
