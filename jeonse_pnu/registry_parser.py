"""
registry_parser.py — 등기부등본 '소재지번' 문자열 파서

빌라(구분건물)의 등기부 주소는 보통 이렇게 생겼어요:

    "서울특별시 강서구 화곡동 504-32 정원빌라 제2층 제202호"
     └── 행정구역 ──┘ └지번┘ └건물명┘ └층┘ └─호─┘

여기서 우리가 뽑아야 할 건 두 종류예요:
  1) 토지 지번(504-32)  -> PNU 만드는 재료
  2) 전유부분(2층 202호) -> 빌라 한 동의 '몇 호'인지 = 호별 공시가 매칭 키

한 줄에 이 둘이 같이 들어 있어서, 등기부 주소 한 줄만 있으면
PNU와 호를 동시에 건질 수 있어요. 이게 이 파서의 존재 이유예요.

표기가 제각각이라(제202호 / 202호 / B01호, 제2층 / 2층 / 지하1층 등)
정규식을 넉넉하게 잡고, 못 뽑은 항목은 None으로 두되 '무엇을 못 뽑았는지'
플래그로 남겨요(뒤에서 confidence 계산에 씀).
"""

import re
from dataclasses import dataclass, field


# 시도 약칭 -> 정식명칭 (앞부분 표준화용)
_SIDO = {
    "서울": "서울특별시", "부산": "부산광역시", "대구": "대구광역시",
    "인천": "인천광역시", "광주": "광주광역시", "대전": "대전광역시",
    "울산": "울산광역시", "세종": "세종특별자치시", "경기": "경기도",
    "강원": "강원특별자치도", "충북": "충청북도", "충남": "충청남도",
    "전북": "전북특별자치도", "전남": "전라남도", "경북": "경상북도",
    "경남": "경상남도", "제주": "제주특별자치도",
}


@dataclass
class ParsedRegistry:
    """등기부 주소를 분해한 결과."""
    원본: str
    시도: str = None
    시군구: str = None
    읍면동: str = None
    산여부: str = "0"          # "0"=일반, "1"=산 (juso 표기로 통일)
    본번: str = None
    부번: str = None
    건물명: str = None
    건물동: str = None         # 아파트 동(예: "105") - 읍면동과 구분
    건물번호: str = None       # 도로명주소의 건물번호(예: "302")
    층: str = None
    호: str = None
    도로명여부: bool = False    # 도로명주소면 True (지번은 juso 정제로 채워야 함)
    경고: list = field(default_factory=list)  # 못 뽑았거나 의심스러운 항목

    @property
    def 지번(self):
        if not self.본번:
            return None
        return self.본번 if not self.부번 or self.부번 == "0" else f"{self.본번}-{self.부번}"

    @property
    def 지번주소(self):
        """정제엔진(juso/카카오)에 넘길 지번주소 문자열."""
        parts = [self.시도, self.시군구, self.읍면동]
        addr = " ".join(p for p in parts if p)
        if self.본번:
            san = "산 " if self.산여부 == "1" else ""
            addr += f" {san}{self.지번}"
        return addr.strip()

    @property
    def 검색질의(self):
        """
        juso/카카오에 보낼 최적 검색어.
        - 도로명주소: 시도 + 시군구 + 도로명 + 건물번호 (juso가 지번을 채워줌)
        - 지번주소:   지번주소 그대로
        둘 다 비면 원본으로 폴백(호출부에서 처리).
        """
        if self.도로명여부:
            parts = [self.시도, self.시군구, self.건물명, self.건물번호]
            return " ".join(p for p in parts if p).strip()
        return self.지번주소


# ── 정규식들 (넉넉하게) ────────────────────────────────────────────────
# 호: "제202호", "202호", "제 202 호", "B01호", "지하101호"
_RE_HO = re.compile(r"제?\s*([A-Za-z]?\d{1,4}(?:-\d{1,4})?)\s*호")
# 층: "제2층", "2층", "지하1층", "지하 1층", "B1층"
_RE_CHUNG = re.compile(r"(지하\s*\d+|[Bb]\d+|제?\s*\d+)\s*층")
# 지번: "504-32", "산 12-3", "126" (동 뒤에 오는 숫자-숫자 또는 숫자)
_RE_JIBUN = re.compile(r"(산)?\s*(\d{1,4})(?:-(\d{1,4}))?")
# 도로명+건물번호: "경인로 302", "디지털로 226", "○○길 12-3"
#   (로/길로 끝나는 토큰 + 뒤따르는 숫자 = 건물번호. 이건 지번이 아니다!)
_RE_ROAD_NAME = re.compile(r"(\S*(?:로|길))\s+(\d+(?:-\d+)?)")
# 아파트 동: "105동", "제101동" (숫자+동 = 건물 동, 읍면동과 구분)
_RE_BLD_DONG = re.compile(r"제?\s*(\d{1,4})\s*동")
# '외 N필지' 같은 꼬리표 (있으면 경고만)
_RE_EXTRA_PARCEL = re.compile(r"외\s*\d+\s*필지")


def parse_registry_address(raw):
    """
    등기부 소재지번 문자열을 분해한다.

    반환: ParsedRegistry
    """
    result = ParsedRegistry(원본=raw or "")
    if not raw or not raw.strip():
        result.경고.append("빈 입력")
        return result

    s = " ".join(raw.split())  # 공백 정리

    # '외 N필지' 표기는 토지가 여러 필지라는 뜻 -> 주의 플래그
    if _RE_EXTRA_PARCEL.search(s):
        result.경고.append("복수필지(외 N필지) - 대표필지로 처리됨")
        s = _RE_EXTRA_PARCEL.sub("", s)

    # 1) 호 추출 (뒤에서부터)
    m_ho = _RE_HO.search(s)
    if m_ho:
        result.호 = m_ho.group(1)
        s = s[:m_ho.start()] + s[m_ho.end():]
    else:
        result.경고.append("호 미인식")

    # 2) 층 추출
    m_chung = _RE_CHUNG.search(s)
    if m_chung:
        result.층 = m_chung.group(1).replace(" ", "")
        s = s[:m_chung.start()] + s[m_chung.end():]

    # 3) 시도 표준화
    s = s.strip()
    tokens = s.split()
    if tokens:
        first = tokens[0]
        for abbr, full in _SIDO.items():
            if first == full or first == abbr:
                result.시도 = full
                tokens = tokens[1:]
                break
            # "서울특별시" 처럼 풀네임이 정확히 일치
        else:
            # 풀네임 토큰이 _SIDO 값에 있는지
            if first in _SIDO.values():
                result.시도 = first
                tokens = tokens[1:]

    # 4) 시군구 (xx시/군/구)
    if tokens and re.search(r"[시군구]$", tokens[0]):
        result.시군구 = tokens[0]
        tokens = tokens[1:]
        # 시 + 구 동시 표기(예: 성남시 분당구) 대응
        if tokens and re.search(r"구$", tokens[0]):
            result.시군구 = (result.시군구 + " " + tokens[0]).strip()
            tokens = tokens[1:]

    # 5) 읍면동 (xx동/읍/면/가/리)
    if tokens and re.search(r"[동읍면가리]$", tokens[0]):
        result.읍면동 = tokens[0]
        tokens = tokens[1:]
    else:
        result.경고.append("읍면동 미인식")

    # 6) 남은 토큰에서 아파트 동 → (도로명 판별) → 지번 + 건물명 분리
    rest = " ".join(tokens).strip()

    # 6-1) 아파트 동(105동 등) 먼저 분리 (읍면동과 다름, 호별 매칭용)
    m_bld = _RE_BLD_DONG.search(rest)
    if m_bld:
        result.건물동 = m_bld.group(1)
        rest = (rest[:m_bld.start()] + " " + rest[m_bld.end():]).strip()

    # 6-2) 도로명(로/길 + 건물번호)인지 판별
    #   도로명이면 그 숫자는 '건물번호'지 지번이 아니다 → 지번은 juso 정제로 채워야 함.
    m_road = _RE_ROAD_NAME.search(rest)
    if m_road:
        result.도로명여부 = True
        result.건물명 = result.건물명 or m_road.group(1)  # 도로명 보존
        result.건물번호 = m_road.group(2)                  # 건물번호 보존
        result.경고.append("도로명주소 - 지번은 juso 정제 필요")
        # 본번/부번을 여기서 만들지 않는다(추측 금지)
        return result

    # 6-3) 지번주소: 지번 + 건물명 추출
    m_jibun = _RE_JIBUN.search(rest)
    if m_jibun:
        if m_jibun.group(1) == "산":
            result.산여부 = "1"
        result.본번 = m_jibun.group(2)
        result.부번 = m_jibun.group(3) or "0"
        tail = rest[m_jibun.end():].strip(" .,번지호")
        if tail:
            result.건물명 = tail
    else:
        result.경고.append("지번 미인식")

    return result
