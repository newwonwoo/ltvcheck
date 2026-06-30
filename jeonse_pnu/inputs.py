"""
inputs.py — 입력 3종 판별 및 분기

사용자(또는 보증 레코드)가 주는 입력은 세 가지예요:
  1) 등기고유번호(부동산고유번호) 14자리  예) "1146-1996-072481"
  2) 등기부 소재지번 주소             예) "서울 강서구 화곡동 504-32 정원빌라 제202호"
  3) 일반 주소(도로명 또는 지번)       예) "화곡로 123" / "화곡동 504-32"

이 모듈은 '무엇이 들어왔는지' 먼저 판별하고, 각각 맞는 처리로 보냅니다.

중요(설계서 확인 사항):
  등기고유번호 14자리는 PNU(19자리)와 '별개 체계'라 직접 변환이 안 돼요.
  그래서 등기고유번호는 (a)형식 검증, (b)보조 식별/로그 용도로만 쓰고,
  실제 PNU는 '주소'에서 만듭니다. 등기번호만 달랑 들어오면, 우리 보증 DB에서
  그 번호로 주소를 찾아오는 단계가 필요(=lookup 콜백으로 위임).
"""

import re
from dataclasses import dataclass

from .registry_parser import parse_registry_address, ParsedRegistry


# 등기고유번호: 14자리 숫자. 보통 "1146-1996-072481"(4-4-6)로 표기.
_RE_REG_NO = re.compile(r"^\s*(\d{4})-?(\d{4})-?(\d{6})\s*$")
# 도로명주소 힌트: 'xx로' 'xx길' + 숫자
_RE_ROAD = re.compile(r"(로|길)\s*\d")


def is_registry_number(text):
    """등기고유번호(14자리) 형식인지 검사."""
    return bool(_RE_REG_NO.match(text or ""))


def normalize_registry_number(text):
    """등기고유번호를 하이픈 없는 14자리로 정규화. 형식이 아니면 None."""
    m = _RE_REG_NO.match(text or "")
    return (m.group(1) + m.group(2) + m.group(3)) if m else None


def looks_like_road_address(text):
    """도로명주소처럼 보이는지(='로/길 + 숫자' 패턴)."""
    return bool(_RE_ROAD.search(text or ""))


@dataclass
class RoutedInput:
    """입력 판별 결과."""
    종류: str                       # "등기고유번호" | "등기부주소" | "도로명주소" | "지번주소"
    원본: str
    등기고유번호: str = None         # 14자리(정규화)
    parsed: ParsedRegistry = None    # 주소를 분해한 결과(주소 입력일 때)
    needs_address_lookup: bool = False  # 등기번호만 와서 주소 조회가 필요한 경우


def route_input(text, *, registry_lookup=None):
    """
    입력을 판별해 분기한다.

    registry_lookup: 등기고유번호 -> 주소문자열 을 돌려주는 콜백(선택).
        우리 보증 DB 조회 함수를 여기 꽂으면, 등기번호만 와도 주소를 찾아
        이어서 파싱한다. 없으면 needs_address_lookup=True로 표시만 한다.
    """
    raw = (text or "").strip()

    # 1) 등기고유번호?
    if is_registry_number(raw):
        reg = normalize_registry_number(raw)
        routed = RoutedInput(종류="등기고유번호", 원본=raw, 등기고유번호=reg)
        if registry_lookup:
            addr = registry_lookup(reg)
            if addr:
                routed.parsed = parse_registry_address(addr)
                return routed
        routed.needs_address_lookup = True
        return routed

    # 2) 주소 -> 등기부형/도로명/지번 구분 후 파싱
    parsed = parse_registry_address(raw)
    if looks_like_road_address(raw):
        # 도로명: 지번 4요소를 직접 못 만드니, 정제엔진(juso/카카오)이 지번을 채워야 함.
        # parsed에는 시도/시군구까지는 들어갈 수 있음(나머지는 엔진이 보강).
        return RoutedInput(종류="도로명주소", 원본=raw, parsed=parsed)

    종류 = "등기부주소" if (parsed.호 or parsed.건물명) else "지번주소"
    return RoutedInput(종류=종류, 원본=raw, parsed=parsed)
