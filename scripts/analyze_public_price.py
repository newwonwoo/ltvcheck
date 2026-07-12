from __future__ import annotations
import csv,json,math,re,urllib.request,zipfile
from pathlib import Path
import numpy as np
import pandas as pd
URL='https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId=FILE_000000003525375&fileDetailSn=1&insertDataPrcus=N'
Z=Path('/tmp/p.zip'); O=Path('research_output'); O.mkdir(exist_ok=True)
BINS=[0,30,45,60,85,np.inf]; LABELS=['~30','30~45','45~60','60~85','85~']; TS=[100_000_000,159_000_000,200_000_000,300_000_000]
def norm(x): return re.sub(r'[^0-9a-zA-Z가-힣]','',str(x)).lower()
def choose(cols,cands,contains=()):
 m={norm(c):c for c in cols}
 for x in cands:
  if norm(x) in m:return m[norm(x)]
 for c in cols:
  if all(norm(x) in norm(c) for x in contains):return c
 return None
def enc(raw):
 for e in ('utf-8-sig','cp949','euc-kr','utf-8'):
  try:raw.decode(e);return e
  except:pass
 return 'utf-8'
def download():
 req=urllib.request.Request(URL,headers={'User-Agent':'Mozilla/5.0'})
 with urllib.request.urlopen(req,timeout=180) as r,Z.open('wb') as f:
  while b:=r.read(1024*1024):f.write(b)
 print('zip',Z.stat().st_size)
def load():
 z=zipfile.ZipFile(Z); names=[n for n in z.namelist() if n.lower().endswith(('.csv','.txt'))]; frames=[]; meta={'zip_bytes':Z.stat().st_size,'members':names,'raw_rows':0,'filtered_rows_before_clean':0}
 for name in names:
  with z.open(name) as f: sample=f.read(65536)
  e=enc(sample); first=sample.decode(e,'replace').splitlines()[0]; sep='\t' if first.count('\t')>first.count(',') else ','; cols=next(csv.reader([first],delimiter=sep))
  tc=choose(cols,['공동주택구분명','주택유형','공동주택구분','건물종류'],('구분','명')); ac=choose(cols,['전용면적','전용면적(㎡)','전용면적(m2)'],('전용','면적')); pc=choose(cols,['공동주택가격','공시가격','공동주택가격(원)'],('주택','가격')); sc=choose(cols,['시도','시도명'],('시도',)); gc=choose(cols,['시군구','시군구명'],('시군구',)); dc=choose(cols,['법정동','법정동명'],('법정동',)); cc=choose(cols,['법정동코드'],('법정동','코드'))
  if not all([tc,ac,pc,dc]): raise RuntimeError(str(cols))
  use=[x for x in [tc,ac,pc,sc,gc,dc,cc] if x]; print(name,e,sep,tc,ac,pc,sc,gc,dc,cc)
  for ch in pd.read_csv(z.open(name),encoding=e,sep=sep,usecols=use,chunksize=350000,low_memory=False):
   meta['raw_rows']+=len(ch); mask=ch[tc].astype(str).str.contains('연립|다세대',regex=True,na=False); s=ch.loc[mask].copy(); meta['filtered_rows_before_clean']+=len(s)
   if s.empty:continue
   ren={tc:'housing_type',ac:'area',pc:'price',dc:'dong'}
   if sc:ren[sc]='sido'
   if gc:ren[gc]='sigungu'
   if cc:ren[cc]='dong_code'
   s.rename(columns=ren,inplace=True)
   for k in ['sido','sigungu','dong_code']:
    if k not in s:s[k]=''
   frames.append(s[['housing_type','area','price','sido','sigungu','dong','dong_code']])
 d=pd.concat(frames,ignore_index=True); d['area']=pd.to_numeric(d.area.astype(str).str.replace(',','',regex=False),errors='coerce'); d['price']=pd.to_numeric(d.price.astype(str).str.replace(',','',regex=False),errors='coerce'); meta['bad_missing']=int(d[['area','price']].isna().any(axis=1).sum()); meta['bad_nonpositive']=int(((d.area<=0)|(d.price<=0)).fillna(True).sum()); d=d[d.area.notna()&d.price.notna()&(d.area>0)&(d.price>0)].copy(); d['unit_price']=d.price/d.area; meta['bad_implausible']=int(((d.area>500)|(d.unit_price<10000)|(d.unit_price>100000000)).sum()); d=d[(d.area<=500)&(d.unit_price>=10000)&(d.unit_price<=100000000)].copy(); d['dong_code']=d.dong_code.astype(str).str.replace(r'\.0$','',regex=True).str.strip(); d['group']=np.where(d.dong_code.str.len()>=8,d.dong_code,d.sido.astype(str)+'|'+d.sigungu.astype(str)+'|'+d.dong.astype(str)); s=d.sido.astype(str); d['region']=np.select([s.str.contains('서울'),s.str.contains('경기|인천',regex=True)],['서울','수도권기타'],default='지방'); d['area_bin']=pd.cut(d.area,BINS,labels=LABELS,right=False); c=d.groupby('group').size(); ok=c[c>=5].index; meta['excluded_lt5_rows']=int((~d.group.isin(ok)).sum()); meta['excluded_lt5_dongs']=int((c<5).sum()); d=d[d.group.isin(ok)].copy(); meta.update(clean_rows=len(d),clean_dongs=d.group.nunique()); return d,meta
def q1(d):
 g=d.groupby('group').unit_price; x=g.agg(n='size',mean='mean',sd='std',p10=lambda s:s.quantile(.1),p25=lambda s:s.quantile(.25),p50='median',p75=lambda s:s.quantile(.75),p90=lambda s:s.quantile(.9)).reset_index(); x['cv']=x.sd/x['mean']; x['iqr_ratio']=(x.p75-x.p25)/x.p50; x['p10_p90_width']=(x.p90-x.p10)/x.p50; x['multiple']=x.p90/x.p10; x=x.merge(d[['group','region']].drop_duplicates('group'),on='group'); out={}
 for n,s in [('전체',x),*[(r,x[x.region==r]) for r in ['서울','수도권기타','지방']]]: out[n]={'dongs':len(s),'rows':int(s.n.sum()),'median_cv':float(s.cv.median()),'mean_cv':float(s.cv.mean()),'pct_cv_lt_0_2':float((s.cv<.2).mean()),'pct_cv_ge_0_4':float((s.cv>=.4).mean()),'median_iqr_ratio':float(s.iqr_ratio.median()),'median_p10_p90_width':float(s.p10_p90_width.median()),'median_p90_p10_multiple':float(s.multiple.median())}
 return x,out
def q2(d):
 allb=d.groupby('area_bin',observed=False).agg(n=('price','size'),mean_unit=('unit_price','mean'),median_unit=('unit_price','median'),mean_price=('price','mean')).reset_index(); allb['region']='전체'; rb=d.groupby(['region','area_bin'],observed=False).agg(n=('price','size'),mean_unit=('unit_price','mean'),median_unit=('unit_price','median'),mean_price=('price','mean')).reset_index(); bins=pd.concat([allb,rb]); gx=d.groupby('group').area.transform('mean'); gy=d.groupby('group').unit_price.transform('mean'); den=((d.area-gx)**2).sum(); slope=float(((d.area-gx)*(d.unit_price-gy)).sum()/den); ly=np.log(d.unit_price); lm=ly.groupby(d.group).transform('mean'); ls=float(((d.area-gx)*(ly-lm)).sum()/den); br={}
 for r,s in d.groupby('region'):
  ax=s.groupby('group').area.transform('mean'); uy=s.groupby('group').unit_price.transform('mean'); l=np.log(s.unit_price); lm=l.groupby(s.group).transform('mean'); de=((s.area-ax)**2).sum(); br[r]={'won_slope':float(((s.area-ax)*(s.unit_price-uy)).sum()/de),'pct_for_10m2':float((math.exp(float(((s.area-ax)*(l-lm)).sum()/de)*10)-1)*100)}
 return bins,{'won_slope':slope,'log_slope':ls,'pct_for_10m2':float((math.exp(ls*10)-1)*100),'by_region':br}
def ev(a,p,t):
 a=np.asarray(a,float);p=np.asarray(p,float);m=np.isfinite(a)&np.isfinite(p)&(a>0);a=a[m];p=p[m];ap=a>=t;pp=p>=t;fn=ap&~pp;fp=~ap&pp;return {'n':len(a),'mape_pct':float(np.mean(np.abs(p-a)/a)*100),'misclassification_pct':float(np.mean(fn|fp)*100),'fn_total_pct':float(np.mean(fn)*100),'fp_total_pct':float(np.mean(fp)*100),'fn_cond_pct':float(fn.sum()/max(1,ap.sum())*100),'fp_cond_pct':float(fp.sum()/max(1,(~ap).sum())*100)}
def q34(d):
 h=pd.util.hash_pandas_object(d[['group','area','price']],index=True).astype('uint64'); tr=d[(h%5)!=0].copy();te=d[(h%5)==0].copy();dm=tr.groupby('group').unit_price.median();bm=tr.groupby(['group','area_bin'],observed=True).unit_price.median();q=tr.groupby('group').price.quantile([.25,.5,.75]).unstack();qb=tr.groupby(['group','area_bin'],observed=True).price.quantile([.25,.5,.75]).unstack();te['du']=te.group.map(dm)*te.area;idx=pd.MultiIndex.from_arrays([te.group,te.area_bin]);v=bm.reindex(idx).to_numpy();te['dbu']=np.where(np.isfinite(v),v*te.area,te.du);te['p50']=te.group.map(q.get(.5));te['bp50']=pd.Series(qb.get(.5).reindex(idx).to_numpy(),index=te.index).fillna(te.p50);mods={'동 단일 ㎡당 중앙단가':'du','동×면적구간 ㎡당 중앙단가':'dbu','동 공시가 P50':'p50','동×면적구간 공시가 P50':'bp50'};res={}
 for n,c in mods.items():res[n]={**{str(t):ev(te.price,te[c],t) for t in TS},'by_region_159m':{r:ev(s.price,s[c],159000000) for r,s in te.groupby('region')}}
 ints={}
 for n,lo,hi in [('동 P25~P75',te.group.map(q.get(.25)),te.group.map(q.get(.75))),('동×면적구간 P25~P75',qb.get(.25).reindex(idx).to_numpy(),qb.get(.75).reindex(idx).to_numpy())]:
  lo=pd.Series(lo,index=te.index,dtype=float).fillna(te.group.map(q.get(.25)));hi=pd.Series(hi,index=te.index,dtype=float).fillna(te.group.map(q.get(.75)));dec=np.where(lo>=159000000,1,np.where(hi<159000000,0,np.nan));m=np.isfinite(dec);a=(te.price>=159000000).astype(int);ints[n]={'coverage_pct':float(m.mean()*100),'misclassification_among_decided_pct':float((dec[m]!=a[m]).mean()*100),'overall_wrong_pct':float((dec[m]!=a[m]).sum()/len(te)*100),'uncertain_pct':float((~m).mean()*100)}
 stores=[];errs=[]
 for g,s in te.groupby('group'):
  x=tr[tr.group==g]
  if x.empty:continue
  b=np.floor(x.price/10000000).astype(int);c=b.value_counts();stores.append(len(c));approx=float(c[c.index*10000000+5000000>=159000000].sum()/c.sum());errs.append(abs(approx-(s.price>=159000000).mean()))
 hist={'numbers_per_dong_mean_nonempty_bins':float(np.mean(stores)*2),'pass_share_mae_pp':float(np.mean(errs)*100),'individual_misclassification':'N/A'};return res,ints,hist,len(tr),len(te)
def main():
 download();d,m=load();x,q1m=q1(d);bins,q2m=q2(d);mods,ints,hist,ntr,nte=q34(d);summary={'source':{'url':URL,'year':2025},'cleaning':m,'q1':q1m,'q2':q2m,'q3_q4':{'primary_threshold':159000000,'models':mods,'intervals':ints,'histogram':hist,'train_rows':ntr,'test_rows':nte}};(O/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8');bins.to_csv(O/'area_bins.csv',index=False,encoding='utf-8-sig');x[['n','cv','iqr_ratio','p10_p90_width','multiple']].describe(percentiles=[.1,.25,.5,.75,.9]).T.to_csv(O/'q1_metric_distribution.csv',encoding='utf-8-sig');p={k:v['159000000'] for k,v in mods.items()};L=['# 연립·다세대 공동주택 공시가격 단가 근사 검증','','## 데이터와 전처리',f"- 원자료 행 {m['raw_rows']:,}; 연립·다세대 추출 {m['filtered_rows_before_clean']:,}; 최종 {m['clean_rows']:,}호·{m['clean_dongs']:,}개 법정동",f"- 결측 {m['bad_missing']:,}, 0 이하 {m['bad_nonpositive']:,}, 비현실값 {m['bad_implausible']:,}, 5호 미만 제외 {m['excluded_lt5_dongs']:,}개 동·{m['excluded_lt5_rows']:,}호",'- 해시 기반 80% 학습·20% 검증.','','## Q1']
 for r,a in q1m.items():L.append(f"- {r}: CV 중앙값 {a['median_cv']:.3f}, CV<0.2 {a['pct_cv_lt_0_2']*100:.1f}%, CV≥0.4 {a['pct_cv_ge_0_4']*100:.1f}%, IQR/중앙값 {a['median_iqr_ratio']:.3f}, P10~P90폭/중앙값 {a['median_p10_p90_width']:.3f}, P90/P10 {a['median_p90_p10_multiple']:.2f}배")
 L+=['','## Q2',f"- 동 고정효과: 면적 1㎡ 증가 시 ㎡당 가격 {q2m['won_slope']:,.0f}원 변화, 10㎡ 증가 시 {q2m['pct_for_10m2']:.2f}% 변화"]
 for r,a in q2m['by_region'].items():L.append(f"- {r}: 10㎡ 증가 시 {a['pct_for_10m2']:.2f}%")
 L+=['','## Q3·Q4 — 1.59억원','|방식|MAPE|오분류|실제 충족 중 미달 오판|실제 미달 중 충족 오판|','|---|---:|---:|---:|---:|']
 for n,a in p.items():L.append(f"|{n}|{a['mape_pct']:.2f}%|{a['misclassification_pct']:.2f}%|{a['fn_cond_pct']:.2f}%|{a['fp_cond_pct']:.2f}%|")
 L += ['',f"- 동 P25~P75: 커버리지 {ints['동 P25~P75']['coverage_pct']:.1f}%, 판정분 오분류 {ints['동 P25~P75']['misclassification_among_decided_pct']:.2f}%",f"- 동×면적 P25~P75: 커버리지 {ints['동×면적구간 P25~P75']['coverage_pct']:.1f}%, 판정분 오분류 {ints['동×면적구간 P25~P75']['misclassification_among_decided_pct']:.2f}%",f"- 1천만원 히스토그램: 동당 평균 숫자 {hist['numbers_per_dong_mean_nonempty_bins']:.1f}개, 동별 충족비율 MAE {hist['pass_share_mae_pp']:.2f}%p. 개별호 오분류는 식별 불가."]
 (O/'report.md').write_text('\n'.join(L),encoding='utf-8');print(json.dumps({'rows':len(d),'dongs':d.group.nunique(),'primary':p},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
