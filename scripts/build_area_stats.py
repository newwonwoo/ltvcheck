#!/usr/bin/env python3
"""
build_area_stats.py — 동네(법정동)별 공시가격 통계 생성

목적: "내 전세금으로 갈 만한 동네"를 찾기 위해, 법정동 단위로 공시가 분포를 집계한다.

대상: 연립·다세대만.
  · HUG 126% 룰(공시가×140%×90%)은 비아파트 기준이다.
  · 아파트는 시세(KB 등)를 우선 쓰므로 공시가 기반 판정이 성립하지 않는다.
  · 오피스텔은 공시가격이 아니라 국세청 기준시가를 쓰므로 별도 처리한다.

입력: 국토교통부 공동주택 공시가격 CSV (부동산공시가격알리미 / 공공데이터포털)
출력: public/data/area/{시군구코드}.json + _index.json

등급은 프론트에서 계산한다(전세금·선순위가 바뀌면 즉시 재계산되어야 하므로).
여기서는 히스토그램만 만들어 두고, 임의 임계값에 대한 비율을 프론트가 구한다.

사용:
  python3 scripts/build_area_stats.py <csv경로> [--year 2026] [--encoding cp949]
"""
import csv
import json
import os
import sys
import time
import argparse
import urllib.request
import urllib.parse
from collections import defaultdict
from statistics import mean, median

OUT_DIR = "public/data/area"
COORD_CACHE = ".area_coords_cache.json"


def geocode_kakao(query, key, cache):
    """법정동 → 중심좌표 (카카오 주소검색).

    좌표는 네이버 부동산 딥링크(center=)를 만드는 데 쓴다.
    키가 없으면 None을 반환하고, 그 경우 프론트는 좌표 없이 동작한다(딥링크 대신 검색 안내).
    """
    if not key:
        return None
    if query in cache:
        return cache[query]
    url = "https://dapi.kakao.com/v2/local/search/address.json?" + urllib.parse.urlencode(
        {"query": query, "size": 1}
    )
    req = urllib.request.Request(url, headers={"Authorization": f"KakaoAK {key}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.load(r)
        docs = d.get("documents") or []
        if not docs:
            cache[query] = None
            return None
        doc = docs[0]
        # address(지번) 우선, 없으면 road_address
        node = doc.get("address") or doc.get("road_address") or doc
        lon, lat = float(node["x"]), float(node["y"])
        cache[query] = {"lat": round(lat, 6), "lon": round(lon, 6)}
    except Exception:
        cache[query] = None
    time.sleep(0.05)  # 과도한 호출 방지
    return cache[query]

# 히스토그램: 0 ~ 5억을 1천만원 단위로, 그 위는 하나로 묶는다.
BIN_SIZE = 10_000_000
BIN_MAX = 500_000_000
N_BINS = BIN_MAX // BIN_SIZE  # 50

# 대상 주택유형 (비아파트)
TARGET_TYPES = ("연립", "다세대")

# CSV 컬럼명 후보 (지자체·연도별로 표기가 다름)
COL_CANDIDATES = {
    "sigungu": ["시군구", "시군구명", "시·군·구"],
    "eupmyeondong": ["읍면동", "법정동", "읍면동명", "동리", "동명", "법정동명"],
    "complex": ["단지명", "공동주택명", "건물명"],
    "type": ["주택유형", "공동주택구분", "유형", "주택구분"],
    "area": ["전용면적", "전용면적(㎡)", "면적"],
    "price": ["공시가격", "공동주택가격", "공시가격(원)", "가격"],
    "ldcode": ["법정동코드", "지역코드", "법정동시군구코드"],
}


def guess_columns(header):
    idx = {}
    norm = [h.strip().replace(" ", "") for h in header]
    for key, cands in COL_CANDIDATES.items():
        for cand in cands:
            c = cand.replace(" ", "")
            if c in norm:
                idx[key] = norm.index(c)
                break
    return idx


def to_int(s):
    if not s:
        return None
    t = str(s).replace(",", "").replace(" ", "").strip()
    if not t or not t.replace(".", "").isdigit():
        return None
    return int(float(t))


def to_float(s):
    if not s:
        return None
    t = str(s).replace(",", "").strip()
    try:
        return float(t)
    except ValueError:
        return None


def sigungu_code(row, idx):
    """법정동코드 앞 5자리 = 시군구코드"""
    if "ldcode" in idx:
        code = str(row[idx["ldcode"]]).strip()
        if len(code) >= 5 and code[:5].isdigit():
            return code[:5]
    return None


def build_hist(prices):
    """1천만원 단위 히스토그램. 마지막 칸은 5억 초과."""
    bins = [0] * (N_BINS + 1)
    for p in prices:
        b = p // BIN_SIZE
        if b >= N_BINS:
            bins[N_BINS] += 1
        else:
            bins[b] += 1
    return bins


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path")
    ap.add_argument("--year", type=int, default=None, help="공시 기준연도")
    ap.add_argument("--encoding", default="cp949", help="CSV 인코딩 (기본 cp949)")
    ap.add_argument("--kakao-key", default=os.environ.get("KAKAO_REST_KEY"),
                    help="카카오 REST 키. 넣으면 동네 좌표를 조회해 네이버 딥링크를 만든다.")
    args = ap.parse_args()

    if not os.path.exists(args.csv_path):
        sys.exit(f"CSV를 찾을 수 없어요: {args.csv_path}")

    # 시군구코드 → 법정동 → 가격 목록
    data = defaultdict(lambda: defaultdict(list))
    region_name = {}
    skipped = 0
    total = 0

    with open(args.csv_path, encoding=args.encoding, errors="replace", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        idx = guess_columns(header)

        missing = [k for k in ("eupmyeondong", "price") if k not in idx]
        if missing:
            sys.exit(f"필수 컬럼을 못 찾았어요: {missing}\n헤더: {header}")

        for row in reader:
            total += 1
            try:
                # 유형 필터 (연립·다세대만)
                if "type" in idx:
                    t = row[idx["type"]].strip()
                    if not any(k in t for k in TARGET_TYPES):
                        skipped += 1
                        continue

                price = to_int(row[idx["price"]])
                if not price or price <= 0:
                    skipped += 1
                    continue

                r5 = sigungu_code(row, idx)
                if not r5:
                    skipped += 1
                    continue

                dong = row[idx["eupmyeondong"]].strip()
                if not dong:
                    skipped += 1
                    continue

                data[r5][dong].append(price)

                if r5 not in region_name and "sigungu" in idx:
                    region_name[r5] = row[idx["sigungu"]].strip()
            except (IndexError, ValueError):
                skipped += 1

    os.makedirs(OUT_DIR, exist_ok=True)
    index = []

    # 좌표 캐시 (재실행 시 API 호출 절약)
    coord_cache = {}
    if os.path.exists(COORD_CACHE):
        try:
            coord_cache = json.load(open(COORD_CACHE, encoding="utf-8"))
        except Exception:
            coord_cache = {}
    if args.kakao_key:
        print("카카오 지오코딩 사용 — 동네 좌표를 조회합니다(네이버 딥링크용).")
    else:
        print("※ --kakao-key 없음 → 좌표를 넣지 않습니다. 네이버 딥링크 대신 검색 안내로 동작합니다.")

    for r5, dongs in data.items():
        areas = []
        region_label = region_name.get(r5, "")
        for dong, prices in dongs.items():
            if len(prices) < 5:  # 표본이 너무 적으면 평균이 의미 없음
                continue
            prices.sort()
            n = len(prices)
            entry = {
                "dong": dong,
                "count": n,
                "avg": int(mean(prices)),
                "median": int(median(prices)),
                "p25": prices[n // 4],
                "p75": prices[(n * 3) // 4],
                "min": prices[0],
                "max": prices[-1],
                "hist": build_hist(prices),
            }
            c = geocode_kakao(f"{region_label} {dong}".strip(), args.kakao_key, coord_cache)
            if c:
                entry["lat"] = c["lat"]
                entry["lon"] = c["lon"]
            areas.append(entry)
        if not areas:
            continue
        areas.sort(key=lambda a: -a["count"])

        payload = {
            "region": region_name.get(r5, r5),
            "code": r5,
            "priceYear": args.year,
            "binSize": BIN_SIZE,
            "binMax": BIN_MAX,
            "types": list(TARGET_TYPES),
            "totalCount": sum(a["count"] for a in areas),
            "areas": areas,
        }
        with open(os.path.join(OUT_DIR, f"{r5}.json"), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

        # 구(시군구) 전체 히스토그램 — 시도 화면에서 구별 등급을 매기는 데 쓴다
        all_prices = sorted(p for ps in dongs.values() for p in ps)
        n_all = len(all_prices)
        gu_coord = geocode_kakao(payload["region"], args.kakao_key, coord_cache)
        index.append({
            "code": r5,
            "sido": r5[:2],
            "region": payload["region"],
            **({"lat": gu_coord["lat"], "lon": gu_coord["lon"]} if gu_coord else {}),
            "short": payload["region"].split()[-1] if payload["region"] else r5,
            "areaCount": len(areas),
            "count": n_all,
            "avg": int(mean(all_prices)),
            "median": int(median(all_prices)),
            "hist": build_hist(all_prices),
        })

    index.sort(key=lambda x: x["code"])

    # 시도 목록 (법정동코드 앞 2자리)
    sido_names = {}
    for i in index:
        nm = i["region"].split()[0] if i["region"] else i["sido"]
        sido_names.setdefault(i["sido"], nm)
    sido = [{"code": c, "name": n} for c, n in sorted(sido_names.items())]

    with open(os.path.join(OUT_DIR, "_index.json"), "w", encoding="utf-8") as f:
        json.dump({
            "priceYear": args.year,
            "binSize": BIN_SIZE,
            "binMax": BIN_MAX,
            "sido": sido,
            "regions": index,
        }, f, ensure_ascii=False, separators=(",", ":"))

    if coord_cache:
        json.dump(coord_cache, open(COORD_CACHE, "w", encoding="utf-8"), ensure_ascii=False)
    n_coord = sum(1 for v in coord_cache.values() if v)
    print(f"입력 {total:,}행 / 제외 {skipped:,}행 (아파트·오피스텔·결측)")
    if args.kakao_key:
        print(f"좌표 확보: {n_coord}/{len(coord_cache)}건")
    print(f"시군구 {len(index)}개, 동네 {sum(i['areaCount'] for i in index)}개 생성 → {OUT_DIR}/")
    for i in index[:10]:
        print(f"  {i['code']} {i['region']}: {i['areaCount']}개 동네, {i['count']:,}세대")


if __name__ == "__main__":
    main()
