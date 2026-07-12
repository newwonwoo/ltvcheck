from __future__ import annotations

import csv
import json
import os
import shutil
import zipfile
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
ZIP_PATH = Path(os.getenv("PUBLIC_PRICE_ZIP", ROOT / "tmp/public_price_2025.zip"))
WORK = ROOT / "tmp/public_price_index"
OUT = ROOT / "research_output/public_price_2025"


def q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def norm(name: str) -> str:
    return "".join(ch for ch in name.lower().strip().replace("\ufeff", "") if ch not in " _-()[]/\\")


def pick(columns: list[str], exact: list[str], contains: list[str], required: bool = True):
    by_norm = {norm(c): c for c in columns}
    for candidate in exact:
        if norm(candidate) in by_norm:
            return by_norm[norm(candidate)]
    for candidate in contains:
        needle = norm(candidate)
        for column in columns:
            if needle in norm(column):
                return column
    if required:
        raise KeyError({"exact": exact, "contains": contains, "columns": columns})
    return None


def text_expr(column: str | None) -> str:
    if not column:
        return "''"
    return f"trim(coalesce(cast({q(column)} as varchar),''))"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(ZIP_PATH) as archive:
        csv_entries = sorted(
            [item for item in archive.infolist() if item.filename.lower().endswith(".csv")],
            key=lambda item: item.file_size,
            reverse=True,
        )
        if not csv_entries:
            raise RuntimeError("CSV entry not found")
        entry = csv_entries[0]
        csv_path = WORK / Path(entry.filename).name
        with archive.open(entry) as source, csv_path.open("wb") as target:
            shutil.copyfileobj(source, target, 8 * 1024 * 1024)

    columns = None
    encoding_used = None
    sample_rows: list[dict] = []
    for encoding in ("utf-8-sig", "utf-8", "cp949"):
        try:
            with csv_path.open("r", encoding=encoding, newline="") as handle:
                reader = csv.DictReader(handle)
                columns = reader.fieldnames or []
                for _, row in zip(range(5), reader):
                    sample_rows.append(row)
            encoding_used = encoding
            break
        except UnicodeDecodeError:
            sample_rows = []
    if not columns:
        raise RuntimeError("CSV header could not be read")

    legal_code = pick(columns, ["법정동코드", "법정동코드10자리"], ["법정동코드"])
    sido = pick(columns, ["시도", "시도명"], ["시도"])
    sigungu = pick(columns, ["시군구", "시군구명"], ["시군구"])
    eupmyeon = pick(columns, ["읍면", "읍면명"], ["읍면"], False)
    dongri = pick(columns, ["동리", "법정동", "법정동명"], ["동리", "법정동"], False)
    area = pick(columns, ["전용면적", "전유면적"], ["전용면적", "전유면적"])
    price = pick(columns, ["공시가격", "공동주택가격"], ["공시가격", "공동주택가격"])
    main_no = pick(columns, ["본번", "본번지"], ["본번"], False)
    sub_no = pick(columns, ["부번", "부번지"], ["부번"], False)
    special = pick(columns, ["특수지명"], ["특수지명"], False)
    complex_name = pick(columns, ["단지명", "공동주택명"], ["단지명", "공동주택명"], False)
    ledger_pk = pick(columns, ["관리건축물대장PK", "건축물대장PK"], ["건축물대장pk", "관리건축물대장pk"], False)

    C = text_expr(legal_code)
    S = text_expr(sido)
    G = text_expr(sigungu)
    E = text_expr(eupmyeon)
    D = text_expr(dongri)
    region = (
        f"case when {S} like '서울%' then '서울' "
        f"when {S} like '경기%' or {S} like '인천%' then '수도권(경기·인천)' else '지방' end"
    )
    legal_name = f"concat_ws(' ',{S},{G},nullif({E},''),nullif({D},''))"
    area_num = f"try_cast(replace(trim(cast({q(area)} as varchar)),',','') as double)"
    price_num = f"try_cast(replace(trim(cast({q(price)} as varchar)),',','') as double)"

    con = duckdb.connect(str(WORK / "index.duckdb"))
    con.execute("pragma threads=4")
    con.execute("pragma memory_limit='5GB'")
    path = str(csv_path).replace("'", "''")
    con.execute(
        f"""
        create table legal_dong_counts as
        select
          {C} as legal_code,
          any_value({legal_name}) as legal_name,
          any_value({region}) as region_group,
          count(*) as total_units,
          count(distinct concat_ws('|',{text_expr(main_no)},{text_expr(sub_no)},{text_expr(special)})) as parcel_keys,
          count(distinct {text_expr(ledger_pk)}) filter (where {text_expr(ledger_pk)} <> '') as ledger_pk_count,
          avg({area_num}) filter (where {area_num} > 0) as mean_area,
          median({area_num}) filter (where {area_num} > 0) as median_area,
          min({price_num}) filter (where {price_num} > 0) as min_price,
          max({price_num}) filter (where {price_num} > 0) as max_price
        from read_csv_auto('{path}', header=true, all_varchar=true, sample_size=-1, ignore_errors=true)
        where {C} <> ''
        group by {C}
        """
    )

    out_csv = str(OUT / "legal_dong_counts.csv").replace("'", "''")
    con.execute(
        f"copy (select * from legal_dong_counts order by region_group,total_units,legal_code) "
        f"to '{out_csv}' (header, delimiter ',')"
    )

    overview_cursor = con.execute(
        """
        select coalesce(region_group,'전국') region_group,
               count(*) legal_dongs,
               sum(total_units) total_units,
               median(total_units) median_units,
               quantile_cont(total_units,.25) p25_units,
               quantile_cont(total_units,.75) p75_units,
               quantile_cont(total_units,.9) p90_units,
               max(total_units) max_units
        from legal_dong_counts
        group by grouping sets ((region_group),())
        order by region_group
        """
    )
    names = [item[0] for item in overview_cursor.description]
    overview = [dict(zip(names, row)) for row in overview_cursor.fetchall()]

    metadata = {
        "csv_entry": entry.filename,
        "csv_uncompressed_bytes": entry.file_size,
        "encoding": encoding_used,
        "headers": columns,
        "mapped_columns": {
            "legal_code": legal_code,
            "sido": sido,
            "sigungu": sigungu,
            "eupmyeon": eupmyeon,
            "dongri": dongri,
            "area": area,
            "price": price,
            "main_no": main_no,
            "sub_no": sub_no,
            "special": special,
            "complex_name": complex_name,
            "ledger_pk": ledger_pk,
        },
        "sample_rows": sample_rows,
        "overview": overview,
    }
    (OUT / "legal_dong_index_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    con.close()


if __name__ == "__main__":
    main()
