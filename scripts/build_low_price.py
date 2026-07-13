#!/usr/bin/env python3
"""
build_low_price.py — 국토부 공동주택 공시가격 CSV → "공시가 상한 미만" 지역별 JSON

비적재(No-DB) 방식의 핵심 준비 스크립트.
상한이 고정(예: 1억)이므로, 미리 그 미만만 뽑아 법정동코드별 JSON으로 쪼갠다.
조회 시에는 해당 지역 JSON 하나만 정적 서빙 → DB/서버 불필요.

사용법:
  # 1억 미만 (기본)
  python build_low_price.py --csv 공동주택공시가격_2025.csv --out public/data/low

  # 상한 바꾸기 (보증한도용 6억 등)
  python build_low_price.py --csv ... --out public/data/guarantee --limit 600000000

  # 특정 지역만 (테스트)
  python build_low_price.py --csv ... --out public/data/low --region 11530 11440

국토부 CSV 컬럼명은 배포 회차마다 다를 수 있어, 컬럼 매핑을 자동 추정 + 수동 지정 지원.
  --col-price "공동주택가격" --col-area "전용면적" ...

바이브코더 요약:
  1) data.go.kr에서 공동주택 공시가격 CSV 다운로드(1,558만 건)
  2) 이 스크립트로 "1억 미만"만 뽑아 지역별 JSON 생성(파일 작아짐)
  3) public/data/low/ 를 레포에 커밋 → Vercel이 정적 파일로 서빙
  4) 끝. DB 없음.
"""

import argparse
import csv
import json
import os
import sys
from collections import defaultdict

# CSV 헤더 자동 추정용 후보(회차별 명칭 차이 흡수)
COL_CANDIDATES = {
    "sido": ["시도", "시·도", "시도명", "광역시도"],
    "sigungu": ["시군구", "시·군·구", "시군구명"],
    "eupmyeondong": ["읍면동", "법정동", "읍면동명", "동리", "동명"],
    "jibun": ["지번", "번지"],
    "name": ["단지명", "공동주택명", "건물명", "아파트명"],
    "dong": ["동명", "동", "건물동"],
    "ho": ["호명", "호", "호수"],
    "type": ["공동주택구분", "주택유형", "구분", "유형"],
    "area": ["전용면적", "전용면적(㎡)", "면적", "전용"],
    "price": ["공동주택가격", "공시가격", "공동주택가격(원)", "가격", "공시가"],
    "ldcode": ["법정동코드", "지역코드", "법정동시군구코드"],
    "bdmgt": ["관리건축물대장PK", "건축물대장PK", "관리건축물대장pk"],
}


def _guess_columns(header, overrides):
    """헤더에서 각 논리컬럼의 실제 인덱스를 찾는다."""
    idx = {}
    norm = [h.strip().replace(" ", "") for h in header]
    for logical, cands in COL_CANDIDATES.items():
        if logical in overrides and overrides[logical]:
            want = overrides[logical].strip().replace(" ", "")
            if want in norm:
                idx[logical] = norm.index(want)
                continue
        for c in cands:
            cc = c.replace(" ", "")
            if cc in norm:
                idx[logical] = norm.index(cc)
                break
    return idx


def _to_int(v):
    if v is None:
        return None
    s = str(v).replace(",", "").replace('"', "").strip()
    if not s or not any(ch.isdigit() for ch in s):
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def _to_float(v):
    if v is None:
        return None
    s = str(v).replace(",", "").replace('"', "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _norm_type(v):
    """공동주택구분을 아파트/연립/다세대로 정규화."""
    s = (v or "").strip()
    if "아파트" in s:
        return "아파트"
    if "연립" in s:
        return "연립"
    if "다세대" in s:
        return "다세대"
    return s or "기타"


def _region5(idx, row, ldcode_fallback=None):
    """법정동코드 앞 5자리(시군구) 추출. 없으면 ldcode 컬럼에서."""
    if "ldcode" in idx:
        code = str(row[idx["ldcode"]]).strip().strip('"')
        if len(code) >= 5:
            return code[:5]
    return ldcode_fallback


def build(csv_path, out_dir, limit, regions, overrides, encoding):
    if not os.path.exists(csv_path):
        sys.exit(f"[오류] CSV 없음: {csv_path}")
    os.makedirs(out_dir, exist_ok=True)
    region_filter = set(regions) if regions else None

    buckets = defaultdict(list)   # 시군구코드 → [item...]
    region_name = {}              # 시군구코드 → "서울 구로구"
    total, kept, skipped = 0, 0, 0

    with open(csv_path, "r", encoding=encoding, errors="replace", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        idx = _guess_columns(header, overrides)

        # 필수 컬럼 확인
        need = ["price", "area"]
        missing = [n for n in need if n not in idx]
        if missing:
            sys.exit(f"[오류] 필수 컬럼 매핑 실패: {missing}\n  헤더: {header}\n"
                     f"  --col-price / --col-area 로 직접 지정하세요.")

        print(f"[컬럼 매핑] {idx}")

        for row in reader:
            total += 1
            if total % 1_000_000 == 0:
                print(f"\r  처리 {total:,}행... (수집 {kept:,})", end="", flush=True)
            try:
                price = _to_int(row[idx["price"]])
                area = _to_float(row[idx["area"]])
            except IndexError:
                skipped += 1
                continue
            if price is None or area is None or area <= 0:
                skipped += 1
                continue
            # ★ 상한 필터
            # 상한 '이하(≤)' 포함: 공시가가 정확히 상한(예: 1억)인 물건도 대상
            if price > limit:
                continue

            r5 = _region5(idx, row)
            if r5 is None:
                skipped += 1
                continue
            if region_filter and r5 not in region_filter:
                continue

            sido = row[idx["sido"]].strip() if "sido" in idx else ""
            sigungu = row[idx["sigungu"]].strip() if "sigungu" in idx else ""
            if r5 not in region_name:
                region_name[r5] = (sido + " " + sigungu).strip() or r5

            item = {
                "dong": row[idx["eupmyeondong"]].strip() if "eupmyeondong" in idx else "",
                "name": row[idx["name"]].strip() if "name" in idx else "",
                "bldDong": row[idx["dong"]].strip() if "dong" in idx else "",
                "ho": row[idx["ho"]].strip() if "ho" in idx else "",
                "type": _norm_type(row[idx["type"]]) if "type" in idx else "기타",
                "area": round(area, 2),
                "price": price,
                # ㎡당 공시가(특히 다세대 비교용) — 미리 계산
                "perM2": round(price / area) if area else None,
            }
            buckets[r5].append(item)
            kept += 1

    print(f"\n[집계] 총 {total:,}행 / 수집 {kept:,} / 스킵 {skipped:,} / 지역 {len(buckets)}개")

    # 지역별 JSON 저장(공시가 낮은 순 정렬)
    index_meta = []
    for r5, items in buckets.items():
        items.sort(key=lambda x: x["price"])
        payload = {
            "region": region_name.get(r5, r5),
            "code": r5,
            "limit": limit,
            "count": len(items),
            "items": items,
        }
        path = os.path.join(out_dir, f"{r5}.json")
        with open(path, "w", encoding="utf-8") as wf:
            json.dump(payload, wf, ensure_ascii=False, separators=(",", ":"))
        index_meta.append({"code": r5, "region": region_name.get(r5, r5), "count": len(items)})

    # 지역 목록 인덱스(드롭다운용)
    index_meta.sort(key=lambda x: x["code"])
    with open(os.path.join(out_dir, "_index.json"), "w", encoding="utf-8") as wf:
        json.dump({"limit": limit, "regions": index_meta}, wf, ensure_ascii=False)

    # 용량 리포트
    sizes = []
    for r5 in buckets:
        p = os.path.join(out_dir, f"{r5}.json")
        sizes.append(os.path.getsize(p))
    if sizes:
        print(f"[용량] 지역파일 {len(sizes)}개, 평균 {sum(sizes)//len(sizes)//1024}KB, "
              f"최대 {max(sizes)//1024}KB")
    print(f"[완료] → {out_dir}/  (_index.json + 지역별 JSON)")


def main():
    ap = argparse.ArgumentParser(description="공동주택 공시가격 CSV → 상한 미만 지역별 JSON")
    ap.add_argument("--csv", required=True, help="국토부 공동주택 공시가격 CSV")
    ap.add_argument("--out", default="public/data/low", help="출력 디렉터리")
    ap.add_argument("--limit", type=int, default=100_000_000, help="공시가 상한(원). 기본 1억")
    ap.add_argument("--region", nargs="*", default=None, help="시군구코드5 필터(생략=전국)")
    ap.add_argument("--encoding", default="utf-8", help="CSV 인코딩(기본 utf-8, 필요시 cp949)")
    for logical in COL_CANDIDATES:
        ap.add_argument(f"--col-{logical}", dest=f"col_{logical}", default=None,
                        help=f"{logical} 컬럼명 직접 지정")
    args = ap.parse_args()

    overrides = {k: getattr(args, f"col_{k}") for k in COL_CANDIDATES}
    build(args.csv, args.out, args.limit, args.region, overrides, args.encoding)


if __name__ == "__main__":
    main()
