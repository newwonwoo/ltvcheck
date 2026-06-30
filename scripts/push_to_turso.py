#!/usr/bin/env python3
"""
push_to_turso.py — 로컬 officetel SQLite → Turso(libSQL) 업로드

build_officetel_db.py 로 만든 로컬 officetel.db 를 Turso 클라우드 DB에 올린다.
Vercel 서버리스는 로컬 파일 DB를 못 쓰므로, 운영에서는 Turso에서 조회한다.

[사전 준비 — 사용자 환경에서 1회]
  1) Turso 계정/DB 생성 (turso.tech 또는 Vercel Marketplace의 Turso Cloud 연동)
  2) 연결 정보 확보:
        TURSO_DATABASE_URL  (libsql://your-db.turso.io)
        TURSO_AUTH_TOKEN
  3) pip install libsql-client

[사용법]
  # 환경변수로 지정
  export TURSO_DATABASE_URL=libsql://...turso.io
  export TURSO_AUTH_TOKEN=...
  python scripts/push_to_turso.py --db officetel.db

  # 또는 인자로
  python scripts/push_to_turso.py --db officetel.db \
      --url libsql://...turso.io --token <TOKEN>

배치 INSERT로 올린다. 수십~수백만 행이면 시간이 걸리니 --batch 로 조절.
"""

import argparse
import os
import sqlite3
import sys

COLUMNS = ["pnu", "ldcode", "building", "dong", "floor", "ho", "prvuse", "price", "year"]


def push(db_path, url, token, batch=1000):
    try:
        import libsql_client
    except ImportError:
        sys.exit("[오류] libsql-client 미설치 → pip install libsql-client")

    if not os.path.exists(db_path):
        sys.exit(f"[오류] 로컬 DB 없음: {db_path}")
    if not url:
        sys.exit("[오류] TURSO_DATABASE_URL(또는 --url) 필요")

    src = sqlite3.connect(db_path)
    src.row_factory = sqlite3.Row
    total = src.execute("SELECT COUNT(*) FROM officetel").fetchone()[0]
    print(f"로컬 DB {db_path}: {total:,}행 → Turso 업로드 시작")

    client = libsql_client.create_client_sync(url=url, auth_token=token)

    # 원격 스키마 생성(없으면)
    client.execute("""CREATE TABLE IF NOT EXISTS officetel(
        pnu TEXT, ldcode TEXT, building TEXT, dong TEXT, floor TEXT, ho TEXT,
        prvuse REAL, price INTEGER, year TEXT,
        PRIMARY KEY(pnu, ho, year))""")
    client.execute("CREATE INDEX IF NOT EXISTS idx_off_pnu_ho ON officetel(pnu, ho)")

    placeholders = "(" + ",".join(["?"] * len(COLUMNS)) + ")"
    insert_sql = f"INSERT OR REPLACE INTO officetel ({','.join(COLUMNS)}) VALUES {placeholders}"

    sent = 0
    buf = []
    cur = src.execute(f"SELECT {','.join(COLUMNS)} FROM officetel")
    for row in cur:
        buf.append(libsql_client.Statement(insert_sql, [row[c] for c in COLUMNS]))
        if len(buf) >= batch:
            client.batch(buf)
            sent += len(buf)
            buf.clear()
            print(f"\r  업로드 중... {sent:,}/{total:,}행", end="", flush=True)
    if buf:
        client.batch(buf)
        sent += len(buf)

    src.close()
    # 원격 검증
    rs = client.execute("SELECT COUNT(*) FROM officetel")
    remote = rs.rows[0][0]
    client.close()
    print(f"\n[완료] Turso 업로드 {sent:,}행 | 원격 총 {remote:,}행")


def main():
    ap = argparse.ArgumentParser(description="로컬 officetel SQLite → Turso 업로드")
    ap.add_argument("--db", default="officetel.db", help="로컬 SQLite 경로")
    ap.add_argument("--url", default=os.environ.get("TURSO_DATABASE_URL", ""),
                    help="Turso DB URL (없으면 TURSO_DATABASE_URL)")
    ap.add_argument("--token", default=os.environ.get("TURSO_AUTH_TOKEN", ""),
                    help="Turso 토큰 (없으면 TURSO_AUTH_TOKEN)")
    ap.add_argument("--batch", type=int, default=1000, help="배치 크기")
    args = ap.parse_args()
    push(args.db, args.url, args.token, batch=args.batch)


if __name__ == "__main__":
    main()
