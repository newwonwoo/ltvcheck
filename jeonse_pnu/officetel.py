"""
officetel.py — 오피스텔 기준시가 조회 (국세청 파일 기반 DB)

연립·다세대는 VWorld 실시간 API(gongsiga.py)로 되지만,
오피스텔은 "공동주택"이 아니라 국세청 상업용건물/오피스텔 기준시가(파일)로만 제공된다.
그래서 오피스텔은 파일을 적재한 DB에서 조회한다.

[DB 두 가지 모드 — 자동 판별]
  1) 로컬 SQLite : OFFICETEL_DB_PATH=/경로/officetel.db  (개발/EC2)
  2) Turso(libSQL): TURSO_DATABASE_URL + TURSO_AUTH_TOKEN  (Vercel 서버리스)
     - Vercel 서버리스는 로컬 파일 DB를 못 쓰므로 운영은 Turso 권장.
     - libsql_client.create_client_sync(url, auth_token) 로 연결, 같은 SQL 사용.

[원천 파일] 국세청_상업용건물_오피스텔_기준시가 (xlsx, 연 1회)
  → 상가종류코드='오피스텔'만 사용.
  → PNU = 법정동코드(10) + 산여부(특수지) + 번지(본번,zfill4) + 호(부번,zfill4)
  → 주의: 파일의 '호'는 지번 부번이고, 실제 호수는 '상가건물호주소' 컬럼이다.

[적재 스키마] (scripts/build_officetel_db.py 가 생성)
  officetel(pnu, ldcode, building, dong, floor, ho, prvuse, price, year)
  - ho = 상가건물호주소(실제 호수, 등기부 호수와 매칭), price = 고시가격(원)
  인덱스: (pnu, ho)

조회는 sqlite3(기본) / libSQL(Turso) / 주입 커넥션을 모두 받는다.
키·URL·토큰은 환경변수에서만 읽는다(엔벨롭).
"""

import os
import sqlite3
from dataclasses import dataclass, field


# 적재/조회가 공유하는 컬럼 순서
COLUMNS = ["pnu", "ldcode", "building", "dong", "floor", "ho", "prvuse", "price", "year"]


def _env(name, default=None):
    v = os.environ.get(name, "").strip()
    return v or default


@dataclass
class OfficetelUnit:
    pnu: str = None
    building: str = None
    dong: str = None
    floor: str = None
    ho: str = None
    prvuse: float = None
    price: int = None
    year: str = None


@dataclass
class OfficetelResult:
    year: str = None
    units: list = field(default_factory=list)
    matched: OfficetelUnit = None
    price: int = None
    total_count: int = 0
    warnings: list = field(default_factory=list)

    @property
    def ok(self):
        return self.price is not None


def _norm(v):
    if v is None:
        return ""
    return str(v).strip().replace(" ", "").rstrip("호동층")


def _dict_to_unit(d):
    price = d.get("price")
    try:
        price = int(price) if price is not None else None
    except (ValueError, TypeError):
        price = None
    return OfficetelUnit(
        pnu=d.get("pnu"), building=d.get("building"), dong=d.get("dong"),
        floor=d.get("floor"), ho=d.get("ho"), prvuse=d.get("prvuse"),
        price=price, year=d.get("year"),
    )


# ── 백엔드별 조회 헬퍼 (모두 dict 리스트로 정규화해 반환) ──────────────────

def _query_sqlite(conn, sql, params):
    conn.row_factory = sqlite3.Row
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def _query_libsql(client, sql, params):
    # libsql_client: execute(sql, args) → ResultSet(.columns, .rows)
    rs = client.execute(sql, params)
    cols = list(rs.columns)
    out = []
    for row in rs.rows:
        # row는 인덱스/이름 모두 접근 가능하지만 안전하게 zip
        out.append({cols[i]: row[i] for i in range(len(cols))})
    return out


def _open_default():
    """
    환경에 맞는 DB 연결을 연다.
    우선순위: Turso(TURSO_DATABASE_URL) > 로컬 SQLite(OFFICETEL_DB_PATH).
    반환: (kind, handle, own)  kind ∈ {"libsql","sqlite",None}
    """
    turso_url = _env("TURSO_DATABASE_URL")
    if turso_url:
        try:
            import libsql_client
        except ImportError:
            return ("error", "libsql_client 미설치 (pip install libsql-client)", False)
        token = _env("TURSO_AUTH_TOKEN")
        client = libsql_client.create_client_sync(url=turso_url, auth_token=token)
        return ("libsql", client, True)

    path = _env("OFFICETEL_DB_PATH")
    if path:
        if not os.path.exists(path):
            return ("error", f"오피스텔 DB 없음: {path}", False)
        return ("sqlite", sqlite3.connect(path), True)

    return (None, None, False)


def fetch_officetel_by_pnu(pnu, year=None, *, ho=None, conn=None, db_path=None):
    """
    오피스텔 DB에서 PNU(+호)로 고시가격을 조회한다.

    conn    : 주입 커넥션. sqlite3.Connection 또는 libsql client.
              (libsql client는 .execute가 있고 sqlite3와 구분해 처리)
    db_path : 로컬 SQLite 경로(테스트/오버라이드). 없으면 환경변수 자동 판별.
    반환: OfficetelResult
    """
    res = OfficetelResult(year=str(year) if year else None)

    sql = "SELECT pnu, ldcode, building, dong, floor, ho, prvuse, price, year " \
          "FROM officetel WHERE pnu = ?"
    params = [pnu]
    if year:
        sql += " AND year = ?"
        params.append(str(year))

    kind, handle, own = None, None, False
    try:
        if conn is not None:
            # 주입 커넥션: sqlite3인지 libsql인지 판별
            if isinstance(conn, sqlite3.Connection):
                kind, handle = "sqlite", conn
            else:
                kind, handle = "libsql", conn
        elif db_path:
            if not os.path.exists(db_path):
                res.warnings.append(f"오피스텔 DB 없음: {db_path}")
                return res
            kind, handle, own = "sqlite", sqlite3.connect(db_path), True
        else:
            kind, handle, own = _open_default()
            if kind is None:
                res.warnings.append("오피스텔 DB 미설정(OFFICETEL_DB_PATH/TURSO_DATABASE_URL)")
                return res
            if kind == "error":
                res.warnings.append(handle)
                return res

        if kind == "sqlite":
            recs = _query_sqlite(handle, sql, params)
        else:
            recs = _query_libsql(handle, sql, params)

        res.total_count = len(recs)
        if not recs:
            res.warnings.append("해당 PNU 오피스텔 없음")
            return res

        res.units = [_dict_to_unit(d) for d in recs]

        if ho:
            for u in res.units:
                if _norm(u.ho) == _norm(ho):
                    res.matched = u
                    break
            if res.matched is None and len(res.units) > 1:
                res.warnings.append(f"호 미매칭 - 후보 {len(res.units)}건")

        chosen = res.matched or res.units[0]
        res.price = chosen.price
        if res.matched is None and ho:
            res.warnings.append("호 특정 실패 - 첫 세대값 사용(주의)")
    except Exception as e:
        res.warnings.append(f"오피스텔 조회 실패: {type(e).__name__}")
    finally:
        if own and handle is not None:
            try:
                handle.close()
            except Exception:
                pass
    return res


def fetch_two_years(pnu, *, this_year, last_year, ho=None,
                    conn=None, db_path=None):
    """오피스텔 구·신 2개년 조회. 반환: (구, 신) OfficetelResult."""
    prev = fetch_officetel_by_pnu(pnu, last_year, ho=ho, conn=conn, db_path=db_path)
    cur = fetch_officetel_by_pnu(pnu, this_year, ho=ho, conn=conn, db_path=db_path)
    return prev, cur
