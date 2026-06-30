# ltvcheck — 전세보증 한도 미리보기

연립·다세대·오피스텔의 **공시가격 변동**을 미리 확인하는 서비스.
시세가 없는 주택은 전세보증 한도가 `공시가격 × 적용비율(HUG 126% 룰)`로 정해지므로,
공시가격이 매년 갱신될 때 한도가 어떻게 달라지는지 미리 안내한다.

> 아파트는 KB시세 기반이라 제외. **연립·다세대·오피스텔만** 대상.

---

## 무엇을 보여주나

주소를 넣으면 → 작년·올해 공시가격을 비교해 **증감액·증감률**을 보여주고,
보증 범위가 늘/줄 수 있다고 따뜻하게 안내한다. (확정 판정이 아니라 참고용)

---

## 구조 (한 레포에 프론트 + 백엔드)

```
ltvcheck/
├ index.html            ← Vite 진입점
├ src/                  ← React 프론트엔드 (디자인)
│  ├ App.jsx               전체 화면 조립
│  ├ components/
│  │  ├ Result.jsx          결과(곡선+증감+안내)
│  │  └ ValueJourney.jsx    작년→올해 공시가 잇는 곡선 그래프(시그니처)
│  ├ data/samples.js       검증된 실데이터 샘플(백엔드 연결 전 데모용)
│  ├ utils/format.js       금액 포맷(원/억)
│  └ styles/app.css        디자인 토큰·전체 스타일
├ api/lookup.py         ← 백엔드 (Vercel 파이썬 서버리스 함수)
├ jeonse_pnu/           ← 주소→PNU→공시가 코어 패키지 (표준 라이브러리만)
│  ├ pipeline.py           통합 파이프라인 lookup()
│  ├ gongsiga.py           연립·다세대: VWorld 공동주택가격 실시간 API
│  ├ officetel.py          오피스텔: 국세청 기준시가 DB 조회
│  ├ providers.py          juso 주소정제(도로명/지번 → PNU)
│  └ ...                   pnu / inputs / confidence / registry_parser
├ scripts/
│  └ build_officetel_db.py 오피스텔 기준시가 xlsx → SQLite 적재
├ tests/                ← 검증 테스트 (코어 12 + 파이프라인 8 = 20)
├ setup_keys.py         ← 로컬 키 입력 도우미(.env.local 자동 생성)
├ vercel.json           ← Vercel 빌드/함수 설정
└ .env.example          ← 필요한 키 목록
```

**왜 프론트(React)와 백엔드(Python)가 한 레포?**
Vercel은 `/api/*.py`를 파이썬 서버리스 함수로, 나머지는 Vite 정적 빌드로 함께 배포한다.
즉 한 번의 `git push`로 둘 다 올라간다.

---

## 데이터 출처 (이원 구조)

| 대상 | 공시가격 소스 | 방식 |
|------|--------------|------|
| 연립·다세대 | 국토부 공동주택가격 (VWorld `getApartHousingPriceAttr`) | **실시간 API** |
| 오피스텔 | 국세청 상업용건물/오피스텔 기준시가 | **파일 → DB 적재** |

연립·다세대는 API라 매년 자동 갱신. 오피스텔은 파일이라 연 1회 재적재 필요.

---

## 로컬 실행

```bash
# 1) 프론트 의존성
npm install

# 2) 키 설정 (.env.local 자동 생성, git에 안 올라감)
python setup_keys.py
#   - JUSO_API_KEY     주소검색 (business.juso.go.kr)
#   - VWORLD_API_KEY   공동주택 공시가격 (www.vworld.kr) + VWORLD_DOMAIN
#   - OFFICETEL_DB_PATH 오피스텔 DB 경로(아래 적재 후)

# 3) 오피스텔 DB 적재 (국세청 xlsx 필요, 연 1회)
python scripts/build_officetel_db.py --xlsx 2026파일.xlsx --year 2026 --db officetel.db
python scripts/build_officetel_db.py --xlsx 2025파일.xlsx --year 2025 --db officetel.db

# 4) 개발 서버
npm run dev          # 프론트 (http://localhost:5173)
vercel dev           # 프론트 + /api 함께 (권장)
```

키가 없어도 프론트는 뜨고, **예시 칩**으로 디자인·흐름을 볼 수 있다(샘플 데이터).
실제 주소 조회는 키 연결 후 동작한다.

---

## 배포 (Vercel)

1. 이 레포를 Vercel 프로젝트로 연결 (Import Git Repository)
2. **Settings → Environment Variables** 에 키 등록 (한 번 = 영구):
   `JUSO_API_KEY`, `VWORLD_API_KEY`, `VWORLD_DOMAIN`, `OFFICETEL_DB_PATH`
   - Production / Preview / Development 모두 체크
3. 배포 → `git push` 마다 자동 재배포

> 키는 **서버사이드(api/lookup.py)에서만** 읽고 브라우저로 내려가지 않는다.
> Vercel 서버리스는 로컬 SQLite 호스팅이 안 되므로, 운영에서 오피스텔은
> 관리형 DB(libSQL/Turso 등) 커넥션 주입을 권장(`officetel.py`의 `conn` 인자).

---

## 검증

```bash
python tests/test_core.py        # 코어 12/12
python tests/test_pipeline.py    # 파이프라인 8/8 (통합·오피스텔 포함)
npm run build                    # 프론트 빌드
```

상세 검증 내역은 `품질확인서.md` 참고.

---

## 범위 밖 (의도적)

- **한도 계산(126% 적용·차감 역산)**: 본 서비스 출력은 *구·신 공시가격까지*.
  실제 한도 산정은 별도 심사 단계.
- 판정(가능/불가)을 내리지 않음 — 숫자와 변동만 안내.
