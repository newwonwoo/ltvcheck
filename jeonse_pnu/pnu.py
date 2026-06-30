"""
pnu.py — PNU(필지고유번호) 19자리 조립기

PNU는 '땅 한 필지'를 유일하게 가리키는 19자리 숫자예요.
구성은 이렇게 정해져 있어요(설계서에서 확인한 규칙):

    [법정동코드 10자리] + [산여부 1자리] + [본번 4자리] + [부번 4자리]

예) 서울 강서구 화곡동 504-32 (일반대지)
    -> 1150010300 + 1 + 0504 + 0032 = "1150010300" "1" "0504" "0032"
    -> "1150010300100040032" (19자리)

핵심 함정 3가지를 여기서 다 막아요:
  1) 본번/부번은 반드시 4자리로 0을 채운다(zfill). 504 -> "0504"
  2) 산여부: juso API는 0(대지)/1(산)으로 주는데, PNU 규약은 1(일반)/2(산).
     그래서 +1 변환이 필요. 이걸 안 하면 전국이 한 자리씩 틀어져요.
  3) 전부 '문자열'로 다룬다. 숫자로 바꾸면 앞자리 0이 날아가서 PNU가 깨져요.
"""

from dataclasses import dataclass


# PNU 산여부 코드: 1=일반(대지), 2=산. (juso의 0/1과 다름에 주의)
PNU_FLAG_NORMAL = "1"
PNU_FLAG_MOUNTAIN = "2"


class PnuError(ValueError):
    """PNU 조립에 필요한 값이 잘못됐을 때 던지는 에러."""
    pass


def normalize_mountain_flag(value, *, source="pnu"):
    """
    산여부 값을 PNU 규약(1=일반/2=산)으로 통일한다.

    들어오는 표기가 제각각이라 다 받아준다:
      - juso API:  mtYn = "0"(대지) / "1"(산)        -> source="juso"
      - 카카오:     mountain_yn = "N" / "Y"           -> source="kakao"
      - 이미 PNU:  "1" / "2"                          -> source="pnu"(기본)
      - 사람 입력: "산" 포함 여부

    반환: "1" 또는 "2" (문자열)
    """
    if value is None:
        return PNU_FLAG_NORMAL  # 정보 없으면 가장 흔한 '일반'으로 가정

    v = str(value).strip()

    if source == "juso":
        # juso: 0=대지(일반), 1=산
        return PNU_FLAG_MOUNTAIN if v == "1" else PNU_FLAG_NORMAL
    if source == "kakao":
        # 카카오: Y=산, N=대지
        return PNU_FLAG_MOUNTAIN if v.upper() == "Y" else PNU_FLAG_NORMAL

    # source="pnu" 또는 사람이 친 값
    if v in ("2", "산") or "산" in v:
        return PNU_FLAG_MOUNTAIN
    if v in ("1", "0", "", "대", "대지", "일반"):
        return PNU_FLAG_NORMAL
    # 알 수 없는 값이면 안전하게 일반으로
    return PNU_FLAG_NORMAL


def _pad4(num, field):
    """본번/부번을 4자리 문자열로 만든다. (앞자리 0 채우기)"""
    if num is None or str(num).strip() == "":
        return "0000"  # 부번이 없는 단식지번(예: 126번지)은 부번을 0000으로
    s = str(num).strip()
    if not s.isdigit():
        raise PnuError(f"{field}는 숫자여야 합니다: {num!r}")
    if len(s) > 4:
        raise PnuError(f"{field}가 4자리를 넘습니다: {num!r}")
    return s.zfill(4)


def build_pnu(beopjeongdong_code, *, bonbun, bubun=None,
              mountain="0", mountain_source="juso"):
    """
    PNU 19자리를 조립한다.

    입력:
      beopjeongdong_code : 법정동코드 10자리 (문자열/숫자)
      bonbun             : 지번 본번 (예: 504)
      bubun              : 지번 부번 (예: 32). 없으면 None -> 0000
      mountain           : 산여부 원본값
      mountain_source    : 산여부 표기 출처("juso"|"kakao"|"pnu")

    반환: 19자리 PNU 문자열

    예) build_pnu("1150010300", bonbun=504, bubun=32)
        -> "1150010300100040032"
    """
    code = str(beopjeongdong_code).strip()
    if not code.isdigit() or len(code) != 10:
        raise PnuError(f"법정동코드는 10자리 숫자여야 합니다: {beopjeongdong_code!r}")

    flag = normalize_mountain_flag(mountain, source=mountain_source)
    bon = _pad4(bonbun, "본번")
    bu = _pad4(bubun, "부번")

    pnu = code + flag + bon + bu
    # 최종 검증: 무조건 19자리 숫자여야 한다
    if len(pnu) != 19 or not pnu.isdigit():
        raise PnuError(f"조립 결과가 19자리가 아닙니다: {pnu!r}")
    return pnu


def split_pnu(pnu):
    """
    PNU 19자리를 구성요소로 다시 분해한다. (디버깅/검증용)
    반환: dict(법정동코드, 산여부, 본번, 부번)
    """
    p = str(pnu).strip()
    if len(p) != 19 or not p.isdigit():
        raise PnuError(f"PNU는 19자리 숫자여야 합니다: {pnu!r}")
    return {
        "법정동코드": p[0:10],
        "산여부": p[10:11],
        "본번": p[11:15],
        "부번": p[15:19],
    }


@dataclass
class PnuParts:
    """PNU 조립에 필요한 4요소를 담는 그릇. 각 provider 어댑터가 이걸 채워서 넘긴다."""
    beopjeongdong_code: str
    bonbun: str
    bubun: str = None
    mountain: str = "0"
    mountain_source: str = "juso"

    def to_pnu(self):
        return build_pnu(
            self.beopjeongdong_code,
            bonbun=self.bonbun,
            bubun=self.bubun,
            mountain=self.mountain,
            mountain_source=self.mountain_source,
        )
