"""
officetel.py — 오피스텔 기준시가 조회 (국세청 파일 기반 DB)

연립·다세대는 VWorld 실시간 API(gongsiga.py)로 되지만,
오피스텔은 "공동주택"이 아니라 국세청 상업용건물/오피스텔 기준시가(파일)로만 제공된다.
그래서 오피스텔은 파일을 적재한 DB에서 조회한다.

[원천 파일] 국세청_상업용건물_오피스텔_기준시가 (xlsx, 연 1회)
  컬럼: 상가건물번호, 상가종류코드, 고시일자, 법정동코드, 특수지코드, 번지, 호,
        상가건물블록주소, 상가건물동주소, 건물층구분코드, 상가건물층주소,
        상가건물호주소, 고시가격, 전용면적, 공유면적
  → 상가종류코드='오피스텔'만 사용.
  → PNU = 법정동코드(10) + 산여부(특수지) + 번지(본번,zfill4) + 호(부번,zfill4)
  → 주의: 파일의 '호'는 지번 부번이고, 실제 호수는 '상가건물호주소' 컬럼이다.

[적재 스키마] (build_officetel_db.py가 생성)
  officetel(pnu, ldcode, building, dong, floor, ho, prvuse, price, year)
  - ho = 상가건물호주소(실제 호수, 등기부 호수와 매칭)
  - price = 고시가격(원)
  인덱스: (pnu, ho)

조회는 sqlite3(기본) 또는 주입된 커넥션으로. Vercel에서는 관리형 DB(libSQL 등)
커넥션을 주입한다. 키/DB경로는 환경변수에서만 읽는다.
"""

import os
import sqlite3
from dataclasses import dataclass, field


def _env(name, default=None):
    v = os.environ.get(name, "").strip()
    return v or default


@dataclass
class OfficetelUnit:
    pnu: str = None
    building: str = None   # 블록주소(건물명)
    dong: str = None
    floor: str = None
    ho: str = None         # 호주소(실제 호수)
    prvuse: float = None   # 전용면적
    price: int = None      # 고시가격(원)
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
    """호 비교용 정규화."""
    if v is None:
        return ""
    return str(v).strip().replace(" ", "").rstrip("호동층")


def _row_to_unit(r):
    return OfficetelUnit(
        pnu=r["pnu"], building=r["building"], dong=r["dong"],
        floor=r["floor"], ho=r["ho"], prvuse=r["prvuse"],
        price=int(r["price"]) if r["price"] is not None else None,
        year=r["year"],
    )


def fetch_officetel_by_pnu(pnu, year=None, *, ho=None, conn=None, db_path=None):
    """
    오피스텔 DB에서 PNU(+호)로 고시가격을 조회한다.

    conn    : 열린 DB 커넥션(주입). 없으면 db_path로 sqlite3 연결.
    db_path : SQLite 파일 경로. 없으면 환경변수 OFFICETEL_DB_PATH.
    반환: OfficetelResult
    """
    res = OfficetelResult(year=str(year) if year else None)
    own = False
    if conn is None:
        path = db_path or _env("OFFICETEL_DB_PATH")
        if not path:
            res.warnings.append("OFFICETEL_DB_PATH 미설정")
            return res
        if not os.path.exists(path):
            res.warnings.append(f"오피스텔 DB 없음: {path}")
            return res
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        own = True

    try:
        sql = "SELECT * FROM officetel WHERE pnu = ?"
        params = [pnu]
        if year:
            sql += " AND year = ?"
            params.append(str(year))
        rows = conn.execute(sql, params).fetchall()
        res.total_count = len(rows)
        if not rows:
            res.warnings.append("해당 PNU 오피스텔 없음")
            return res

        res.units = [_row_to_unit(r) for r in rows]

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
    except sqlite3.Error as e:
        res.warnings.append(f"오피스텔 조회 실패: {type(e).__name__}")
    finally:
        if own:
            conn.close()
    return res


def fetch_two_years(pnu, *, this_year, last_year, ho=None,
                    conn=None, db_path=None):
    """오피스텔 구·신 2개년 조회. 반환: (구, 신) OfficetelResult."""
    prev = fetch_officetel_by_pnu(pnu, last_year, ho=ho, conn=conn, db_path=db_path)
    cur = fetch_officetel_by_pnu(pnu, this_year, ho=ho, conn=conn, db_path=db_path)
    return prev, cur
