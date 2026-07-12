from __future__ import annotations

import csv
import gzip
import json
import math
import os
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "research_output/public_price_2025/legal_dong_counts.csv"
OUT = ROOT / "research_output/public_price_2025/vworld_sample"
RAW = OUT / "vworld_villa_sample.csv.gz"
BASE_URL = os.getenv("VWORLD_RESEARCH_ENDPOINT", "https://ltvcheck.vercel.app/api/vworld-page")
YEAR = "2025"
ROWS_PER_PAGE = 1000
SEED = 20250712
THRESHOLDS = [100_000_000, round(200_000_000 / 1.26), 200_000_000, 300_000_000]
AREA_BINS = [-np.inf, 30, 45, 60, 85, np.inf]
AREA_LABELS = ["01_~30", "02_30~45", "03_45~60", "04_60~85", "05_85~"]
REGIONS = ["서울", "수도권(경기·인천)", "지방"]


def weighted_mean(values, weights):
    v = np.asarray(values, dtype=float)
    w = np.asarray(weights, dtype=float)
    mask = np.isfinite(v) & np.isfinite(w) & (w > 0)
    if not mask.any():
        return None
    return float(np.sum(v[mask] * w[mask]) / np.sum(w[mask]))


def weighted_quantile(values, weights, quantile):
    v = np.asarray(values, dtype=float)
    w = np.asarray(weights, dtype=float)
    mask = np.isfinite(v) & np.isfinite(w) & (w > 0)
    if not mask.any():
        return None
    v, w = v[mask], w[mask]
    order = np.argsort(v)
    v, w = v[order], w[order]
    cumulative = np.cumsum(w) - 0.5 * w
    cumulative /= np.sum(w)
    return float(np.interp(quantile, cumulative, v))


def safe_div(a, b):
    return None if b in (0, None) or not np.isfinite(b) else float(a / b)


def json_clean(value):
    if isinstance(value, dict):
        return {str(k): json_clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_clean(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not np.isfinite(value) else round(float(value), 8)
    if pd.isna(value) if not isinstance(value, (str, bool)) else False:
        return None
    return value


def choose_sample(index: pd.DataFrame, target_per_stratum=4, page_budget=1200):
    eligible = index[(index["total_units"] >= 100) & index["legal_code"].astype(str).str.len().ge(10)].copy()
    eligible["legal_code"] = eligible["legal_code"].astype(str).str[:10]
    selections = []
    strata_meta = []
    region_seed = {name: i for i, name in enumerate(REGIONS)}

    def build(target):
        chosen, meta = [], []
        for region in REGIONS:
            part = eligible[eligible["region_group"] == region].sort_values(["total_units", "legal_code"]).copy()
            if part.empty:
                continue
            part["rank_pct"] = (np.arange(len(part)) + 0.5) / len(part)
            part["size_stratum"] = pd.cut(
                part["rank_pct"], bins=[0, 1 / 3, 2 / 3, 1], labels=["low", "mid", "high"], include_lowest=True
            ).astype(str)
            for s_idx, stratum in enumerate(["low", "mid", "high"]):
                frame = part[part["size_stratum"] == stratum].copy()
                n_take = min(target, len(frame))
                rng = random.Random(SEED + region_seed[region] * 100 + s_idx)
                positions = sorted(rng.sample(range(len(frame)), n_take)) if n_take else []
                sample = frame.iloc[positions].copy()
                probability = n_take / len(frame) if len(frame) else 0
                sample["sampling_probability"] = probability
                sample["sampling_weight"] = 1 / probability if probability else np.nan
                chosen.append(sample)
                meta.append(
                    {
                        "region_group": region,
                        "size_stratum": stratum,
                        "population_dongs": int(len(frame)),
                        "sampled_dongs": int(n_take),
                        "sampling_probability": probability,
                        "min_units": int(frame["total_units"].min()) if len(frame) else None,
                        "max_units": int(frame["total_units"].max()) if len(frame) else None,
                    }
                )
        return pd.concat(chosen, ignore_index=True), meta

    target = target_per_stratum
    while True:
        sample, metadata = build(target)
        expected_pages = int(np.ceil(sample["total_units"] / ROWS_PER_PAGE).sum())
        if expected_pages <= page_budget or target <= 2:
            selections, strata_meta = sample, metadata
            break
        target -= 1
    selections["expected_pages_from_csv"] = np.ceil(selections["total_units"] / ROWS_PER_PAGE).astype(int)
    return selections.sort_values(["region_group", "size_stratum", "legal_code"]), strata_meta, expected_pages, target


def fetch_json(params, attempts=8):
    last = None
    for attempt in range(attempts):
        try:
            response = requests.get(BASE_URL, params=params, timeout=60)
            if response.status_code == 200:
                payload = response.json()
                if payload.get("ok"):
                    return payload
                last = RuntimeError(str(payload))
            else:
                last = RuntimeError(f"HTTP {response.status_code}: {response.text[:200]}")
        except Exception as exc:
            last = exc
        time.sleep(min(30, 2 ** attempt))
    raise RuntimeError(f"fetch failed params={params}: {last}")


def fetch_dong_first(row):
    code = str(row.legal_code)[:10]
    payload = fetch_json({"pnu": code, "year": YEAR, "page": 1, "rows": ROWS_PER_PAGE, "villa": 1})
    return code, payload


def fetch_page(code, page):
    payload = fetch_json({"pnu": code, "year": YEAR, "page": page, "rows": ROWS_PER_PAGE, "villa": 1})
    return code, page, payload


def collect(sample: pd.DataFrame):
    first_pages = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(fetch_dong_first, row): str(row.legal_code) for row in sample.itertuples()}
        for future in as_completed(futures):
            code, payload = future.result()
            first_pages[code] = payload

    tasks = []
    audit = []
    records = []
    for row in sample.itertuples():
        code = str(row.legal_code)[:10]
        payload = first_pages[code]
        total = int(payload.get("totalCount", 0))
        pages = math.ceil(total / ROWS_PER_PAGE)
        for item in payload.get("fields", []):
            item["sample_legal_code"] = code
            records.append(item)
        for page in range(2, pages + 1):
            tasks.append((code, page))
        audit.append(
            {
                "legal_code": code,
                "legal_name": row.legal_name,
                "region_group": row.region_group,
                "size_stratum": row.size_stratum,
                "csv_total_units": int(row.total_units),
                "api_total_units": total,
                "pages": pages,
                "sampling_probability": float(row.sampling_probability),
                "sampling_weight": float(row.sampling_weight),
                "page1_villas": int(payload.get("returnedCount", 0)),
            }
        )

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(fetch_page, code, page): (code, page) for code, page in tasks}
        for future in as_completed(futures):
            code, page, payload = future.result()
            for item in payload.get("fields", []):
                item["sample_legal_code"] = code
                records.append(item)

    return records, pd.DataFrame(audit)


def prepare(records, sample, audit):
    df = pd.DataFrame(records)
    if df.empty:
        raise RuntimeError("No villa records returned")
    for col in ["prvuseAr", "pblntfPc"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["legal_code"] = df.get("ldCode", df["sample_legal_code"]).astype(str).str[:10]
    df["legal_name"] = df.get("ldCodeNm", "")
    df["housing_type"] = df["aphusSeCode"].astype(str).map({"3": "연립", "5": "다세대"})
    df = df[df["housing_type"].notna() & (df["prvuseAr"] > 0) & (df["pblntfPc"] > 0)].copy()
    df.rename(columns={"prvuseAr": "area", "pblntfPc": "price"}, inplace=True)
    df["unit_price"] = df["price"] / df["area"]
    df["area_bin"] = pd.cut(df["area"], bins=AREA_BINS, labels=AREA_LABELS, right=True).astype(str)

    weights = sample[["legal_code", "region_group", "size_stratum", "sampling_probability", "sampling_weight"]].copy()
    weights["legal_code"] = weights["legal_code"].astype(str).str[:10]
    df = df.merge(weights, on="legal_code", how="left", validate="many_to_one")

    dedupe_cols = [
        "legal_code", "pnu", "aphusCode", "dongNm", "floorNm", "hoNm", "area", "price", "aphusSeCode"
    ]
    before = len(df)
    df = df.drop_duplicates(subset=[c for c in dedupe_cols if c in df.columns]).copy()
    duplicate_rows_removed = before - len(df)

    villa_counts = df.groupby("legal_code").size().rename("villa_units")
    audit = audit.merge(villa_counts, on="legal_code", how="left")
    audit["villa_units"] = audit["villa_units"].fillna(0).astype(int)
    return df, audit, duplicate_rows_removed


def group_stats(df):
    rows = []
    for code, g in df.groupby("legal_code"):
        if len(g) < 5:
            continue
        up = g["unit_price"].to_numpy(float)
        q10, q25, q50, q75, q90 = np.quantile(up, [0.1, 0.25, 0.5, 0.75, 0.9])
        rows.append(
            {
                "legal_code": code,
                "legal_name": g["legal_name"].iloc[0],
                "region_group": g["region_group"].iloc[0],
                "size_stratum": g["size_stratum"].iloc[0],
                "sampling_weight": g["sampling_weight"].iloc[0],
                "n": len(g),
                "mean_unit_price": np.mean(up),
                "median_unit_price": q50,
                "cv": np.std(up, ddof=0) / np.mean(up),
                "p10": q10,
                "p25": q25,
                "p75": q75,
                "p90": q90,
                "iqr": q75 - q25,
                "p10_p90_width": q90 - q10,
                "p90_p10_ratio": q90 / q10 if q10 > 0 else np.nan,
            }
        )
    return pd.DataFrame(rows)


def summarize_q1(gs):
    output = []
    for region in REGIONS + ["전국"]:
        g = gs if region == "전국" else gs[gs["region_group"] == region]
        if g.empty:
            continue
        w = g["sampling_weight"].to_numpy(float)
        output.append(
            {
                "region_group": region,
                "sampled_eligible_dongs": len(g),
                "villa_households": int(g["n"].sum()),
                "weighted_median_cv": weighted_quantile(g["cv"], w, 0.5),
                "weighted_p25_cv": weighted_quantile(g["cv"], w, 0.25),
                "weighted_p75_cv": weighted_quantile(g["cv"], w, 0.75),
                "weighted_share_cv_lt_0_2": weighted_mean((g["cv"] < 0.2).astype(float), w),
                "weighted_share_cv_ge_0_4": weighted_mean((g["cv"] >= 0.4).astype(float), w),
                "weighted_median_iqr_to_median": weighted_quantile(g["iqr"] / g["median_unit_price"], w, 0.5),
                "weighted_median_p10p90_to_median": weighted_quantile(g["p10_p90_width"] / g["median_unit_price"], w, 0.5),
                "weighted_median_p90_p10_ratio": weighted_quantile(g["p90_p10_ratio"], w, 0.5),
                "household_weighted_mean_cv": weighted_mean(g["cv"], w * g["n"]),
            }
        )
    return output


def summarize_q2(df):
    bins = []
    regressions = []
    for region in REGIONS + ["전국"]:
        g = df if region == "전국" else df[df["region_group"] == region]
        if g.empty:
            continue
        for label in AREA_LABELS:
            b = g[g["area_bin"] == label]
            if b.empty:
                continue
            bins.append(
                {
                    "region_group": region,
                    "area_bin": label,
                    "n": len(b),
                    "weighted_mean_area": weighted_mean(b["area"], b["sampling_weight"]),
                    "weighted_mean_unit_price": weighted_mean(b["unit_price"], b["sampling_weight"]),
                    "weighted_median_unit_price": weighted_quantile(b["unit_price"], b["sampling_weight"], 0.5),
                }
            )
        x, y, w = g["area"].to_numpy(float), g["unit_price"].to_numpy(float), g["sampling_weight"].to_numpy(float)
        x_mean, y_mean = weighted_mean(x, w), weighted_mean(y, w)
        pooled_slope = np.sum(w * (x - x_mean) * (y - y_mean)) / np.sum(w * (x - x_mean) ** 2)
        pooled_corr = np.sum(w * (x - x_mean) * (y - y_mean)) / math.sqrt(
            np.sum(w * (x - x_mean) ** 2) * np.sum(w * (y - y_mean) ** 2)
        )
        demeaned = []
        for _, d in g.groupby("legal_code"):
            demeaned.append(
                pd.DataFrame(
                    {
                        "dx": d["area"] - d["area"].mean(),
                        "dy": d["unit_price"] - d["unit_price"].mean(),
                        "w": d["sampling_weight"],
                    }
                )
            )
        dm = pd.concat(demeaned, ignore_index=True)
        fe_slope = np.sum(dm["w"] * dm["dx"] * dm["dy"]) / np.sum(dm["w"] * dm["dx"] ** 2)
        fe_corr = np.sum(dm["w"] * dm["dx"] * dm["dy"]) / math.sqrt(
            np.sum(dm["w"] * dm["dx"] ** 2) * np.sum(dm["w"] * dm["dy"] ** 2)
        )
        regressions.append(
            {
                "region_group": region,
                "n": len(g),
                "pooled_slope_won_per_m2_unitprice_per_extra_m2": pooled_slope,
                "pooled_corr": pooled_corr,
                "legal_dong_fixed_effect_slope": fe_slope,
                "legal_dong_fixed_effect_corr": fe_corr,
            }
        )
    return bins, regressions


def add_predictions(df):
    d = df.copy()
    dong = d.groupby("legal_code").agg(dong_med=("unit_price", "median"), dong_mean=("unit_price", "mean"))
    area = d.groupby(["legal_code", "area_bin"])["unit_price"].agg([("area_med", "median"), ("area_n", "size")])
    typ = d.groupby(["legal_code", "housing_type"])["unit_price"].agg([("type_med", "median"), ("type_n", "size")])
    ta = d.groupby(["legal_code", "housing_type", "area_bin"])["unit_price"].agg([("ta_med", "median"), ("ta_n", "size")])
    d = d.merge(dong, on="legal_code", how="left")
    d = d.merge(area, on=["legal_code", "area_bin"], how="left")
    d = d.merge(typ, on=["legal_code", "housing_type"], how="left")
    d = d.merge(ta, on=["legal_code", "housing_type", "area_bin"], how="left")
    d["pred_single_median"] = d["dong_med"] * d["area"]
    d["pred_single_mean"] = d["dong_mean"] * d["area"]
    d["pred_area"] = np.where(d["area_n"] >= 5, d["area_med"], d["dong_med"]) * d["area"]
    d["pred_type"] = np.where(d["type_n"] >= 5, d["type_med"], d["dong_med"]) * d["area"]
    fallback_ta = np.where(d["area_n"] >= 5, d["area_med"], np.where(d["type_n"] >= 5, d["type_med"], d["dong_med"]))
    d["pred_type_area"] = np.where(d["ta_n"] >= 5, d["ta_med"], fallback_ta) * d["area"]
    return d


def weighted_error_metrics(g, pred, threshold):
    w = g["sampling_weight"].to_numpy(float)
    actual = g["price"].to_numpy(float)
    estimate = g[pred].to_numpy(float)
    ape = np.abs(estimate - actual) / actual
    actual_pass = actual >= threshold
    predicted_pass = estimate >= threshold
    mismatch = actual_pass != predicted_pass
    return {
        "n": len(g),
        "mape": weighted_mean(ape, w),
        "median_ape": weighted_quantile(ape, w, 0.5),
        "p90_ape": weighted_quantile(ape, w, 0.9),
        "overall_misclassification": weighted_mean(mismatch.astype(float), w),
        "false_negative_rate": weighted_mean((~predicted_pass[actual_pass]).astype(float), w[actual_pass]) if actual_pass.any() else None,
        "false_positive_rate": weighted_mean(predicted_pass[~actual_pass].astype(float), w[~actual_pass]) if (~actual_pass).any() else None,
    }


def summarize_q3(pred):
    models = [
        ("동네 중위단가 1개", "pred_single_median", 1),
        ("동네 평균단가 1개", "pred_single_mean", 1),
        ("동네×면적 5구간", "pred_area", 5),
        ("동네×주택유형", "pred_type", 2),
        ("동네×주택유형×면적 5구간", "pred_type_area", 10),
    ]
    output = []
    for model, column, numbers in models:
        for region in REGIONS + ["전국"]:
            g = pred if region == "전국" else pred[pred["region_group"] == region]
            if g.empty:
                continue
            for threshold in THRESHOLDS:
                row = weighted_error_metrics(g, column, threshold)
                row.update(
                    {
                        "model": model,
                        "region_group": region,
                        "threshold": threshold,
                        "stored_unit_price_numbers_per_dong": numbers,
                    }
                )
                output.append(row)
    return output


def grade(share):
    if share >= 0.75:
        return "A"
    if share >= 0.50:
        return "B"
    if share >= 0.25:
        return "C"
    return "D"


def summarize_q4(pred):
    dong_quantiles = pred.groupby("legal_code")["price"].quantile([0.25, 0.5, 0.75]).unstack()
    dong_quantiles.columns = ["p25", "p50", "p75"]
    dong_meta = pred.groupby("legal_code").agg(
        region_group=("region_group", "first"), sampling_weight=("sampling_weight", "first"), n=("price", "size")
    )
    base = dong_meta.join(dong_quantiles)
    rows = []
    histogram_rows = []
    storage_bins = []
    for code, g in pred.groupby("legal_code"):
        bins = np.floor(g["price"].to_numpy(float) / 10_000_000).astype(int)
        storage_bins.append(len(np.unique(bins)))
    for threshold in THRESHOLDS:
        per_dong = []
        for code, g in pred.groupby("legal_code"):
            true_share = float(np.mean(g["price"] >= threshold))
            base_share = float(np.mean(g["pred_single_median"] >= threshold))
            area_share = float(np.mean(g["pred_area"] >= threshold))
            ta_share = float(np.mean(g["pred_type_area"] >= threshold))
            q = base.loc[code]
            q_grade = "A" if threshold <= q.p25 else "B" if threshold <= q.p50 else "C" if threshold <= q.p75 else "D"
            prices = g["price"].to_numpy(float)
            lower = np.floor(prices / 10_000_000) * 10_000_000
            unique, counts = np.unique(lower, return_counts=True)
            estimated_pass = 0.0
            for lo, count in zip(unique, counts):
                hi = lo + 10_000_000
                if lo >= threshold:
                    estimated_pass += count
                elif hi <= threshold:
                    pass
                else:
                    estimated_pass += count * (hi - threshold) / 10_000_000
            hist_share = estimated_pass / len(prices)
            per_dong.append(
                {
                    "legal_code": code,
                    "region_group": g["region_group"].iloc[0],
                    "weight": g["sampling_weight"].iloc[0],
                    "true_share": true_share,
                    "base_share": base_share,
                    "area_share": area_share,
                    "type_area_share": ta_share,
                    "hist_share": hist_share,
                    "true_grade": grade(true_share),
                    "base_grade": grade(base_share),
                    "area_grade": grade(area_share),
                    "type_area_grade": grade(ta_share),
                    "quantile_grade": q_grade,
                    "hist_grade": grade(hist_share),
                }
            )
        p = pd.DataFrame(per_dong)
        for region in REGIONS + ["전국"]:
            g = p if region == "전국" else p[p["region_group"] == region]
            if g.empty:
                continue
            w = g["weight"]
            rows.append(
                {
                    "region_group": region,
                    "threshold": threshold,
                    "sampled_dongs": len(g),
                    "single_unit_price_grade_misclassification": weighted_mean((g["base_grade"] != g["true_grade"]).astype(float), w),
                    "area_bin_grade_misclassification": weighted_mean((g["area_grade"] != g["true_grade"]).astype(float), w),
                    "type_area_grade_misclassification": weighted_mean((g["type_area_grade"] != g["true_grade"]).astype(float), w),
                    "p25_p50_p75_grade_misclassification": weighted_mean((g["quantile_grade"] != g["true_grade"]).astype(float), w),
                    "histogram_grade_misclassification": weighted_mean((g["hist_grade"] != g["true_grade"]).astype(float), w),
                    "single_share_mae": weighted_mean(np.abs(g["base_share"] - g["true_share"]), w),
                    "area_bin_share_mae": weighted_mean(np.abs(g["area_share"] - g["true_share"]), w),
                    "type_area_share_mae": weighted_mean(np.abs(g["type_area_share"] - g["true_share"]), w),
                    "histogram_share_mae": weighted_mean(np.abs(g["hist_share"] - g["true_share"]), w),
                }
            )
        histogram_rows.extend(per_dong)
    storage = {
        "one_unit_price": 1,
        "area_bins_unit_lookup": 5,
        "area_bins_with_counts_for_neighborhood_grade": 10,
        "p25_p50_p75": 3,
        "type_area_unit_lookup": 10,
        "histogram_nonempty_bins_mean": float(np.mean(storage_bins)),
        "histogram_nonempty_bins_median": float(np.median(storage_bins)),
        "histogram_nonempty_bins_p90": float(np.quantile(storage_bins, 0.9)),
        "histogram_nonempty_bins_max": int(np.max(storage_bins)),
    }
    return rows, storage, pd.DataFrame(histogram_rows)


def sensitivity_q1(df):
    lo, hi = df["unit_price"].quantile([0.001, 0.999])
    trimmed = df[df["unit_price"].between(lo, hi)].copy()
    gs = group_stats(trimmed)
    return {"trim_bounds": [lo, hi], "q1": summarize_q1(gs)}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    index = pd.read_csv(INDEX, dtype={"legal_code": str})
    sample, strata_meta, expected_pages, target = choose_sample(index)
    sample.to_csv(OUT / "sampled_legal_dongs.csv", index=False)

    records, audit = collect(sample)
    df, audit, duplicates = prepare(records, sample, audit)
    audit.to_csv(OUT / "collection_audit.csv", index=False)
    df.to_csv(RAW, index=False, compression="gzip")

    eligible_counts = df.groupby("legal_code").size()
    eligible_codes = eligible_counts[eligible_counts >= 5].index
    analysis_df = df[df["legal_code"].isin(eligible_codes)].copy()
    gs = group_stats(analysis_df)
    gs.to_csv(OUT / "q1_legal_dong_stats.csv", index=False)

    q1 = summarize_q1(gs)
    q2_bins, q2_reg = summarize_q2(analysis_df)
    pred = add_predictions(analysis_df)
    q3 = summarize_q3(pred)
    q4, storage, q4_dong = summarize_q4(pred)
    q4_dong.to_csv(OUT / "q4_dong_threshold_details.csv", index=False)

    result = {
        "source": {
            "official_csv": "국토교통부_주택 공시가격 정보_20250626",
            "official_csv_reference_date": "2025-01-01",
            "official_csv_rows": 15_580_435,
            "vworld_endpoint": "getApartHousingPriceAttr",
            "vworld_year": YEAR,
            "villa_type_codes": {"3": "연립", "5": "다세대"},
        },
        "sample_design": {
            "method": "서울/경기·인천/지방 × 각 지역 법정동 공동주택 총호수 순위 3분위 층화 단순무작위",
            "seed": SEED,
            "target_per_region_size_stratum": target,
            "selected_dongs": len(sample),
            "expected_api_pages_from_csv": expected_pages,
            "actual_api_pages": int(audit["pages"].sum()),
            "strata": strata_meta,
            "sampled_dongs_with_at_least_5_villas": int(len(eligible_codes)),
            "villa_rows_before_n5_filter": int(len(df)),
            "villa_rows_analyzed": int(len(analysis_df)),
            "duplicates_removed": int(duplicates),
            "excluded_dongs_under_5_villas": int((audit["villa_units"] < 5).sum()),
        },
        "cleaning": {
            "excluded": ["전용면적<=0", "공시가격<=0", "주택유형코드가 3·5가 아님", "법정동 내 연립·다세대 5호 미만"],
            "main_outlier_policy": "상단 절단 없음",
            "sensitivity": "전체 표본 단가 0.1~99.9% 범위만 남긴 Q1 별도 계산",
        },
        "q1": q1,
        "q1_sensitivity": sensitivity_q1(analysis_df),
        "q2_area_bins": q2_bins,
        "q2_regression": q2_reg,
        "q3_unit_level": q3,
        "q4_neighborhood_grade": q4,
        "q4_storage": storage,
        "definitions": {
            "cv_interpretation": {"practical": "CV<0.2", "caution": "0.2<=CV<0.4", "unsuitable": "CV>=0.4"},
            "grades": {"A": "충족비율>=75%", "B": "50~75%", "C": "25~50%", "D": "<25%"},
            "thresholds": THRESHOLDS,
            "area_bins_m2": AREA_LABELS,
        },
    }
    (OUT / "summary.json").write_text(json.dumps(json_clean(result), ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
