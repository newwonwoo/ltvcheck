"""
test_pipeline.py — 어댑터+공시가+파이프라인 통합 검증 (네트워크/키 불필요)

실제 juso/카카오/VWorld 응답 '형태'를 mock으로 만들어 주입한다.
=> 키 없이도 "주소 → PNU → 2개년 공시가 → 신뢰도" 전 흐름이 실제로 도는지 검증.
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jeonse_pnu import (
    geocode_juso, geocode_kakao, geocode,
    fetch_price_by_pnu, lookup,
)


# ── mock 응답 만들기 ───────────────────────────────────────────────────────
def mock_juso_ok(url):
    # 화곡동 504-32 가정: 법정동코드 1150010300, 대지(0), 본번504, 부번32
    return json.dumps({
        "results": {
            "common": {"errorCode": "0", "errorMessage": "정상"},
            "juso": [{
                "admCd": "1150010300", "mtYn": "0",
                "lnbrMnnm": "504", "lnbrSlno": "32",
                "jibunAddr": "서울특별시 강서구 화곡동 504-32",
                "roadAddr": "서울특별시 강서구 화곡로 123",
                "bdKdcd": "1", "hstryYn": "0",
            }],
        }
    })


def mock_juso_empty(url):
    return json.dumps({"results": {"common": {"errorCode": "0"}, "juso": []}})


def mock_kakao_ok(url, headers):
    return json.dumps({
        "documents": [{
            "address": {
                "b_code": "1150010300", "mountain_yn": "N",
                "main_address_no": "504", "sub_address_no": "32",
                "address_name": "서울 강서구 화곡동 504-32",
            }
        }]
    })


def mock_apart_price(units_by_year):
    """
    VWorld getApartHousingPriceAttr 실제 응답 형태로 mock.
    units_by_year = {"2026":[{dongNm,hoNm,pblntfPc,...}, ...], "2025":[...]}
    """
    def _get(url, timeout=6):
        year = "2026" if "stdrYear=2026" in url else "2025"
        units = units_by_year.get(year, [])
        return json.dumps({
            "apartHousingPrices": {
                "numOfRows": 1000, "pageNo": 1, "totalCount": len(units),
                "fields": {"field": units},
            }
        }, ensure_ascii=False)
    return _get


# VWorld 공식 응답 1건(상암월드컵1단지) — 사용자가 제공한 실제 응답 형태
def _field(dong, ho, price, year, name="에비앙하우스", se="다세대", floor="2", ar="41.69"):
    return {
        "pnu": "1147010100110000007", "ldCode": "1147010100",
        "ldCodeNm": "서울특별시 양천구 신정동", "regstrSeCodeNm": "일반",
        "mnnmSlno": "1000-7", "stdrYear": year, "stdrMt": "01",
        "aphusCode": "20000000", "aphusSeCodeNm": se, "aphusNm": name,
        "dongNm": dong, "floorNm": floor, "hoNm": ho,
        "prvuseAr": ar, "pblntfPc": str(price), "lastUpdtDt": "2026-05-14",
    }


# ── 어댑터 테스트 ──────────────────────────────────────────────────────────
def test_juso_to_pnu():
    r = geocode_juso("서울 강서구 화곡동 504-32", http_get=mock_juso_ok, key="DUMMY")
    assert r.ok and r.tier == 1
    pnu = r.parts.to_pnu()
    assert pnu == "1150010300105040032", pnu
    assert r.refined_address.endswith("504-32")


def test_kakao_to_pnu():
    r = geocode_kakao("화곡동 504-32", http_get=mock_kakao_ok, key="DUMMY")
    assert r.ok and r.tier == 2
    assert r.parts.to_pnu() == "1150010300105040032"


def test_geocode_fallback():
    # juso가 빈 결과 → 카카오로 폴백
    r = geocode("화곡동 504-32",
                juso_http=mock_juso_empty, kakao_http=mock_kakao_ok,
                juso_key="D", kakao_key="D")
    assert r.ok and r.tier == 2, r.tier
    assert any("juso 결과 없음" in w for w in r.warnings)


def test_apart_price_key_error():
    # 실제 INCORRECT_KEY 에러 응답 형태 처리
    def err_get(url, timeout=6):
        return json.dumps({"apartHousingPrices": {
            "resultCode": "INCORRECT_KEY", "resultMsg": "인증키 정보가 올바르지 않습니다."}})
    r = fetch_price_by_pnu("1147010100110000007", "2026",
                           http_get=err_get, key="WRONG")
    assert r.price is None
    assert any("INCORRECT_KEY" in w for w in r.warnings)


def test_gongsiga_unit_match():
    # 한 PNU에 여러 호 → 동/호로 특정 (빌라 호별 매칭)
    units = {
        "2026": [
            _field("", "201", 158000000, "2026"),
            _field("", "202", 226000000, "2026"),
            _field("", "203", 226000000, "2026"),
        ]
    }
    get = mock_apart_price(units)
    r = fetch_price_by_pnu("1147010100110000007", "2026", ho="202",
                           http_get=get, key="DUMMY")
    assert r.price == 226000000, r.price
    assert r.matched is not None and r.matched.hoNm == "202"
    assert r.total_count == 3


def test_full_pipeline_villa():
    units = {
        "2025": [_field("", "202", 240000000, "2025")],
        "2026": [_field("", "202", 228000000, "2026")],
    }
    get_price = mock_apart_price(units)

    out = lookup(
        "서울 강서구 화곡동 504-32 정원빌라 제202호",
        this_year="2026", last_year="2025",
        juso_http=mock_juso_ok, gongsiga_http=get_price,
        juso_key="D", gongsiga_key="D",
    )
    assert out.ok, out.warnings
    assert out.pnu == "1150010300105040032"
    assert out.ho == "202"
    assert out.price_last == 240000000
    assert out.price_this == 228000000
    assert out.price_delta == -12000000   # 공시가 하락
    assert out.confidence_grade in ("A", "B")
    # JSON 직렬화(서버 응답용) 되는지
    d = out.to_dict()
    assert json.dumps(d, ensure_ascii=False)


def test_pipeline_registry_number_needs_lookup():
    out = lookup("1146-1996-072481", this_year="2026", last_year="2025")
    assert out.ok is False
    assert any("보증DB" in w for w in out.warnings)


def _officetel_memory_db():
    """인메모리 오피스텔 DB(키/파일 없이 재현). 인터시티오피스텔 201호 구·신."""
    import sqlite3
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE officetel(
        pnu TEXT, ldcode TEXT, building TEXT, dong TEXT, floor TEXT, ho TEXT,
        prvuse REAL, price INTEGER, year TEXT)""")
    rows = [
        ("1150010300103430032", "1150010300", "인터시티오피스텔", "1", "2", "201",
         29.84, 2084000, "2025"),
        ("1150010300103430032", "1150010300", "인터시티오피스텔", "1", "2", "201",
         29.84, 2005000, "2026"),
    ]
    con.executemany("INSERT INTO officetel VALUES (?,?,?,?,?,?,?,?,?)", rows)
    con.commit()
    return con


def test_pipeline_officetel_integration():
    """오피스텔 물건: 공동주택 API 빈 응답 → 오피스텔 DB 경로 자동 선택 + 구·신 비교."""
    def juso_intercity(url, timeout=6):
        return json.dumps({"results": {"common": {"errorCode": "0", "totalCount": "1"},
            "juso": [{"admCd": "1150010300", "lnbrMnnm": "343", "lnbrSlno": "32",
                      "mtYn": "0", "jibunAddr": "서울특별시 강서구 화곡동 343-32",
                      "bdKdcd": "1"}]}})

    def apart_empty(url, timeout=6):
        return json.dumps({"apartHousingPrices": {"totalCount": 0, "fields": {"field": []}}})

    conn = _officetel_memory_db()
    out = lookup(
        "서울 강서구 화곡동 343-32 인터시티오피스텔 201호",
        this_year="2026", last_year="2025",
        juso_http=juso_intercity, juso_key="D",
        gongsiga_http=apart_empty, gongsiga_key="D",
        officetel_conn=conn,
    )
    assert out.ok, out.warnings
    assert out.property_type == "오피스텔", out.property_type
    assert out.pnu == "1150010300103430032"
    assert out.price_last == 2084000
    assert out.price_this == 2005000
    assert out.price_delta == -79000   # 기준시가 하락
    conn.close()


def test_officetel_libsql_path():
    """libSQL 클라이언트(file: = Turso와 동일 API) 조회 경로 검증."""
    try:
        import libsql_client
    except ImportError:
        print("  (libsql-client 미설치 — 스킵)")
        return
    import tempfile, os
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        c = libsql_client.create_client_sync(url="file:" + path)
        c.execute("""CREATE TABLE officetel(pnu TEXT,ldcode TEXT,building TEXT,
            dong TEXT,floor TEXT,ho TEXT,prvuse REAL,price INTEGER,year TEXT)""")
        c.execute("INSERT INTO officetel VALUES (?,?,?,?,?,?,?,?,?)",
                  ["1150010300103430032", "1150010300", "인터시티오피스텔", "1",
                   "2", "201", 29.84, 2005000, "2026"])
        from jeonse_pnu.officetel import fetch_officetel_by_pnu
        r = fetch_officetel_by_pnu("1150010300103430032", "2026", ho="201", conn=c)
        assert r.ok and r.price == 2005000, r.warnings
        assert r.matched and r.matched.ho == "201"
        c.close()
    finally:
        os.remove(path)


def test_geocode_dongmyeong_iji():
    """동명이지: 여러 행정구역 매칭 시 1순위 단정 말고 후보 전부 + ambiguous."""
    from jeonse_pnu.providers import geocode_juso

    def juso_multi(url, timeout=5):
        return json.dumps({"results": {"common": {"errorCode": "0"}, "juso": [
            {"admCd": "2611010100", "siNm": "부산광역시", "sggNm": "중구", "emdNm": "중앙동",
             "roadAddr": "부산 중앙대로", "jibunAddr": "부산 중앙동 300",
             "lnbrMnnm": "300", "lnbrSlno": "0", "mtYn": "0"},
            {"admCd": "3011010100", "siNm": "대전광역시", "sggNm": "중구", "emdNm": "중앙동",
             "roadAddr": "대전 중앙로", "jibunAddr": "대전 중앙동 300",
             "lnbrMnnm": "300", "lnbrSlno": "0", "mtYn": "0"},
        ]}})
    r = geocode_juso("중앙동 300", http_get=juso_multi, key="D")
    assert not r.ok and r.ambiguous
    assert len(r.region_candidates) == 2
    assert any("동명이지" in w for w in r.warnings)


def test_geocode_same_dong_compressed():
    """같은 법정동의 복수 표현은 prefix로 압축 → 자동 확정."""
    from jeonse_pnu.providers import geocode_juso

    def juso_same(url, timeout=5):
        return json.dumps({"results": {"common": {"errorCode": "0"}, "juso": [
            {"admCd": "1168010100", "siNm": "서울", "sggNm": "강남구", "emdNm": "역삼동",
             "roadAddr": "테헤란로 152", "jibunAddr": "역삼동 737",
             "lnbrMnnm": "737", "lnbrSlno": "0", "mtYn": "0", "bdKdcd": "0"},
            {"admCd": "1168010100", "siNm": "서울", "sggNm": "강남구", "emdNm": "역삼동",
             "roadAddr": "테헤란로 154", "jibunAddr": "역삼동 737-1",
             "lnbrMnnm": "737", "lnbrSlno": "1", "mtYn": "0", "bdKdcd": "0"},
        ]}})
    r = geocode_juso("역삼동", http_get=juso_same, key="D")
    assert r.ok and not r.ambiguous
    assert r.parts.to_pnu().startswith("1168010100")


def test_geocode_cascade_strip_detail():
    """캐스케이드: 동/호 붙은 원문 0건 → 상세 제거본으로 성공."""
    from jeonse_pnu.providers import geocode
    import urllib.parse as up

    def juso_cascade(url, timeout=5):
        q = up.parse_qs(up.urlparse(url).query).get("keyword", [""])[0]
        if "호" in q:  # 상세주소 남아있으면 0건
            return json.dumps({"results": {"common": {"errorCode": "0"}, "juso": []}})
        return json.dumps({"results": {"common": {"errorCode": "0"}, "juso": [
            {"admCd": "1150010300", "siNm": "서울", "sggNm": "강서구", "emdNm": "화곡동",
             "roadAddr": "화곡로 100", "jibunAddr": "화곡동 504-32",
             "lnbrMnnm": "504", "lnbrSlno": "32", "mtYn": "0", "bdKdcd": "1"}]}})
    r = geocode("서울 강서구 화곡동 504-32 102동 301호",
                juso_http=juso_cascade, juso_key="D", kakao_key=None)
    assert r.ok and r.parts.to_pnu() == "1150010300105040032"


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)}/{len(fns)} 통과")


if __name__ == "__main__":
    _run_all()
