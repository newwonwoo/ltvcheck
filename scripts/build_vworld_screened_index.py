from __future__ import annotations

import io
import json
import os
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "research_output/public_price_2025"
OUT_CSV = OUT_DIR / "legal_dong_counts.csv"
OUT_META = OUT_DIR / "screened_index_metadata.json"
CODE_URL = os.getenv(
    "LEGAL_CODE_URL",
    "https://raw.githubusercontent.com/kimyejoon/K-Bjd-OpenLib/main/raw_data/bjd_code_20250805.csv",
)
ENDPOINT = os.getenv("VWORLD_RESEARCH_ENDPOINT", "https://ltvcheck.vercel.app/api/vworld-page")
YEAR = "2025"
SEED = 20250712
CANDIDATES_PER_REGION = int(os.getenv("CANDIDATES_PER_REGION", "150"))
MIN_TOTAL_UNITS = int(os.getenv("MIN_TOTAL_UNITS", "100"))
MAX_TOTAL_UNITS = int(os.getenv("MAX_TOTAL_UNITS", "200000"))
REGIONS = ["서울", "수도권(경기·인천)", "지방"]


def region_group(name: str) -> str:
    if name.startswith("서울특별시"):
        return "서울"
    if name.startswith("경기도") or name.startswith("인천광역시"):
        return "수도권(경기·인천)"
    return "지방"


def read_code_frame() -> pd.DataFrame:
    response = requests.get(CODE_URL, timeout=60)
    response.raise_for_status()
    raw = response.content
    last_error = None
    for encoding in ("utf-8-sig", "utf-8", "cp949"):
        try:
            frame = pd.read_csv(io.BytesIO(raw), dtype=str, encoding=encoding)
            break
        except UnicodeDecodeError as exc:
            last_error = exc
    else:
        raise RuntimeError(f"legal-code CSV decode failed: {last_error}")

    required = {"법정동코드", "법정동명", "폐지여부"}
    if not required.issubset(frame.columns):
        raise RuntimeError(f"unexpected legal-code columns: {list(frame.columns)}")

    frame = frame[list(required)].rename(
        columns={"법정동코드": "legal_code", "법정동명": "legal_name", "폐지여부": "status"}
    )
    frame["legal_code"] = frame["legal_code"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(10)
    frame["legal_name"] = frame["legal_name"].fillna("").str.strip()
    frame["last_token"] = frame["legal_name"].str.split().str[-1].fillna("")

    # 시·군·구 및 읍·면 집계코드는 제외하고 실제 법정동/리 leaf 코드만 사용한다.
    leaf = frame[
        frame["status"].eq("존재")
        & frame["legal_code"].str.len().eq(10)
        & ~frame["legal_code"].str.endswith("00000")
        & frame["last_token"].str.contains(r"(동|가|리|로)$", regex=True, na=False)
    ].copy()
    leaf["region_group"] = leaf["legal_name"].map(region_group)
    leaf = leaf.drop_duplicates("legal_code").reset_index(drop=True)
    return leaf


def fetch_total(code: str, attempts: int = 8) -> dict:
    params = {"pnu": code, "year": YEAR, "page": 1, "rows": 1}
    last_error = None
    for attempt in range(attempts):
        try:
            response = requests.get(ENDPOINT, params=params, timeout=60)
            if response.status_code == 200:
                payload = response.json()
                if payload.get("ok"):
                    return {
                        "legal_code": code,
                        "total_units": int(payload.get("totalCount", 0) or 0),
                        "screen_ok": True,
                        "screen_error": "",
                    }
                last_error = RuntimeError(str(payload))
            else:
                last_error = RuntimeError(f"HTTP {response.status_code}: {response.text[:200]}")
        except Exception as exc:
            last_error = exc
        time.sleep(min(30, 2**attempt))
    return {
        "legal_code": code,
        "total_units": 0,
        "screen_ok": False,
        "screen_error": f"{type(last_error).__name__}: {last_error}",
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    frame = read_code_frame()
    selected_parts = []
    selection_meta = []

    for region_index, region in enumerate(REGIONS):
        region_frame = frame[frame["region_group"] == region].sort_values("legal_code").copy()
        n_screen = min(CANDIDATES_PER_REGION, len(region_frame))
        rng = random.Random(SEED + region_index * 1000)
        positions = sorted(rng.sample(range(len(region_frame)), n_screen))
        selected = region_frame.iloc[positions].copy()
        selected["frame_population_dongs"] = len(region_frame)
        selected["frame_screened_dongs"] = n_screen
        selected["frame_sampling_probability"] = n_screen / len(region_frame)
        selected["frame_weight"] = len(region_frame) / n_screen
        selected_parts.append(selected)
        selection_meta.append(
            {
                "region_group": region,
                "active_leaf_legal_dongs": int(len(region_frame)),
                "screened_dongs": int(n_screen),
                "stage1_probability": float(n_screen / len(region_frame)),
            }
        )

    screened = pd.concat(selected_parts, ignore_index=True)
    results = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(fetch_total, code): code for code in screened["legal_code"]}
        for future in as_completed(futures):
            results.append(future.result())

    result_frame = pd.DataFrame(results)
    screened = screened.merge(result_frame, on="legal_code", how="left", validate="one_to_one")
    eligible = screened[
        screened["screen_ok"].fillna(False)
        & screened["total_units"].between(MIN_TOTAL_UNITS, MAX_TOTAL_UNITS, inclusive="both")
    ].copy()
    eligible = eligible[
        [
            "legal_code",
            "legal_name",
            "region_group",
            "total_units",
            "frame_population_dongs",
            "frame_screened_dongs",
            "frame_sampling_probability",
            "frame_weight",
        ]
    ].sort_values(["region_group", "total_units", "legal_code"])

    counts = eligible.groupby("region_group").size().to_dict()
    missing_regions = [region for region in REGIONS if counts.get(region, 0) < 9]
    if missing_regions:
        raise RuntimeError(
            f"too few eligible screened dongs for {missing_regions}; counts={counts}. "
            "Increase CANDIDATES_PER_REGION or adjust total-unit bounds."
        )

    eligible.to_csv(OUT_CSV, index=False)
    screened.to_csv(OUT_DIR / "screened_legal_dong_candidates.csv", index=False)
    metadata = {
        "source": CODE_URL,
        "source_role": "법정동 후보 목록만 사용; 가격·면적·주택유형은 VWorld 공식 API 사용",
        "vworld_endpoint": ENDPOINT,
        "year": YEAR,
        "seed": SEED,
        "candidate_sampling": selection_meta,
        "screened_total": int(len(screened)),
        "screen_success": int(screened["screen_ok"].fillna(False).sum()),
        "eligible_total": int(len(eligible)),
        "eligible_by_region": {key: int(value) for key, value in counts.items()},
        "eligibility": {
            "min_communal_housing_units": MIN_TOTAL_UNITS,
            "max_communal_housing_units": MAX_TOTAL_UNITS,
            "reason_for_upper_bound": "API 호출량 통제; 표본 결과의 외삽 한계로 명시",
        },
    }
    OUT_META.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
