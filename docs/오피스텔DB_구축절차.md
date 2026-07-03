# 오피스텔 DB 구축 절차서 (Vercel Postgres / Neon)

ltvcheck의 오피스텔 공시가는 국세청 파일 기반이라, 한 번 DB에 적재해야 조회됩니다.
연립·다세대(VWorld 실시간 API)는 이 작업과 무관하게 이미 동작합니다.

이 문서대로 하면: Vercel 안에서 Postgres를 만들고 → 데이터를 올리고 → 자동 연결까지 끝납니다.

---

## 0. 준비물
- Vercel 계정 (ltvcheck 프로젝트가 이미 배포돼 있어야 함)
- 국세청 "상업용건물·오피스텔 기준시가" xlsx (2026, 2025) — 또는 이미 만든 officetel.db
- 로컬 PC에 Python 3 + 이 레포

---

## 1. Vercel에서 Postgres(Neon) 생성

1. Vercel 대시보드 → 해당 프로젝트(ltvcheck) 선택
2. 상단 탭에서 **Storage** 클릭
3. **Create Database** (또는 Connect Store) 클릭
4. 목록에서 **Neon (Postgres)** 선택 → **Continue**
5. 이름은 아무거나(예: `ltvcheck-db`), 리전은 **가까운 곳** 선택
   - 함수가 서울(icn1)이니 가능하면 **가장 가까운 리전**(예: Singapore/Tokyo 계열)
6. **Create** → 잠시 후 DB 생성 완료

> 생성되면 Vercel이 이 프로젝트에 **POSTGRES_URL 등 환경변수를 자동으로 주입**합니다.
> (별도로 복붙할 필요 없음 — 프로젝트에 자동 연결됨)

---

## 2. 로컬에서 접속 정보(POSTGRES_URL) 가져오기

적재 스크립트를 **내 PC에서** 돌리려면 접속 URL이 필요합니다.

1. 방금 만든 DB 화면 → **.env.local** 또는 **Quickstart** 탭
2. `POSTGRES_URL` 값을 복사 (postgres://...sslmode=require 형태)
3. 로컬 터미널에 환경변수로 설정

   PowerShell(Windows):
   ```powershell
   $env:POSTGRES_URL = "여기에_복사한_URL_붙여넣기"
   ```
   bash/zsh(Mac/EC2):
   ```bash
   export POSTGRES_URL="여기에_복사한_URL_붙여넣기"
   ```

---

## 3. 드라이버 설치 (최초 1회)

```bash
pip install "psycopg[binary]" openpyxl
```

---

## 4. 데이터 적재 (둘 중 하나 선택)

### 방식 A — 이미 만든 SQLite가 있으면 (가장 빠름, 권장)
전에 `build_officetel_db.py`로 만든 `officetel.db`가 있다면:
```bash
python scripts/push_to_postgres.py --from-sqlite officetel.db
```

### 방식 B — 국세청 xlsx에서 바로 적재
```bash
python scripts/push_to_postgres.py --xlsx "2026_오피스텔_기준시가.xlsx" --year 2026
python scripts/push_to_postgres.py --xlsx "2025_오피스텔_기준시가.xlsx" --year 2025
```
(두 해를 각각 올리면 구·신 비교가 됩니다.)

> 전국이 크면 특정 시도만 먼저 테스트: `--region 11 41` (서울=11, 경기=41)

적재가 끝나면 콘솔에 `[완료] N행 적재 | Postgres 총 …행` 이 출력됩니다.

---

## 5. 확인

1. Vercel이 자동 재배포됐는지 확인(또는 수동 Redeploy)
2. 브라우저에서 진단:
   ```
   https://ltvcheck.vercel.app/api/diag
   ```
   → 오피스텔 항목이 `"mode": "Postgres"`, `"ok": true`, "조회 성공"으로 뜨면 완료
3. 실제 오피스텔 주소 + 호로 조회해 값이 나오는지 확인

---

## 자주 나는 문제

- **psycopg 미설치 에러**: `pip install "psycopg[binary]"` 다시.
- **POSTGRES_URL 없음**: 2번에서 복사한 URL을 환경변수로 설정했는지 확인.
- **sslmode 에러**: URL 끝에 `?sslmode=require`가 있는지 확인(Neon은 SSL 필수).
- **진단은 mode=Postgres인데 데이터 0건**: 적재 스크립트가 실제로 완료됐는지(4번 콘솔 출력) 확인.
- **연립·다세대는 되는데 오피스텔만 안 됨**: 정상 — 오피스텔만 이 DB가 필요. VWorld와 무관.

---

## 유지보수 메모
- 국세청 파일은 연 1회 갱신. 새 연도가 나오면 방식 B로 그 연도만 추가 적재하면 됩니다.
- 우선순위: POSTGRES_URL > TURSO_DATABASE_URL > OFFICETEL_DB_PATH (officetel.py `_open_default`).
  즉 Postgres를 붙이면 자동으로 그걸 씁니다.
