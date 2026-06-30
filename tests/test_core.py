"""
test_core.py — 코어 순수 로직 검증 (외부 키 불필요)
실행: python3 -m pytest tests/test_core.py -v   또는   python3 tests/test_core.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jeonse_pnu import (
    build_pnu, split_pnu, normalize_mountain_flag, PnuError,
    parse_registry_address, route_input,
    is_registry_number, normalize_registry_number,
    score_confidence,
)


def test_pnu_basic():
    # 화곡동 504-32, 일반대지 -> 법정동코드 + 1 + 0504 + 0032
    pnu = build_pnu("1150010300", bonbun=504, bubun=32)
    assert pnu == "1150010300105040032", pnu
    assert len(pnu) == 19


def test_pnu_zfill():
    # 본번/부번 앞자리 0 채우기: 126 -> 0126, 부번없음 -> 0000
    pnu = build_pnu("1150010300", bonbun=126)
    assert pnu[11:15] == "0126"
    assert pnu[15:19] == "0000"


def test_pnu_mountain_flag_conversion():
    # juso의 mtYn=1(산) -> PNU 2 로 변환되어야 함
    pnu = build_pnu("1150010300", bonbun=12, bubun=3, mountain="1", mountain_source="juso")
    assert pnu[10] == "2", pnu
    # juso mtYn=0(대지) -> PNU 1
    pnu2 = build_pnu("1150010300", bonbun=12, bubun=3, mountain="0", mountain_source="juso")
    assert pnu2[10] == "1"
    # 카카오 Y -> 2
    assert normalize_mountain_flag("Y", source="kakao") == "2"
    assert normalize_mountain_flag("N", source="kakao") == "1"


def test_pnu_split_roundtrip():
    pnu = build_pnu("1150010300", bonbun=504, bubun=32)
    parts = split_pnu(pnu)
    assert parts["법정동코드"] == "1150010300"
    assert parts["본번"] == "0504"
    assert parts["부번"] == "0032"


def test_pnu_errors():
    # 법정동코드 자릿수 오류
    try:
        build_pnu("123", bonbun=1)
        assert False, "에러가 나야 함"
    except PnuError:
        pass
    # 본번이 4자리 초과
    try:
        build_pnu("1150010300", bonbun=99999)
        assert False
    except PnuError:
        pass


def test_registry_parse_villa():
    # 전형적인 빌라 등기부 주소
    p = parse_registry_address("서울특별시 강서구 화곡동 504-32 정원빌라 제2층 제202호")
    assert p.시도 == "서울특별시"
    assert p.시군구 == "강서구"
    assert p.읍면동 == "화곡동"
    assert p.본번 == "504"
    assert p.부번 == "32"
    assert p.호 == "202"
    assert p.층 == "제2층" or "2" in (p.층 or "")
    assert "정원빌라" in (p.건물명 or "")
    assert p.지번 == "504-32"


def test_registry_parse_variants():
    # 약칭 시도 + 호 표기 변형 + 부번 없음
    p = parse_registry_address("서울 관악구 신림동 1640 그린빌 402호")
    assert p.시도 == "서울특별시"
    assert p.읍면동 == "신림동"
    assert p.본번 == "1640"
    assert p.호 == "402"

    # 성남시 분당구(시+구 동시표기)
    p2 = parse_registry_address("경기 성남시 분당구 백현동 537 봇들마을 제101동 제303호")
    assert "분당구" in (p2.시군구 or "")
    assert p2.읍면동 == "백현동"


def test_registry_parse_mountain():
    p = parse_registry_address("강원특별자치도 춘천시 동면 산 12-3")
    assert p.산여부 == "1"
    assert p.본번 == "12"
    assert p.부번 == "3"


def test_registry_jibun_address_for_engine():
    # 정제엔진에 넘길 지번주소 문자열이 잘 만들어지나
    p = parse_registry_address("서울특별시 강서구 화곡동 504-32 정원빌라 제202호")
    assert p.지번주소 == "서울특별시 강서구 화곡동 504-32"


def test_registry_number_detection():
    assert is_registry_number("1146-1996-072481")
    assert is_registry_number("1146199607 2481".replace(" ", ""))
    assert normalize_registry_number("1146-1996-072481") == "11461996072481"
    assert not is_registry_number("화곡동 504-32")


def test_route_input_types():
    # 등기번호
    r1 = route_input("1146-1996-072481")
    assert r1.종류 == "등기고유번호"
    assert r1.needs_address_lookup is True

    # 등기번호 + lookup 콜백
    r1b = route_input("1146-1996-072481",
                      registry_lookup=lambda n: "서울 강서구 화곡동 504-32 정원빌라 제202호")
    assert r1b.parsed is not None
    assert r1b.parsed.호 == "202"

    # 등기부 주소(호 있음)
    r2 = route_input("서울 강서구 화곡동 504-32 정원빌라 제202호")
    assert r2.종류 == "등기부주소"

    # 도로명주소
    r3 = route_input("서울 강서구 화곡로 123")
    assert r3.종류 == "도로명주소"

    # 지번주소(호 없음)
    r4 = route_input("서울 강서구 화곡동 504-32")
    assert r4.종류 == "지번주소"


def test_confidence():
    # 최상: 1차 정제 + 지번 + 호 + 교차검증
    c = score_confidence(refine_tier=1, has_jibun=True, has_ho=True,
                         registry_cross_checked=True)
    assert c.score == 100
    assert c.grade == "A"
    assert not c.needs_manual_check

    # 호 미확정 -> 등급 하락, 수동확인 가능성
    c2 = score_confidence(refine_tier=1, has_jibun=True, has_ho=False)
    assert c2.score < c.score
    assert "호 미확정" in " ".join(c2.notes)

    # 정제 실패 -> F
    c3 = score_confidence(refine_tier=None, has_jibun=False, has_ho=False)
    assert c3.grade == "F"
    assert c3.needs_manual_check


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
        passed += 1
    print(f"\n{passed}/{len(fns)} 통과")


if __name__ == "__main__":
    _run_all()
