from __future__ import annotations

import csv
import io
import json
import math
import os
import re
import urllib.request
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

DATA_URL = "https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId=FILE_000000003525375&fileDetailSn=1&insertDataPrcus=N"
OUT = Path("research_output")
OUT.mkdir(exist_ok=True)
ZIP_PATH = Path("/tmp/public_price_2025.zip")
THRESHOLDS = [100_000_000, 159_000_000, 200_000_000, 300_000_000]
AREA_BINS = [0, 30, 45, 60, 85, np.inf]
AREA_LABELS = ["~30", "30~45", "45~60", "60~85", "85~"]


def download() -> None:
    if ZIP_PATH.exists() and ZIP_PATH.stat().st_size > 1_000_000:
        return
    req = urllib.request.Request(DATA_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as r, ZIP_PATH.open("wb") as f:
        while True:
            chunk = r.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)
    print("downloaded", ZIP_PATH.stat().st_size)


def norm(s: str) -> str:
    return re.sub(r"[^0-9a-zA-Z가-힣]", "", str(s)).lower()


def choose(columns, candidates, contains=()):
    m = {norm(c): c for c in columns}
    for x in candidates:
        if norm(x) in m:
            return m[norm(x)]
    for c in columns:
        nc = norm(c)
        if all(norm(x) in nc for x in contains):
            return c
    return None


def detect_encoding(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp949", "euc-kr", "utf-8"):
        try:
            raw.decode(enc)
            return enc
        except UnicodeDecodeError:
            pass
    return "utf-8"


def load_filtered() -> tuple[pd.DataFrame, dict]:
    zf = zipfile.ZipFile(ZIP_PATH)
    names = [n for n in zf.namelist() if n.lower().endswith((".csv", ".txt"))]
    if not names:
        raise RuntimeError(f"No CSV/TXT in ZIP: {zf.namelist()[:20]}")
    frames = []
    metadata = {"zip_bytes": ZIP_PATH.stat().st_size, "members": names, "raw_rows": 0, "filtered_rows_before_clean": 0}
    for name in names:
        with zf.open(name) as fh:
            sample = fh.read(65536)
        enc = detect_encoding(sample)
        text = sample.decode(enc, "replace")
        first = text.splitlines()[0]
        sep = "\t" if first.count("\t") > first.count(",") else ","
        cols = next(csv.reader([first], delimiter=sep))
        type_col = choose(cols, ["공동주택구분명", "주택유형", "공동주택구분", "건물종류"], contains=("구분", "명"))
        area_col = choose(cols, ["전용면적", "전용면적(㎡)", "전용면적(m2)", "전용면적(제곱미터)"], contains=("전용", "면적"))
        price_col = choose(cols, ["공동주택가격", "공시가격", "공동주택가격(원)"], contains=("주택", "가격"))
        sido_col = choose(cols, ["시도", "시도명", "광역시도"], contains=("시도",))
        sigungu_col = choose(cols, ["시군구", "시군구명"], contains=("시군구",))
        dong_col = choose(cols, ["법정동", "법정동명"], contains=("법정동",))
        code_col = choose(cols, ["법정동코드", "법정동코드10자리"], contains=("법정동", "코드"))
        if not all([type_col, area_col, price_col, dong_col]):
            raise RuntimeError(f"Column inference failed: {cols}")
        use = [x for x in [type_col, area_col, price_col, sido_col, sigungu_col, dong_col, code_col] if x]
        print("member", name, "encoding", enc, "sep", repr(sep), "columns", {"type":type_col,"area":area_col,"price":price_col,"sido":sido_col,"sigungu":sigungu_col,"dong":dong_col,"code":code_col})
        for chunk in pd.read_csv(zf.open(name), encoding=enc, sep=sep, usecols=use, chunksize=350_000, low_memory=False):
            metadata["raw_rows"] += len(chunk)
            t = chunk[type_col].astype(str).str.strip()
            mask = t.str.contains("연립|다세대", regex=True, na=False)
            sub = chunk.loc[mask].copy()
            metadata["filtered_rows_before_clean"] += len(sub)
            if sub.empty:
                continue
            sub.rename(columns={type_col:"housing_type", area_col:"area", price_col:"price", dong_col:"dong", **({sido_col:"sido"} if sido_col else {}), **({sigungu_col:"sigungu"} if sigungu_col else {}), **({code_col:"dong_code"} if code_col else {})}, inplace=True)
            if "sido" not in sub: sub["sido"] = ""
            if "sigungu" not in sub: sub["sigungu"] = ""
            if "dong_code" not in sub: sub["dong_code"] = ""
            frames.append(sub[["housing_type","area","price","sido","sigungu","dong","dong_code"]])
    if not frames:
        raise RuntimeError("No row-house/multiplex rows found")
    df = pd.concat(frames, ignore_index=True)
    df["area"] = pd.to_numeric(df["area"].astype(str).str.replace(",", "", regex=False), errors="coerce")
    df["price"] = pd.to_numeric(df["price"].astype(str).str.replace(",", "", regex=False), errors="coerce")
    bad_missing = int(df[["area","price"]].isna().any(axis=1).sum())
    bad_nonpositive = int(((df["area"] <= 0) | (df["price"] <= 0)).fillna(True).sum())
    df = df[df["area"].notna() & df["price"].notna() & (df["area"] > 0) & (df["price"] > 0)].copy()
    df["unit_price"] = df["price"] / df["area"]
    # Impossible/unit-conversion mistakes only; retain genuine tails.
    bad_implausible = int(((df["area"] > 500) | (df["unit_price"] < 10_000) | (df["unit_price"] > 100_000_000)).sum())
    df = df[(df["area"] <= 500) & (df["unit_price"] >= 10_000) & (df["unit_price"] <= 100_000_000)].copy()
    df["dong_code"] = df["dong_code"].astype(str).str.replace(r"\.0$", "", regex=True).str.strip()
    df["group"] = np.where(df["dong_code"].str.len() >= 8, df["dong_code"], df["sido"].astype(str)+"|"+df["sigungu"].astype(str)+"|"+df["dong"].astype(str))
    s = df["sido"].astype(str)
    df["region"] = np.select([s.str.contains("서울"), s.str.contains("경기|인천", regex=True)], ["서울", "수도권기타"], default="지방")
    df["area_bin"] = pd.cut(df["area"], AREA_BINS, labels=AREA_LABELS, right=False)
    counts = df.groupby("group").size()
    eligible = counts[counts >= 5].index
    excluded_rows = int((~df["group"].isin(eligible)).sum())
    excluded_dongs = int((counts < 5).sum())
    df = df[df["group"].isin(eligible)].copy()
    metadata.update({"bad_missing":bad_missing,"bad_nonpositive":bad_nonpositive,"bad_implausible":bad_implausible,"excluded_lt5_rows":excluded_rows,"excluded_lt5_dongs":excluded_dongs,"clean_rows":len(df),"clean_dongs":df["group"].nunique()})
    return df, metadata


def q1(df):
    g = df.groupby("group")["unit_price"]
    x = g.agg(n="size", mean="mean", sd="std", p10=lambda s:s.quantile(.1), p25=lambda s:s.quantile(.25), p50="median", p75=lambda s:s.quantile(.75), p90=lambda s:s.quantile(.9)).reset_index()
    x["cv"] = x["sd"] / x["mean"]
    x["iqr_ratio"] = (x["p75"]-x["p25"]) / x["p50"]
    x["p10_p90_ratio_width"] = (x["p90"]-x["p10"]) / x["p50"]
    x["p90_p10_multiple"] = x["p90"] / x["p10"]
    reg = df[["group","region"]].drop_duplicates("group")
    x = x.merge(reg,on="group",how="left")
    metrics = {}
    for name, sub in [("전체",x), *[(r,x[x.region==r]) for r in ["서울","수도권기타","지방"]]]:
        metrics[name] = {"dongs":len(sub),"rows":int(sub.n.sum()),"median_cv":float(sub.cv.median()),"mean_cv":float(sub.cv.mean()),"pct_cv_lt_0_2":float((sub.cv<.2).mean()),"pct_cv_ge_0_4":float((sub.cv>=.4).mean()),"median_iqr_ratio":float(sub.iqr_ratio.median()),"median_p10_p90_ratio_width":float(sub.p10_p90_ratio_width.median()),"median_p90_p10_multiple":float(sub.p90_p10_multiple.median())}
    return x, metrics


def q2(df):
    bins = df.groupby(["region","area_bin"], observed=False).agg(n=("price","size"), mean_unit=("unit_price","mean"), median_unit=("unit_price","median"), mean_price=("price","mean")).reset_index()
    overall = df.groupby("area_bin", observed=False).agg(n=("price","size"), mean_unit=("unit_price","mean"), median_unit=("unit_price","median"), mean_price=("price","mean")).reset_index()
    overall["region"]="전체"; bins=pd.concat([overall,bins],ignore_index=True)
    # Legal-dong fixed-effects slope: within-dong demeaning.
    gx=df.groupby("group")["area"].transform("mean"); gy=df.groupby("group")["unit_price"].transform("mean")
    num=((df.area-gx)*(df.unit_price-gy)).sum(); den=((df.area-gx)**2).sum(); slope=float(num/den)
    logy=np.log(df.unit_price); gly=logy.groupby(df.group).transform("mean")
    log_slope=float(((df.area-gx)*(logy-gly)).sum()/den)
    by_region={}
    for r,s in df.groupby("region"):
        ax=s.groupby("group")["area"].transform("mean"); uy=s.groupby("group")["unit_price"].transform("mean"); ly=np.log(s.unit_price); lym=ly.groupby(s.group).transform("mean"); d=((s.area-ax)**2).sum()
        by_region[r]={"won_per_m2_change_for_1m2":float(((s.area-ax)*(s.unit_price-uy)).sum()/d),"pct_unit_change_for_10m2":float((math.exp(float(((s.area-ax)*(ly-lym)).sum()/d)*10)-1)*100)}
    return bins, {"fixed_effect_slope_won_per_m2_per_extra_m2":slope,"fixed_effect_log_slope":log_slope,"pct_unit_change_for_10m2":float((math.exp(log_slope*10)-1)*100),"by_region":by_region}


def split(df):
    h=pd.util.hash_pandas_object(df[["group","area","price"]],index=True).astype("uint64")
    return df[(h%5)!=0].copy(), df[(h%5)==0].copy()


def evaluate(actual, pred, threshold):
    a=np.asarray(actual,dtype=float); p=np.asarray(pred,dtype=float)
    ok=np.isfinite(a)&np.isfinite(p)&(a>0)
    a=a[ok]; p=p[ok]
    apos=a>=threshold; ppos=p>=threshold
    fn=(apos&~ppos); fp=(~apos&ppos)
    return {"n":int(len(a)),"mape_pct":float(np.mean(np.abs(p-a)/a)*100),"misclassification_pct":float(np.mean(fn|fp)*100),"false_negative_total_pct":float(np.mean(fn)*100),"false_positive_total_pct":float(np.mean(fp)*100),"false_negative_conditional_pct":float(fn.sum()/max(1,apos.sum())*100),"false_positive_conditional_pct":float(fp.sum()/max(1,(~apos).sum())*100)}


def q3_q4(df):
    train,test=split(df)
    dong_med=train.groupby("group")["unit_price"].median()
    bin_med=train.groupby(["group","area_bin"],observed=True)["unit_price"].median()
    q=train.groupby("group")["price"].quantile([.25,.5,.75]).unstack()
    qbin=train.groupby(["group","area_bin"],observed=True)["price"].quantile([.25,.5,.75]).unstack()
    test["pred_dong_unit"]=test["group"].map(dong_med)*test.area
    idx=pd.MultiIndex.from_arrays([test.group,test.area_bin])
    v=bin_med.reindex(idx).to_numpy(); fallback=test.pred_dong_unit.to_numpy(); test["pred_dong_area_unit"]=np.where(np.isfinite(v),v*test.area,fallback)
    test["pred_dong_p50"]=test.group.map(q.get(.5))
    test["pred_dong_area_p50"]=qbin.get(.5).reindex(idx).to_numpy(); test["pred_dong_area_p50"]=test["pred_dong_area_p50"].fillna(test.pred_dong_p50)
    models={"동 단일 ㎡당 중앙단가":"pred_dong_unit","동×면적구간 ㎡당 중앙단가":"pred_dong_area_unit","동 공시가 P50":"pred_dong_p50","동×면적구간 공시가 P50":"pred_dong_area_p50"}
    result={}
    for label,col in models.items():
        result[label]={}
        for t in THRESHOLDS:
            result[label][str(t)]=evaluate(test.price,test[col],t)
        result[label]["by_region_159m"]={r:evaluate(s.price,s[col],159_000_000) for r,s in test.groupby("region")}
    # Interval decision models: pass if P25>=T, fail if P75<T, otherwise uncertain.
    intervals={}
    for label, lo, hi in [("동 P25~P75",test.group.map(q.get(.25)),test.group.map(q.get(.75))), ("동×면적구간 P25~P75",qbin.get(.25).reindex(idx).to_numpy(),qbin.get(.75).reindex(idx).to_numpy())]:
        lo=pd.Series(lo,index=test.index,dtype=float).fillna(test.group.map(q.get(.25))); hi=pd.Series(hi,index=test.index,dtype=float).fillna(test.group.map(q.get(.75)))
        t=159_000_000; decision=np.where(lo>=t,1,np.where(hi<t,0,np.nan)); mask=np.isfinite(decision); actual=(test.price>=t).astype(int)
        intervals[label]={"coverage_pct":float(mask.mean()*100),"misclassification_among_decided_pct":float((decision[mask]!=actual[mask]).mean()*100),"overall_wrong_pct":float(((decision[mask]!=actual[mask]).sum()/len(test))*100),"uncertain_pct":float((~mask).mean()*100)}
    # Histogram: exact pass-share except threshold bin; 10m bins, approximate at bin midpoint.
    hist_store=[]; errors=[]
    for grp,s in test.groupby("group"):
        tr=train[train.group==grp]
        if tr.empty: continue
        bins=np.floor(tr.price/10_000_000).astype(int); counts=bins.value_counts(); hist_store.append(len(counts))
        approx=float(counts[bins.index*10_000_000+5_000_000>=159_000_000].sum()/counts.sum())
        actual=float((s.price>=159_000_000).mean()); errors.append(abs(approx-actual))
    histogram={"numbers_per_dong_mean_nonempty_bins":float(np.mean(hist_store)*2 if hist_store else 0),"pass_share_mae_percentage_points":float(np.mean(errors)*100 if errors else np.nan),"individual_misclassification":"N/A: 면적·호 식별정보 없이 동 히스토그램만으로 개별 세대를 분류할 수 없음"}
    storage={"동 단일 ㎡당 단가":2,"동×5면적구간 단가":10,"동 공시가 P25/P50/P75":4,"동×5면적구간 P25/P50/P75":20,"동 1천만원 히스토그램":"비어 있지 않은 구간당 경계+빈도 2개; 실측 평균은 histogram 참조"}
    return result, intervals, histogram, storage, len(train), len(test)


def fmt_money(x):
    return f"{x:,.0f}"


def main():
    download(); df,meta=load_filtered(); q1table,q1metrics=q1(df); q2bins,q2reg=q2(df); models,intervals,hist,storage,ntrain,ntest=q3_q4(df)
    primary={k:v[str(159_000_000)] for k,v in models.items()}
    summary={"source":{"url":DATA_URL,"year":2025},"cleaning":meta,"q1":q1metrics,"q2":q2reg,"q3_q4":{"primary_threshold":159_000_000,"models":models,"intervals":intervals,"histogram":hist,"storage_numbers_per_dong":storage,"train_rows":ntrain,"test_rows":ntest}}
    (OUT/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    q2bins.to_csv(OUT/"area_bins.csv",index=False,encoding="utf-8-sig")
    # Compact percentile distribution of dong-level Q1 metrics.
    q1desc=q1table[["n","cv","iqr_ratio","p10_p90_ratio_width","p90_p10_multiple"]].describe(percentiles=[.1,.25,.5,.75,.9]).T
    q1desc.to_csv(OUT/"q1_metric_distribution.csv",encoding="utf-8-sig")
    lines=[]
    lines += ["# 연립·다세대 공동주택 공시가격 단가 근사 검증", "", "## 데이터와 전처리", f"- 원자료: 공공데이터포털 2025년 공동주택 공시가격 전국 파일", f"- 원자료 행: {meta['raw_rows']:,}; 연립·다세대 추출 전처리 전: {meta['filtered_rows_before_clean']:,}", f"- 최종 분석: {meta['clean_rows']:,}호, 법정동 {meta['clean_dongs']:,}개", f"- 결측 제거 {meta['bad_missing']:,}행, 0 이하 제거 {meta['bad_nonpositive']:,}행, 물리적으로 비현실적인 값 제거 {meta['bad_implausible']:,}행", f"- 5호 미만 법정동 제외: {meta['excluded_lt5_dongs']:,}개 동, {meta['excluded_lt5_rows']:,}호", "- 평가는 해시 기반 80% 학습·20% 검증으로 분리하여 같은 세대로 단가를 만들고 평가하는 누수를 막음.", "", "## Q1. 법정동 안 ㎡당 단가 분산"]
    for r,m in q1metrics.items():
        lines.append(f"- **{r}**: 동별 CV 중앙값 {m['median_cv']:.3f}, CV<0.2 동 {m['pct_cv_lt_0_2']*100:.1f}%, CV≥0.4 동 {m['pct_cv_ge_0_4']*100:.1f}%, IQR/중앙값 중앙값 {m['median_iqr_ratio']:.3f}, P10~P90 폭/중앙값 {m['median_p10_p90_ratio_width']:.3f}, P90/P10 {m['median_p90_p10_multiple']:.2f}배")
    lines += ["", "판단 기준: CV<0.20은 단일 단가가 대략 ±20% 범위의 변동을 전제로 쓸 수 있는 수준, 0.20~0.40은 경계, CV≥0.40은 임계값 판정용 단일 단가로 부적합으로 분류했다. 이는 법정 기준이 아니라 서비스 오분류 위험을 해석하기 위한 사전 규칙이다.", "", "## Q2. 면적 효과", f"- 법정동 고정효과 회귀에서 면적 1㎡ 증가 시 ㎡당 공시가격 변화: {q2reg['fixed_effect_slope_won_per_m2_per_extra_m2']:,.0f}원/㎡", f"- 면적 10㎡ 증가 시 ㎡당 공시가격 변화율: {q2reg['pct_unit_change_for_10m2']:.2f}%"]
    for r,m in q2reg["by_region"].items(): lines.append(f"  - {r}: 10㎡ 증가 시 {m['pct_unit_change_for_10m2']:.2f}%")
    lines += ["", "## Q3. 동 단가 근사의 실제 오차 — 필요 공시가 1.59억원"]
    for name,m in primary.items():
        lines.append(f"- **{name}**: MAPE {m['mape_pct']:.2f}%, 전체 오분류 {m['misclassification_pct']:.2f}%, 실제 충족 중 미달 오판 {m['false_negative_conditional_pct']:.2f}%, 실제 미달 중 충족 오판 {m['false_positive_conditional_pct']:.2f}%")
    lines += ["", "## Q4. 개선안 비교", "", "| 방식 | 동당 저장 숫자 | MAPE | 1.59억 오분류 |", "|---|---:|---:|---:|"]
    labelmap={"동 단일 ㎡당 중앙단가":"2 (단가+n)","동×면적구간 ㎡당 중앙단가":"10 (5단가+5n)","동 공시가 P50":"4 (P25/P50/P75+n)","동×면적구간 공시가 P50":"20 (5×P25/P50/P75+n)"}
    for name,m in primary.items(): lines.append(f"| {name} | {labelmap[name]} | {m['mape_pct']:.2f}% | {m['misclassification_pct']:.2f}% |")
    lines += ["", f"- 동 P25~P75 보수 판정: 커버리지 {intervals['동 P25~P75']['coverage_pct']:.1f}%, 판정한 건 중 오분류 {intervals['동 P25~P75']['misclassification_among_decided_pct']:.2f}%", f"- 동×면적구간 P25~P75 보수 판정: 커버리지 {intervals['동×면적구간 P25~P75']['coverage_pct']:.1f}%, 판정한 건 중 오분류 {intervals['동×면적구간 P25~P75']['misclassification_among_decided_pct']:.2f}%", f"- 1천만원 히스토그램: 동당 평균 저장 숫자 {hist['numbers_per_dong_mean_nonempty_bins']:.1f}개, 동별 충족비율 MAE {hist['pass_share_mae_percentage_points']:.2f}%p. 단, 개별호 오분류율은 계산 불가.", "", "## 최종 권고", "- 최종 권고문은 수치 비교를 바탕으로 자동 작성하지 않고, 보고서 검토 시 단일 단가의 오분류율과 면적구간 개선폭을 기준으로 선택한다.", "", "## 권장 저장 포맷 후보", "```json", '{"법정동코드":{"n":123,"bins":{"0_30":{"n":12,"unit_p50":1234567,"price_p25":90000000,"price_p50":110000000,"price_p75":130000000},"30_45":{},"45_60":{},"60_85":{},"85_inf":{}}}}', "```", "", "면적 구간은 [0,30), [30,45), [45,60), [60,85), [85,∞)㎡이다."]
    (OUT/"report.md").write_text("\n".join(lines),encoding="utf-8")
    print(json.dumps({"done":True,"rows":len(df),"dongs":df.group.nunique(),"primary":primary},ensure_ascii=False,indent=2))

if __name__ == "__main__":
    main()
