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
    """인메모리 오피스텔 DB. 인터시티오피스텔 201호 구·신.
    price는 ㎡당 단가(원/㎡), 총액은 price×(전용+공유)로 계산됨(국세청 공식)."""
    import sqlite3
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE officetel(
        pnu TEXT, ldcode TEXT, building TEXT, dong TEXT, floor TEXT, ho TEXT,
        prvuse REAL, share REAL, price INTEGER, year TEXT)""")
    # 실데이터 기준: 201호 전용29.84 공유12.87
    rows = [
        ("1150010300103430032", "1150010300", "인터시티오피스텔", "1", "2", "201",
         29.84, 12.87, 2084000, "2025"),
        ("1150010300103430032", "1150010300", "인터시티오피스텔", "1", "2", "201",
         29.84, 12.87, 2005000, "2026"),
    ]
    con.executemany("INSERT INTO officetel VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
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
    # 총액 = ㎡당 × (전용+공유). 42.71㎡ 기준
    # 2025: 2084000×42.71 = 89,008,640 / 2026: 2005000×42.71 = 85,633,550
    assert out.price_last == round(2084000 * (29.84 + 12.87)), out.price_last
    assert out.price_this == round(2005000 * (29.84 + 12.87)), out.price_this
    assert out.price_delta < 0   # 기준시가 하락(㎡당 2084→2005)
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
            dong TEXT,floor TEXT,ho TEXT,prvuse REAL,share REAL,price INTEGER,year TEXT)""")
        c.execute("INSERT INTO officetel VALUES (?,?,?,?,?,?,?,?,?,?)",
                  ["1150010300103430032", "1150010300", "인터시티오피스텔", "1",
                   "2", "201", 29.84, 12.87, 2005000, "2026"])
        from jeonse_pnu.officetel import fetch_officetel_by_pnu
        r = fetch_officetel_by_pnu("1150010300103430032", "2026", ho="201", conn=c)
        # 총액 = 2005000 × (29.84+12.87)
        assert r.ok and r.price == round(2005000 * (29.84 + 12.87)), r.warnings
        assert r.matched and r.matched.ho == "201"
        c.close()
    finally:
        os.remove(path)


def test_officetel_total_price_calculation():
    """오피스텔 고시가격은 ㎡당 단가 → 총액=㎡당×(전용+공유). 계산근거도 응답에 포함."""
    import sqlite3
    from jeonse_pnu import lookup

    def juso(url, timeout=6):
        return json.dumps({"results": {"common": {"errorCode": "0"}, "juso": [
            {"admCd": "1150010300", "lnbrMnnm": "343", "lnbrSlno": "32", "mtYn": "0",
             "jibunAddr": "서울 강서구 화곡동 343-32", "bdKdcd": "1"}]}})

    def apart_empty(url, timeout=6):
        return json.dumps({"apartHousingPrices": {"totalCount": 0, "fields": {"field": []}}})

    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE officetel(pnu TEXT,ldcode TEXT,building TEXT,dong TEXT,floor TEXT,ho TEXT,
        prvuse REAL,share REAL,price INTEGER,year TEXT)""")
    con.executemany("INSERT INTO officetel VALUES (?,?,?,?,?,?,?,?,?,?)", [
        ("1150010300103430032", "1150010300", "OO텔", "1", "2", "201", 29.84, 12.87, 2005000, "2026"),
    ])
    con.commit()
    out = lookup("서울 강서구 화곡동 343-32 OO텔 201호", this_year="2026", last_year="2025",
                 juso_http=juso, juso_key="D", gongsiga_http=apart_empty, gongsiga_key="D",
                 officetel_conn=con)
    # 총액 = 2005000 × (29.84+12.87) = 85,633,550 (㎡당 raw 2005000이 아님)
    assert out.price_this == round(2005000 * 42.71), out.price_this
    assert out.price_this > 80_000_000  # ㎡당 raw였다면 200만원대였을 것
    assert out.price_calc["unit_price_per_m2"] == 2005000
    assert out.price_calc["total_area_m2"] == 42.71
    con.close()


def test_status_and_checks():
    """명시적 status 코드 + 확인단계(SKIP 포함) 파생."""
    from jeonse_pnu import lookup

    def juso(url, timeout=5):
        j = {"admCd": "1153010700", "siNm": "서울", "sggNm": "구로구", "emdNm": "개봉동",
             "roadAddr": "경인로 302", "jibunAddr": "개봉동 497", "lnbrMnnm": "497",
             "lnbrSlno": "0", "mtYn": "0", "bdKdcd": "1"}
        return json.dumps({"results": {"common": {"errorCode": "0"}, "juso": [j]}}, ensure_ascii=False)

    def vw(url, timeout=6):
        y = "2026" if "stdrYear=2026" in url else "2025"
        p = 510000000 if y == "2026" else 491000000
        f = [{"pnu": "P", "aphusNm": "센", "aphusSeCodeNm": "아파트", "dongNm": "", "hoNm": h,
              "floorNm": "14", "prvuseAr": "84", "pblntfPc": str(p), "stdrYear": y} for h in ["1401", "1403"]]
        return json.dumps({"apartHousingPrices": {"totalCount": 2, "fields": {"field": f}}}, ensure_ascii=False)

    d = lookup("서울 구로구 경인로 302", this_year="2026", last_year="2025", ho="1403",
               juso_http=juso, juso_key="D", gongsiga_http=vw, gongsiga_key="D").to_dict()
    assert d["status"] == "SUCCESS"
    states = {c["key"]: c["state"] for c in d["checks"]}
    assert states["address"] == "PASS"
    assert states["price"] == "PASS"
    # 등기 미입력은 실패가 아니라 SKIP
    assert states["registry"] == "SKIP"


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


def test_geocode_same_parcel_compressed():
    """같은 '필지(PNU)'의 복수 도로명 표현만 압축. 다른 번지는 별도 후보로 노출."""
    from jeonse_pnu.providers import geocode_juso

    # 같은 필지(역삼동 737)의 도로명 2개 표현 → 압축돼 자동확정
    def juso_same_parcel(url, timeout=5):
        return json.dumps({"results": {"common": {"errorCode": "0"}, "juso": [
            {"admCd": "1168010100", "siNm": "서울", "sggNm": "강남구", "emdNm": "역삼동",
             "roadAddr": "테헤란로 152", "jibunAddr": "역삼동 737",
             "lnbrMnnm": "737", "lnbrSlno": "0", "mtYn": "0", "bdKdcd": "0"},
            {"admCd": "1168010100", "siNm": "서울", "sggNm": "강남구", "emdNm": "역삼동",
             "roadAddr": "테헤란로 152 (별칭)", "jibunAddr": "역삼동 737",
             "lnbrMnnm": "737", "lnbrSlno": "0", "mtYn": "0", "bdKdcd": "0"},
        ]}})
    r = geocode_juso("역삼동 737", http_get=juso_same_parcel, key="D")
    assert r.ok and not r.ambiguous
    assert r.parts.to_pnu().startswith("1168010100")


def test_geocode_different_bunji_separated():
    """같은 법정동이라도 번지(본번/부번)가 다르면 별개 물건 → 후보로 노출(P0-2)."""
    from jeonse_pnu.providers import geocode_juso

    def juso_diff_bunji(url, timeout=5):
        return json.dumps({"results": {"common": {"errorCode": "0"}, "juso": [
            {"admCd": "1168010100", "siNm": "서울", "sggNm": "강남구", "emdNm": "역삼동",
             "roadAddr": "테헤란로 152", "jibunAddr": "역삼동 737",
             "lnbrMnnm": "737", "lnbrSlno": "0", "mtYn": "0", "bdKdcd": "0"},
            {"admCd": "1168010100", "siNm": "서울", "sggNm": "강남구", "emdNm": "역삼동",
             "roadAddr": "테헤란로 154", "jibunAddr": "역삼동 737-1",
             "lnbrMnnm": "737", "lnbrSlno": "1", "mtYn": "0", "bdKdcd": "0"},
        ]}})
    r = geocode_juso("역삼동", http_get=juso_diff_bunji, key="D")
    # 737과 737-1은 다른 필지 → 자동확정 금지, 후보 2건 노출
    assert r.ambiguous and len(r.region_candidates) == 2


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


def test_pipeline_multi_unit_requires_dongho():
    """여러 세대인데 동·호 없으면 임의 대표값 안 내고 needs_unit."""
    def juso_bldg(url, timeout=6):
        return json.dumps({"results": {"common": {"errorCode": "0"}, "juso": [
            {"admCd": "1153010700", "siNm": "서울", "sggNm": "구로구", "emdNm": "개봉동",
             "roadAddr": "경인로 302", "jibunAddr": "개봉동 497",
             "lnbrMnnm": "497", "lnbrSlno": "0", "mtYn": "0", "bdKdcd": "1"}]}}, ensure_ascii=False)

    def apt_multi(url, timeout=6):
        y = "2026" if "stdrYear=2026" in url else "2025"
        base = 459000000 if y == "2026" else 442000000
        fields = [{"pnu": "1153010700104970000", "aphusNm": "센트레빌", "aphusSeCodeNm": "아파트",
                   "dongNm": "", "hoNm": str(101 + i), "floorNm": "", "prvuseAr": "84",
                   "pblntfPc": str(base + i * 1000000), "stdrYear": y} for i in range(5)]
        return json.dumps({"apartHousingPrices": {"totalCount": 5, "fields": {"field": fields}}}, ensure_ascii=False)

    # 동·호 없음 → 값 없음 + needs_unit
    out = lookup("서울 구로구 경인로 302", this_year="2026", last_year="2025",
                 juso_http=juso_bldg, juso_key="D", gongsiga_http=apt_multi, gongsiga_key="D")
    assert out.ok is False and out.price_this is None and out.needs_unit is True

    # 호 지정 → 그 세대값
    out2 = lookup("서울 구로구 경인로 302 103호", this_year="2026", last_year="2025",
                  juso_http=juso_bldg, juso_key="D", gongsiga_http=apt_multi, gongsiga_key="D")
    assert out2.ok and out2.price_this == 461000000 and not out2.needs_unit


def test_road_name_space_normalize():
    """도로명 내부 공백('도신로 29길')을 붙여 건물번호를 안 잃게."""
    from jeonse_pnu.registry_parser import parse_registry_address as P
    # 띄어쓴 도로명도 건물번호 보존 + 검색질의에 붙여쓰기
    p1 = P("서울특별시 영등포구 도신로 29길 28")
    assert p1.도로명여부 and p1.건물번호 == "28"
    assert "도신로29길" in p1.검색질의 and "28" in p1.검색질의
    # 붙여쓴 것과 동일 결과
    p2 = P("서울특별시 영등포구 도신로29길 28")
    assert p2.검색질의 == p1.검색질의
    # 일반 '로 + 번호'는 그대로(경인로 302)
    p3 = P("서울 구로구 경인로 302")
    assert p3.도로명여부 and p3.건물번호 == "302"


def test_road_addr_no_truncation():
    """도로명주소는 절삭검색으로 엉뚱한 후보를 만들지 않는다."""
    import json as _j
    from jeonse_pnu.providers import geocode

    calls = []

    def juso_miss(url, timeout=5):
        # 무엇을 검색하든 빈 결과(도로명 원본을 못 찾는 상황 재현)
        import urllib.parse as up
        q = up.parse_qs(up.urlparse(url).query).get("keyword", [""])[0]
        calls.append(q)
        return _j.dumps({"results": {"common": {"errorCode": "0"}, "juso": []}})

    r = geocode("서울특별시 영등포구 도신로29길 28",
                juso_http=juso_miss, juso_key="D", kakao_key=None)
    # 도로명이므로 절삭검색('도신로29길'만 남기기 등)을 시도하지 않아야 함
    assert not r.ok
    # 건물번호를 뗀 부분검색이 호출되지 않았는지(절삭 억제 확인)
    assert not any(c.strip().endswith("도신로29길") for c in calls)


def test_explicit_dong_ho_numbers_only():
    """동·호를 숫자만 별도 필드로 넘기면 매칭된다(문자열 파싱 비의존)."""
    import json as _j

    def juso(url, timeout=5):
        return _j.dumps({"results": {"common": {"errorCode": "0"}, "juso": [
            {"admCd": "1153010700", "siNm": "서울", "sggNm": "구로구", "emdNm": "개봉동",
             "roadAddr": "경인로 302", "jibunAddr": "개봉동 497",
             "lnbrMnnm": "497", "lnbrSlno": "0", "mtYn": "0", "bdKdcd": "1"}]}}, ensure_ascii=False)

    def apt_multi(url, timeout=6):
        y = "2026" if "stdrYear=2026" in url else "2025"
        base = 500000000 if y == "2026" else 491000000
        fields = []
        for d in ["104", "105"]:
            for h in ["1402", "1403"]:
                bump = 10000000 if (d == "105" and h == "1403") else 0
                fields.append({"pnu": "P", "aphusNm": "센트레빌", "aphusSeCodeNm": "아파트",
                               "dongNm": d, "hoNm": h, "floorNm": "14", "prvuseAr": "84",
                               "pblntfPc": str(base + bump), "stdrYear": y})
        return _j.dumps({"apartHousingPrices": {"totalCount": len(fields), "fields": {"field": fields}}}, ensure_ascii=False)

    # 숫자만 별도 필드 → 매칭
    out = lookup("서울특별시 구로구 경인로 302", this_year="2026", last_year="2025",
                 dong="105", ho="1403", juso_http=juso, juso_key="D",
                 gongsiga_http=apt_multi, gongsiga_key="D")
    assert out.ok and not out.needs_unit and out.price_this == 510000000
    # 동·호 없으면 needs_unit
    out2 = lookup("서울특별시 구로구 경인로 302", this_year="2026", last_year="2025",
                  juso_http=juso, juso_key="D", gongsiga_http=apt_multi, gongsiga_key="D")
    assert not out2.ok and out2.needs_unit


def test_match_ho_only_when_no_dong():
    """VWorld 응답에 동이 없으면(빈값) 호로만 특정한다(센트레빌 케이스)."""
    from jeonse_pnu.gongsiga import fetch_price_by_pnu

    def vw_nodong(url, timeout=6):
        y = "2026" if "stdrYear=2026" in url else "2025"
        p = 510000000 if y == "2026" else 491000000
        fields = [{"pnu": "P", "aphusNm": "센트레빌", "aphusSeCodeNm": "아파트",
                   "dongNm": "", "hoNm": h, "floorNm": "14", "prvuseAr": "84",
                   "pblntfPc": str(p), "stdrYear": y} for h in ["1401", "1402", "1403"]]
        return json.dumps({"apartHousingPrices": {"totalCount": 3, "fields": {"field": fields}}}, ensure_ascii=False)

    # 동을 넣어도 VWorld에 동이 없으니 호로만 매칭돼 특정 성공
    r = fetch_price_by_pnu("P", "2026", dong="105", ho="1403", http_get=vw_nodong, key="D")
    assert r.ok and r.price == 510000000 and not r.needs_unit

    # 같은 호가 여러 동에 있으면 동이 필요 → needs_unit
    def vw_dupho(url, timeout=6):
        fields = [{"pnu": "P", "aphusNm": "x", "aphusSeCodeNm": "아파트",
                   "dongNm": d, "hoNm": "1403", "floorNm": "14", "prvuseAr": "84",
                   "pblntfPc": "510000000", "stdrYear": "2026"} for d in ["105", "106"]]
        return json.dumps({"apartHousingPrices": {"totalCount": 2, "fields": {"field": fields}}}, ensure_ascii=False)
    r2 = fetch_price_by_pnu("P", "2026", ho="1403", http_get=vw_dupho, key="D")
    assert not r2.ok and r2.needs_unit


def test_confidence_road_address_with_ho_is_B():
    """도로명주소로 호까지 특정되면(센트레빌 105/1403) 신뢰도 B 이상."""
    import json as _j
    from jeonse_pnu import lookup

    def juso(url, timeout=5):
        j = {"admCd": "1153010700", "siNm": "서울", "sggNm": "구로구", "emdNm": "개봉동",
             "roadAddr": "경인로 302", "jibunAddr": "개봉동 497", "lnbrMnnm": "497",
             "lnbrSlno": "0", "mtYn": "0", "bdKdcd": "1"}
        return _j.dumps({"results": {"common": {"errorCode": "0"}, "juso": [j]}}, ensure_ascii=False)

    def vw(url, timeout=6):
        y = "2026" if "stdrYear=2026" in url else "2025"
        p = 510000000 if y == "2026" else 491000000
        fields = [{"pnu": "1153010700104970000", "aphusNm": "센트레빌", "aphusSeCodeNm": "아파트",
                   "dongNm": "", "hoNm": h, "floorNm": "14", "prvuseAr": "84",
                   "pblntfPc": str(p), "stdrYear": y} for h in ["1401", "1402", "1403"]]
        return _j.dumps({"apartHousingPrices": {"totalCount": 3, "fields": {"field": fields}}}, ensure_ascii=False)

    out = lookup("서울특별시 구로구 경인로 302", this_year="2026", last_year="2025",
                 dong="105", ho="1403", juso_http=juso, juso_key="D", gongsiga_http=vw, gongsiga_key="D")
    assert out.price_this == 510000000
    assert out.confidence_grade in ("A", "B"), f"C가 아니라 B 이상이어야: {out.confidence_grade}"
    assert out.confidence_score >= 65


def test_building_name_search():
    """건물명만 입력해도(지번 없이) juso 건물명 검색으로 정제된다."""
    import json as _j
    from jeonse_pnu import lookup

    captured = []

    def juso(url, timeout=5):
        import urllib.parse as up
        q = up.parse_qs(up.urlparse(url).query).get("keyword", [""])[0]
        captured.append(q)
        if "진오피스텔" in q:
            j = {"admCd": "1153010200", "siNm": "서울특별시", "sggNm": "구로구", "emdNm": "구로동",
                 "roadAddr": "구로중앙로 152", "jibunAddr": "구로동 100 진오피스텔",
                 "lnbrMnnm": "100", "lnbrSlno": "0", "mtYn": "0", "bdKdcd": "1"}
            return _j.dumps({"results": {"common": {"errorCode": "0"}, "juso": [j]}}, ensure_ascii=False)
        return _j.dumps({"results": {"common": {"errorCode": "0"}, "juso": []}}, ensure_ascii=False)

    def vw(url, timeout=6):
        return _j.dumps({"apartHousingPrices": {"totalCount": 0, "fields": {"field": []}}}, ensure_ascii=False)

    # 건물명만 → juso 검색어에 건물명이 살아있어야
    out = lookup("서울특별시 구로구 진오피스텔", this_year="2026", last_year="2025",
                 juso_http=juso, juso_key="D", gongsiga_http=vw, gongsiga_key="D")
    assert any("진오피스텔" in q for q in captured), "건물명이 juso 검색어에 있어야"
    assert out.pnu, "건물명 검색으로 PNU가 조립돼야"

    # 건물명 + 별도 동/호 → 검색어는 건물명만(동/호 오염 없음)
    captured.clear()
    lookup("서울특별시 구로구 진오피스텔", this_year="2026", last_year="2025",
           dong="105", ho="201", juso_http=juso, juso_key="D", gongsiga_http=vw, gongsiga_key="D")
    assert all("201" not in q and "105" not in q for q in captured)


def test_available_units_returned():
    """여러 세대일 때 존재하는 동·호 목록을 available_units로 반환한다."""
    import json as _j
    from jeonse_pnu import lookup

    def juso(url, timeout=5):
        j = {"admCd": "1153010700", "siNm": "서울", "sggNm": "구로구", "emdNm": "개봉동",
             "roadAddr": "경인로38길 13", "jibunAddr": "개봉동 500", "lnbrMnnm": "500",
             "lnbrSlno": "0", "mtYn": "0", "bdKdcd": "1"}
        return _j.dumps({"results": {"common": {"errorCode": "0"}, "juso": [j]}}, ensure_ascii=False)

    def vw(url, timeout=6):
        y = "2026" if "stdrYear=2026" in url else "2025"
        fields = [{"pnu": "P", "aphusNm": "신개봉삼환", "aphusSeCodeNm": "아파트",
                   "dongNm": d, "hoNm": h, "floorNm": "1", "prvuseAr": "84",
                   "pblntfPc": "500000000", "stdrYear": y}
                  for d in ["101", "102"] for h in ["101", "1403"]]
        return _j.dumps({"apartHousingPrices": {"totalCount": 4, "fields": {"field": fields}}}, ensure_ascii=False)

    out = lookup("서울특별시 구로구 경인로38길 13", this_year="2026", last_year="2025",
                 juso_http=juso, juso_key="D", gongsiga_http=vw, gongsiga_key="D")
    assert out.needs_unit is True
    d = out.to_dict()
    assert len(d["available_units"]) == 4
    # 동→호 순 정렬 확인
    assert d["available_units"][0] == {"dong": "101", "ho": "101"}
    assert d["available_units"][-1] == {"dong": "102", "ho": "1403"}


def test_norm_prefix_preserved():
    """문자 접두부(B/A/지하)는 세대 식별자 — 101과 절대 동일시 금지."""
    from jeonse_pnu.gongsiga import _norm
    assert _norm("B101") != _norm("101")
    assert _norm("A101") != _norm("101")
    assert _norm("지하101") != _norm("101")
    assert _norm("b101") == _norm("B101")      # 대소문자만 흡수
    assert _norm("B0101") == _norm("B101")     # 접두부+앞0
    # 기존 회귀 유지
    assert _norm("105") == _norm("제105동") == _norm("105동") == _norm("0105")
    assert _norm("1403") == _norm("1403호")


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)}/{len(fns)} 통과")


# ── v0.10.4: 확정된 PNU 재사용 (후보 선택 무한루프 방지) ──
def juso_same_dong_multi_parcels(url):
    """같은 법정동인데 필지가 여러 개 → 후보 여러 개 (실제 케이스: 서초구 반포동)"""
    return json.dumps({"results": {"common": {"errorCode": "0"}, "juso": [
        {"admCd": "1165010700", "mtYn": "0", "lnbrMnnm": "18", "lnbrSlno": "0",
         "roadAddr": "서울특별시 서초구 반포대로 333 (반포동, 래미안 원베일리)",
         "jibunAddr": "서울특별시 서초구 반포동 18", "bdKdcd": "1",
         "siNm": "서울특별시", "sggNm": "서초구", "emdNm": "반포동"},
        {"admCd": "1165010700", "mtYn": "0", "lnbrMnnm": "20", "lnbrSlno": "0",
         "roadAddr": "서울특별시 서초구 신반포로 127 (반포동)",
         "jibunAddr": "서울특별시 서초구 반포동 20", "bdKdcd": "1",
         "siNm": "서울특별시", "sggNm": "서초구", "emdNm": "반포동"},
    ]}})


def apart_reanpo(url):
    return json.dumps({"apartHousingPrices": {"field": [
        {"pnu": "1165010700100180000", "dongNm": "113", "hoNm": "203",
         "pblntfPc": "1800000000", "aphusNm": "래미안 원베일리", "aphusSeCodeNm": "아파트"},
    ]}})


def test_region_candidates_carry_pnu():
    """후보에 PNU가 실려 와야 한다 (그래야 재정제 없이 바로 조회 가능)"""
    r = lookup("서울특별시 서초구 반포대로 333", this_year="2026", last_year="2025",
               juso_http=juso_same_dong_multi_parcels, gongsiga_http=apart_reanpo,
               juso_key="D", gongsiga_key="D")
    assert r.ambiguous is True
    cands = r.region_candidates or []
    assert len(cands) >= 2
    for c in cands:
        assert c.get("pnu"), "후보에 PNU가 없다"
        assert len(c["pnu"]) == 19, f"PNU가 19자리가 아니다: {c['pnu']}"


def test_pnu_given_skips_refine():
    """PNU가 주어지면 주소를 다시 정제하지 않는다.
    (재정제하면 juso가 또 여러 필지를 물어와 후보 선택 화면으로 되돌아간다 — 무한루프)"""
    addr = "서울특별시 서초구 반포대로 333 (반포동, 래미안 원베일리)"

    # PNU 없이: 후보가 또 뜬다
    r_old = lookup(addr, this_year="2026", last_year="2025", dong="113", ho="203",
                   juso_http=juso_same_dong_multi_parcels, gongsiga_http=apart_reanpo,
                   juso_key="D", gongsiga_key="D")
    assert r_old.ambiguous is True

    # PNU 주면: 정제를 건너뛰고 바로 조회
    r_new = lookup(addr, this_year="2026", last_year="2025", dong="113", ho="203",
                   pnu="1165010700100180000",
                   juso_http=juso_same_dong_multi_parcels, gongsiga_http=apart_reanpo,
                   juso_key="D", gongsiga_key="D")
    assert r_new.ambiguous is False, "PNU를 줬는데도 후보가 떴다"
    assert r_new.pnu == "1165010700100180000"
    assert r_new.dong == "113" and r_new.ho == "203"
    assert r_new.building_name == "래미안 원베일리"


# ── v0.10.7: 대단지 세대 매칭 (서버 필터 1차 + 전체수신 폴백) ──
def test_large_complex_server_filter():
    """2,462세대 대단지: 동·호를 주면 서버 필터가 1건만 준다.
    전체 수신은 1,000건 제한이 있어 페이지를 놓치면 못 찾는다 — 그 위험을 우회한다."""
    from jeonse_pnu.gongsiga import fetch_price_by_pnu
    PNU = "1156013300100280000"
    calls = []

    def http(url):
        calls.append(url)
        if "dongNm=106" in url and "hoNm=802" in url:
            return json.dumps({"apartHousingPrices": {"field": [
                {"pnu": PNU, "dongNm": "106", "hoNm": "802", "pblntfPc": "900000000",
                 "aphusNm": "영등포푸르지오", "aphusSeCodeNm": "아파트"}], "totalCount": 1}})
        # 전체 요청: 2462건인데 1000건만 온다(페이지 누락 재현)
        return json.dumps({"apartHousingPrices": {"field": [
            {"pnu": PNU, "dongNm": "218", "hoNm": str(i), "pblntfPc": "9",
             "aphusNm": "영등포푸르지오", "aphusSeCodeNm": "아파트"} for i in range(1000)],
            "totalCount": 2462}})

    r = fetch_price_by_pnu(PNU, "2026", dong="106", ho="802", http_get=http, key="K")
    assert r.matched is not None, "서버 필터로 세대를 찾지 못했다"
    assert r.price == 900_000_000
    assert len(calls) == 1, "서버 필터로 끝나야 하는데 전체 수신까지 갔다"


def test_notation_mismatch_falls_back():
    """VWorld 표기가 '제106동'/'0802'면 서버 필터가 0건 → 전체 수신 폴백이 흡수한다."""
    from jeonse_pnu.gongsiga import fetch_price_by_pnu
    PNU = "1156013300100280000"

    def http(url):
        if "dongNm=" in url:
            return json.dumps({"apartHousingPrices": {"field": [], "totalCount": 0}})
        return json.dumps({"apartHousingPrices": {"field": [
            {"pnu": PNU, "dongNm": "제106동", "hoNm": "0802", "pblntfPc": "900000000",
             "aphusNm": "영등포푸르지오", "aphusSeCodeNm": "아파트"},
            {"pnu": PNU, "dongNm": "제218동", "hoNm": "0802", "pblntfPc": "800000000",
             "aphusNm": "영등포푸르지오", "aphusSeCodeNm": "아파트"}], "totalCount": 2}})

    r = fetch_price_by_pnu(PNU, "2026", dong="106", ho="802", http_get=http, key="K")
    assert r.matched is not None, "폴백이 표기차를 흡수하지 못했다"
    assert r.price == 900_000_000


def test_no_unit_still_lists_all():
    """동·호 없이 조회하면 전체를 받아 세대 목록을 만든다(기존 동작 유지)."""
    from jeonse_pnu.gongsiga import fetch_price_by_pnu
    PNU = "1156013300100280000"

    def http(url):
        return json.dumps({"apartHousingPrices": {"field": [
            {"pnu": PNU, "dongNm": "106", "hoNm": "802", "pblntfPc": "9",
             "aphusNm": "A", "aphusSeCodeNm": "아파트"},
            {"pnu": PNU, "dongNm": "218", "hoNm": "802", "pblntfPc": "8",
             "aphusNm": "A", "aphusSeCodeNm": "아파트"}], "totalCount": 2}})

    r = fetch_price_by_pnu(PNU, "2026", http_get=http, key="K")
    assert len(r.units) == 2
    assert r.needs_unit is True
    assert r.price is None, "임의 대표세대를 쓰면 안 된다"


if __name__ == "__main__":
    _run_all()
