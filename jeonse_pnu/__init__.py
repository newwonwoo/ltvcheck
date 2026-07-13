"""
jeonse_pnu — 전세보증 도메인 특화 주소 정제 → PNU 변환 → 등기 연계 패키지

핵심 흐름:
    입력(등기번호/등기부주소/일반주소)
      → route_input()        : 무엇이 들어왔는지 분기
      → parse_registry_address(): 주소를 지번 + 동/호로 분해
      → [정제엔진: juso/카카오로 PNU 4요소 확보]   (provider 어댑터, 키 필요)
      → build_pnu()          : PNU 19자리 조립
      → [호별 공시가 매칭]                          (가격 데이터 필요)
      → score_confidence()   : 신뢰도 등급

이 패키지의 '순수 로직'(파서·PNU 조립·분기·신뢰도)은 외부 키 없이 동작하며
단위 테스트로 검증됩니다. 외부 의존(엔진/가격DB)은 어댑터 자리로 비워둡니다.
"""

from .pnu import (
    build_pnu, split_pnu, normalize_mountain_flag,
    PnuParts, PnuError,
    PNU_FLAG_NORMAL, PNU_FLAG_MOUNTAIN,
)
from .registry_parser import parse_registry_address, ParsedRegistry
from .inputs import (
    route_input, RoutedInput,
    is_registry_number, normalize_registry_number, looks_like_road_address,
)
from .confidence import score_confidence, Confidence
from .providers import geocode, geocode_juso, geocode_kakao, GeocodeResult
from .gongsiga import fetch_price_by_pnu, fetch_two_years, PriceResult, UnitPrice
from .officetel import fetch_officetel_by_pnu, OfficetelResult, OfficetelUnit
from .pipeline import lookup, LookupResult

__version__ = "0.10.7"

__all__ = [
    "build_pnu", "split_pnu", "normalize_mountain_flag",
    "PnuParts", "PnuError", "PNU_FLAG_NORMAL", "PNU_FLAG_MOUNTAIN",
    "parse_registry_address", "ParsedRegistry",
    "route_input", "RoutedInput",
    "is_registry_number", "normalize_registry_number", "looks_like_road_address",
    "score_confidence", "Confidence",
    "geocode", "geocode_juso", "geocode_kakao", "GeocodeResult",
    "fetch_price_by_pnu", "fetch_two_years", "PriceResult", "UnitPrice",
    "fetch_officetel_by_pnu", "OfficetelResult", "OfficetelUnit",
    "lookup", "LookupResult",
    "__version__",
]
