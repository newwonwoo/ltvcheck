from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "research_output/public_price_2025"
SOURCE = BASE / "vworld_sample/summary.json"
META = BASE / "screened_index_metadata.json"
OUT_JSON = BASE / "vworld_sample/key_results.json"
OUT_MD = BASE / "vworld_sample/research_report.md"
TARGET = 158_730_159


def pct(value):
    return "-" if value is None else f"{value * 100:.1f}%"


def won_m2(value):
    return "-" if value is None else f"{value / 10_000:.1f}만원/㎡"


def num(value):
    return f"{value:,}" if isinstance(value, int) else str(value)


def md_table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    out.extend("| " + " | ".join(str(v) for v in row) + " |" for row in rows)
    return "\n".join(out)


def main():
    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    meta = json.loads(META.read_text(encoding="utf-8")) if META.exists() else {}

    q3_target = [r for r in data["q3_unit_level"] if r["threshold"] == TARGET]
    q3_national = [r for r in q3_target if r["region_group"] == "전국"]
    q4_target = [r for r in data["q4_neighborhood_grade"] if r["threshold"] == TARGET]

    best_by_region = {}
    for region in ["서울", "수도권(경기·인천)", "지방", "전국"]:
        rows = [r for r in q3_target if r["region_group"] == region]
        if rows:
            best_by_region[region] = min(rows, key=lambda r: r["overall_misclassification"])

    compact = {
        "source": data["source"],
        "screened_frame": meta,
        "sample_design": data["sample_design"],
        "cleaning": data["cleaning"],
        "q1": data["q1"],
        "q1_sensitivity": data["q1_sensitivity"],
        "q2_area_bins": data["q2_area_bins"],
        "q2_regression": data["q2_regression"],
        "q3_threshold_158730159": q3_target,
        "q3_national_threshold_158730159": q3_national,
        "q3_best_model_by_region": best_by_region,
        "q4_threshold_158730159": q4_target,
        "q4_storage": data["q4_storage"],
    }
    OUT_JSON.write_text(json.dumps(compact, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# 연립·다세대 공시가격 단가근사 실증 결과",
        "",
        f"- 표본: 선택 {data['sample_design']['selected_dongs']}개 법정동, 분석 가능 {data['sample_design']['sampled_dongs_with_at_least_5_villas']}개 법정동, {data['sample_design']['villa_rows_analyzed']:,}호",
        f"- 설계: {data['sample_design']['method']}",
        f"- 핵심 판정선: {TARGET:,}원(2억원 ÷ 1.26 반올림)",
        "",
        "## Q1. 법정동 단일 단가의 동질성",
        "",
        md_table(
            ["지역", "동 수", "호 수", "CV 중앙", "CV<0.2", "CV≥0.4", "P90/P10 중앙"],
            [
                [r["region_group"], r["sampled_eligible_dongs"], f"{r['villa_households']:,}", f"{r['weighted_median_cv']:.3f}", pct(r["weighted_share_cv_lt_0_2"]), pct(r["weighted_share_cv_ge_0_4"]), f"{r['weighted_median_p90_p10_ratio']:.2f}배"]
                for r in data["q1"]
            ],
        ),
        "",
        "## Q2. 면적 효과",
        "",
        md_table(
            ["지역", "법정동 고정효과 기울기", "고정효과 상관"],
            [
                [r["region_group"], f"{r['legal_dong_fixed_effect_slope']:,.0f}원/㎡당", f"{r['legal_dong_fixed_effect_corr']:.3f}"]
                for r in data["q2_regression"]
            ],
        ),
        "",
        "### 면적구간별 중위 단가",
        "",
        md_table(
            ["지역", "면적구간", "n", "중위 단가"],
            [[r["region_group"], r["area_bin"], f"{r['n']:,}", won_m2(r["weighted_median_unit_price"])] for r in data["q2_area_bins"]],
        ),
        "",
        "## Q3. 1.587억원 판정선의 호별 오분류",
        "",
        md_table(
            ["모형", "지역", "저장값/동", "MAPE", "전체 오분류", "거짓음성", "거짓양성"],
            [
                [r["model"], r["region_group"], r["stored_unit_price_numbers_per_dong"], pct(r["mape"]), pct(r["overall_misclassification"]), pct(r["false_negative_rate"]), pct(r["false_positive_rate"])]
                for r in q3_target
            ],
        ),
        "",
        "## Q4. 동네 A/B/C/D 등급 오분류",
        "",
        md_table(
            ["지역", "단일단가", "면적5구간", "유형×면적", "P25/P50/P75", "1천만원 히스토그램"],
            [
                [r["region_group"], pct(r["single_unit_price_grade_misclassification"]), pct(r["area_bin_grade_misclassification"]), pct(r["type_area_grade_misclassification"]), pct(r["p25_p50_p75_grade_misclassification"]), pct(r["histogram_grade_misclassification"])]
                for r in q4_target
            ],
        ),
        "",
        "### 저장량",
        "",
        "```json",
        json.dumps(data["q4_storage"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## 1.587억원 기준 지역별 최소 오분류 모형",
        "",
        md_table(
            ["지역", "모형", "호별 오분류", "MAPE", "저장값/동"],
            [[region, row["model"], pct(row["overall_misclassification"]), pct(row["mape"]), row["stored_unit_price_numbers_per_dong"]] for region, row in best_by_region.items()],
        ),
    ]
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
