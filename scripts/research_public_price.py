from __future__ import annotations
import csv,json,math,os,shutil,zipfile
from pathlib import Path
import duckdb

ROOT=Path(__file__).resolve().parents[1]
ZIP=Path(os.getenv('PUBLIC_PRICE_ZIP',ROOT/'tmp/public_price_2025.zip'))
WORK=ROOT/'tmp/public_price_work'; OUT=ROOT/'research_output/public_price_2025'
T=[100_000_000,round(200_000_000/1.26),200_000_000,300_000_000]

def qi(s): return '"'+s.replace('"','""')+'"'
def nm(s): return ''.join(c for c in s.lower().strip().replace('\ufeff','') if c not in ' _-()[]/\\')
def pick(cols,exact,contains,req=True):
 d={nm(c):c for c in cols}
 for x in exact:
  if nm(x) in d:return d[nm(x)]
 for x in contains:
  for c in cols:
   if nm(x) in nm(c):return c
 if req: raise KeyError((exact,contains,cols))
 return None
def txt(c): return "''" if not c else f"trim(coalesce(cast({qi(c)} as varchar),''))"
def number(c): return f"try_cast(replace(replace(trim(cast({qi(c)} as varchar)),',',''),' ','') as double)"
def recs(con,q):
 cur=con.execute(q); n=[d[0] for d in cur.description]
 return [dict(zip(n,r)) for r in cur.fetchall()]
def scalar(con,q): return con.execute(q).fetchone()[0]
def cleanfloat(x):
 if isinstance(x,float) and (math.isnan(x) or math.isinf(x)):return None
 return round(x,6) if isinstance(x,float) else x
def normalize(rows): return [{k:cleanfloat(v) for k,v in r.items()} for r in rows]
def copycsv(con,q,p): con.execute(f"copy ({q}) to '{str(p).replace("'","''")}' (header,delimiter ',')")

def main():
 OUT.mkdir(parents=True,exist_ok=True); shutil.rmtree(WORK,ignore_errors=True); WORK.mkdir(parents=True)
 with zipfile.ZipFile(ZIP) as z:
  files=sorted([i for i in z.infolist() if i.filename.lower().endswith('.csv')],key=lambda i:i.file_size,reverse=True)
  if not files:raise RuntimeError('no csv')
  info=files[0]; csvp=WORK/Path(info.filename).name
  with z.open(info) as a,csvp.open('wb') as b: shutil.copyfileobj(a,b,8*1024*1024)
 for enc in ('utf-8-sig','utf-8','cp949'):
  try:
   with csvp.open(encoding=enc,newline='') as f: cols=next(csv.reader(f));break
  except UnicodeDecodeError:pass
 area=pick(cols,['전용면적','전유면적','prvuseAr'],['전용면적','전유면적','prvusear'])
 price=pick(cols,['공시가격','공동주택가격','pblntfPc'],['공시가격','공동주택가격','pblntfpc'])
 tname=pick(cols,['공동주택구분명','주택유형명','aphusSeCodeNm'],['공동주택구분명','주택유형명','구분명'],False)
 tcode=pick(cols,['공동주택구분','공동주택구분코드','aphusSeCode'],['공동주택구분코드','aphussecode','공동주택구분'],False)
 sido=pick(cols,['시도','시도명'],['시도']); sig=pick(cols,['시군구','시군구명'],['시군구'])
 eup=pick(cols,['읍면','읍면명'],['읍면'],False); dong=pick(cols,['동리','법정동','법정동명'],['동리','법정동'],False)
 code=pick(cols,['법정동코드','법정동코드10자리'],['법정동코드'],False)
 mapping={'area':area,'price':price,'type_name':tname,'type_code':tcode,'sido':sido,'sigungu':sig,'eupmyeon':eup,'dongri':dong,'legal_code':code}
 A=number(area); P=number(price); TN=txt(tname); TC=txt(tcode); S=txt(sido); G=txt(sig); E=txt(eup); D=txt(dong); C=txt(code)
 typ=f"(({TN} like '%연립%' or {TN} like '%다세대%') or regexp_replace({TC},'[^0-9]','','g') in ('3','5'))"
 htype=f"case when {TN} like '%연립%' or regexp_replace({TC},'[^0-9]','','g')='3' then '연립' else '다세대' end"
 key=f"case when {C}<>'' then {C} else concat_ws('|',{S},{G},nullif({E},''),nullif({D},'')) end"
 name=f"concat_ws(' ',{S},{G},nullif({E},''),nullif({D},''))"
 rg=f"case when {S} like '서울%' then '서울' when {S} like '경기%' or {S} like '인천%' then '수도권(경기·인천)' else '지방' end"
 con=duckdb.connect(str(WORK/'a.duckdb')); con.execute("pragma threads=4");con.execute("pragma memory_limit='5GB'")
 path=str(csvp).replace("'","''")
 con.execute(f"""create table clean as select {key} legal_key,{name} legal_name,{rg} region_group,{htype} housing_type,
 {A} area,cast(round({P}) as bigint) price from read_csv_auto('{path}',header=true,all_varchar=true,sample_size=-1,ignore_errors=true)
 where {typ} and {A}>0 and {P}>0 and {key}<>''""")
 raw=scalar(con,'select count(*) from clean')
 con.execute("""create table gc as select legal_key,any_value(legal_name) legal_name,any_value(region_group) region_group,count(*) n from clean group by legal_key""")
 small_groups=scalar(con,'select count(*) from gc where n<5');small_rows=scalar(con,'select coalesce(sum(n),0) from gc where n<5')
 con.execute("""create table e as select c.*,price/area unit_price,case when area<=30 then '01_~30' when area<=45 then '02_30~45' when area<=60 then '03_45~60' when area<=85 then '04_60~85' else '05_85~' end area_bin from clean c join gc g using(legal_key) where g.n>=5""")
 n=scalar(con,'select count(*) from e');groups=scalar(con,'select count(*) from gc where n>=5')
 csvp.unlink(missing_ok=True);ZIP.unlink(missing_ok=True)
 con.execute("""create table gs as select legal_key,any_value(legal_name) legal_name,any_value(region_group) region_group,count(*) n,
 avg(unit_price) mean_up,median(unit_price) median_up,stddev_pop(unit_price)/avg(unit_price) cv,
 quantile_cont(unit_price,.1) p10,quantile_cont(unit_price,.25) p25,quantile_cont(unit_price,.75) p75,quantile_cont(unit_price,.9) p90,
 quantile_cont(unit_price,.75)-quantile_cont(unit_price,.25) iqr,
 quantile_cont(unit_price,.9)-quantile_cont(unit_price,.1) p10_p90_width,
 quantile_cont(unit_price,.9)/quantile_cont(unit_price,.1) p90_p10_ratio from e group by legal_key""")
 q1=normalize(recs(con,"""select coalesce(region_group,'전국') region_group,count(*) groups,sum(n) households,median(cv) median_cv,
 quantile_cont(cv,.25) p25_cv,quantile_cont(cv,.75) p75_cv,avg((cv<.2)::int) share_cv_lt_02,avg((cv>=.4)::int) share_cv_ge_04,
 median(iqr/median_up) median_iqr_to_median,median(p10_p90_width/median_up) median_p10p90_to_median,
 median(p90_p10_ratio) median_p90_p10_ratio,sum(cv*n)/sum(n) household_weighted_mean_cv
 from gs group by grouping sets((region_group),()) order by region_group"""))
 bins=normalize(recs(con,"""select coalesce(region_group,'전국') region_group,area_bin,count(*) n,avg(unit_price) mean_up,median(unit_price) median_up,avg(area) mean_area
 from e group by grouping sets((region_group,area_bin),(area_bin)) order by region_group,area_bin"""))
 reg=normalize(recs(con,"""with s as(select region_group,legal_key,avg(area) ma,avg(unit_price) mu from e group by region_group,legal_key),
 d as(select e.region_group,e.area,e.unit_price,e.area-s.ma da,e.unit_price-s.mu du from e join s using(region_group,legal_key))
 select coalesce(region_group,'전국') region_group,count(*) n,covar_pop(area,unit_price)/var_pop(area) pooled_slope,corr(area,unit_price) pooled_corr,
 sum(da*du)/sum(da*da) legal_dong_fe_slope,corr(da,du) legal_dong_fe_corr from d group by grouping sets((region_group),()) order by region_group"""))
 con.execute("""create table gm as select legal_key,median(unit_price) med,avg(unit_price) mean,quantile_cont(price,.25) p25,median(price) p50,quantile_cont(price,.75) p75 from e group by legal_key""")
 con.execute("""create table gb as select legal_key,area_bin,count(*) bn,median(unit_price) bmed from e group by legal_key,area_bin""")
 con.execute("""create table gt as select legal_key,housing_type,count(*) tn,median(unit_price) tmed from e group by legal_key,housing_type""")
 con.execute("""create table pred as select e.*,gm.p25,gm.p50,gm.p75,gm.med*area p_med,gm.mean*area p_mean,
 (case when gb.bn>=5 then gb.bmed else gm.med end)*area p_bin,(case when gt.tn>=5 then gt.tmed else gm.med end)*area p_type,gm.p50 p_p50
 from e join gm using(legal_key) left join gb using(legal_key,area_bin) left join gt using(legal_key,housing_type)""")
 models=[('동네_중위단가1개','p_med',1),('동네_평균단가1개','p_mean',1),('동네×면적5구간','p_bin',10),('동네×주택유형','p_type',4),('동네_P50가격','p_p50',4)]
 q3=[]
 for mn,pc,store in models:
  for t in T:q3+=recs(con,f"""select '{mn}' model,coalesce(region_group,'전국') region_group,{t} threshold,count(*) n,
  avg(abs({pc}-price)/price) mape,median(abs({pc}-price)/price) median_ape,quantile_cont(abs({pc}-price)/price,.9) p90_ape,
  avg(((price>={t})<>({pc}>={t}))::int) overall_misclass,
  sum((price>={t} and {pc}<{t})::int)::double/nullif(sum((price>={t})::int),0) false_negative_rate,
  sum((price<{t} and {pc}>={t})::int)::double/nullif(sum((price<{t})::int),0) false_positive_rate,{store} storage_numbers_per_dong
  from pred group by grouping sets((region_group),()) order by region_group""")
 q3=normalize(q3)
 grades=[];hists=[]
 for t in T:
  grades+=recs(con,f"""with g as(select legal_key,any_value(region_group) region_group,avg((price>={t})::int) ts,avg((p_med>={t})::int) bs,avg((p_bin>={t})::int) ars,
  any_value(p25) p25,any_value(p50) p50,any_value(p75) p75 from pred group by legal_key),z as(select *,
  case when ts>=.75 then 'A' when ts>=.5 then 'B' when ts>=.25 then 'C' else 'D' end tg,
  case when bs>=.75 then 'A' when bs>=.5 then 'B' when bs>=.25 then 'C' else 'D' end bg,
  case when ars>=.75 then 'A' when ars>=.5 then 'B' when ars>=.25 then 'C' else 'D' end ag,
  case when {t}<=p25 then 'A' when {t}<=p50 then 'B' when {t}<=p75 then 'C' else 'D' end qg from g)
  select coalesce(region_group,'전국') region_group,{t} threshold,count(*) groups,avg((bg<>tg)::int) base_grade_misclass,avg((ag<>tg)::int) area_grade_misclass,
  avg((qg<>tg)::int) quantile_grade_misclass,avg(abs(bs-ts)) base_share_mae,avg(abs(ars-ts)) area_share_mae
  from z group by grouping sets((region_group),()) order by region_group""")
  hists+=recs(con,f"""with tr as(select legal_key,any_value(region_group) region_group,count(*) n,avg((price>={t})::int) ts from e group by legal_key),
  b as(select legal_key,floor(price/10000000)*10000000 lo,count(*) c from e group by legal_key,lo),x as(select tr.legal_key,tr.region_group,tr.ts,
  sum(case when b.lo>={t} then b.c when b.lo+10000000<={t} then 0 else b.c*((b.lo+10000000-{t})/10000000.0) end)/tr.n hs
  from tr join b using(legal_key) group by tr.legal_key,tr.region_group,tr.ts,tr.n),z as(select *,case when ts>=.75 then 'A' when ts>=.5 then 'B' when ts>=.25 then 'C' else 'D' end tg,
  case when hs>=.75 then 'A' when hs>=.5 then 'B' when hs>=.25 then 'C' else 'D' end hg from x)
  select coalesce(region_group,'전국') region_group,{t} threshold,count(*) groups,avg(abs(hs-ts)) hist_share_mae,
  quantile_cont(abs(hs-ts),.9) hist_share_p90_abs_error,avg((hg<>tg)::int) hist_grade_misclass from z group by grouping sets((region_group),()) order by region_group""")
 grades=normalize(grades);hists=normalize(hists)
 histstore=normalize(recs(con,"""with b as(select legal_key,floor(price/10000000) bin,count(*) n from e group by legal_key,bin),g as(select legal_key,count(*) bins from b group by legal_key)
 select avg(bins) avg_nonempty_bins,median(bins) median_nonempty_bins,quantile_cont(bins,.9) p90_nonempty_bins,max(bins) max_nonempty_bins from g"""))[0]
 sens=normalize(recs(con,"""with c as(select quantile_cont(unit_price,.001) lo,quantile_cont(unit_price,.999) hi from e),x as(select e.* from e,c where unit_price between lo and hi),
 g as(select legal_key,count(*) n,stddev_pop(unit_price)/avg(unit_price) cv from x group by legal_key having count(*)>=5)
 select count(*) groups,median(cv) median_cv,avg((cv<.2)::int) share_cv_lt_02,avg((cv>=.4)::int) share_cv_ge_04 from g"""))[0]
 copycsv(con,'select * from gs order by region_group,legal_name',OUT/'q1_group_stats.csv')
 copycsv(con,"select coalesce(region_group,'전국') region_group,area_bin,count(*) n,avg(unit_price) mean_up,median(unit_price) median_up,avg(area) mean_area from e group by grouping sets((region_group,area_bin),(area_bin)) order by region_group,area_bin",OUT/'q2_area_bins.csv')
 summary={'source':{'dataset':'국토교통부_주택 공시가격 정보_20250626','reference_date':'2025-01-01','official_all_rows':15580435,'official_sha256':'BBADCB0E85787F3DB157B199A6B9DF1601E995228A3976106EC5440C2CD8935C','csv_entry':info.filename,'columns':mapping},
 'cleaning':{'valid_villa_rows':raw,'eligible_rows_n_ge_5':n,'eligible_legal_dongs':groups,'excluded_groups_n_lt_5':small_groups,'excluded_rows_n_lt_5':small_rows,'outliers':'주분석은 상단 절단 없음; 면적<=0·가격<=0 제거. 0.1~99.9% 단가 민감도 별도'},
 'q1':q1,'q1_sensitivity':sens,'q2_area_bins':bins,'q2_regression':reg,'q3_unit_metrics':q3,'q4_grade_metrics':grades,'q4_histogram_metrics':hists,'q4_histogram_storage':histstore,
 'definitions':{'cv_rule':{'<0.2':'실용적','0.2~0.4':'주의','>=0.4':'부적합'},'area_bins':['<=30','30~45','45~60','60~85','>85'],'grade':{'A':'>=75%','B':'50~75%','C':'25~50%','D':'<25%'}}}
 (OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8');con.close()
if __name__=='__main__':main()
