"""Build quarantined diagnostic USD/CNY panels and retain source checks."""
import hashlib
import json
from pathlib import Path
import re
import sys
import os
import pandas as pd

ROOT = Path(__file__).resolve().parent
RAW = Path(sys.argv[1])
OUT = Path(os.environ.get('A7_NORMALIZED_DIR', ROOT/'normalized'))
OUT.mkdir(parents=True,exist_ok=True)
core_path = Path(os.environ['FROZEN_PANEL'])
core = pd.read_csv(core_path,index_col=0,parse_dates=True)[['QQQ','SMH']]
raw = json.loads((RAW/'spmo_nasdaq_prices.json').read_text())['data']['tradesTable']['rows']
px = pd.Series({pd.to_datetime(r['date'],format='%m/%d/%Y'):float(r['close'].replace('$','').replace(',','')) for r in raw}).sort_index()
assert len(px)==len(raw) and px.index.is_unique and (px>0).all()
events = json.loads((RAW/'spmo_invesco_distributions.json').read_text())['distributions']
unknown_events = [e for e in events if e['distributionAmountPerUnit'] is None]
# A null event is not silently treated as zero. Exclude windows spanning it.
if unknown_events:
    last_unknown = max(pd.Timestamp(e['exDate']) for e in unknown_events)
    px = px.loc[px.index > last_unknown]
events_known = [e for e in events if e['distributionAmountPerUnit'] is not None]
div = pd.Series(0.,index=px.index)
for e in events_known:
    day = pd.Timestamp(e['exDate'])
    if px.index[0]<day<=px.index[-1]:
        assert day in px.index, f'ex date absent: {day}'
        div.loc[day] += e['distributionAmountPerUnit']
factors = (px+div)/px.shift()
factors.iloc[0]=1.
tr = factors.cumprod()
pd.DataFrame({'close':px,'distribution':div,'total_return_index':tr}).to_csv(OUT/'spmo_market_TR.csv',index_label='date')

# Price comparison is separate from NAV comparison: no inference of identical conventions.
legacy_path=Path(os.environ['SPMO_LEGACY_CSV'])
sh = pd.read_csv(legacy_path,index_col=0,parse_dates=True).iloc[:,0]
check = pd.concat([px.rename('nasdaq_close'),sh.rename('legacy_sina_close')],axis=1).dropna()
check['difference_bps']=(check.nasdaq_close/check.legacy_sina_close-1)*10000
check.to_csv(OUT/'spmo_vs_legacy.csv',index_label='date')
nav_raw=json.loads((RAW/'spmo_invesco_nav.json').read_text())['lineChartData'][0]
nav=pd.Series({pd.to_datetime(r['date'],format='%m/%d/%Y'):r['value'] for r in nav_raw['data']}).sort_index()
nd=pd.Series(0.,index=nav.index)
for e in events_known:
    day=pd.Timestamp(e['exDate'])
    if day in nd.index:nd.loc[day]+=e['distributionAmountPerUnit']
nf=(nav+nd)/nav.shift();nf.iloc[0]=1.;nt=nf.cumprod()
official=json.loads((RAW/'spmo_invesco_performance.json').read_text())
pr={r['label']:r for r in official['cumulativePerformance'] if r['label'] in ['fund','marketPrice']}
end=pd.Timestamp(official['effectiveDate']);controls=[]
for label,months in [('m1',1),('y1',12),('y3',36),('y5',60)]:
    start=end-pd.DateOffset(months=months)
    nr=(nt.loc[end]/nt.loc[:start].iloc[-1]-1)*100
    mr=(tr.loc[end]/tr.loc[:start].iloc[-1]-1)*100
    controls.append({'period':label,'market_calculated_pct':mr,'market_published_pct':pr['marketPrice'][label],
                     'market_difference_bps':(mr-pr['marketPrice'][label])*100,
                     'NAV_calculated_pct':nr,'NAV_published_pct':pr['fund'][label],
                     'NAV_difference_bps':(nr-pr['fund'][label])*100})

html=(RAW/'usd_cny_fed.html').read_text()
pairs=re.findall(r'<th[^>]*>\s*(\d{1,2}-[A-Z]{3}-\d{2})\s*</th>\s*<td[^>]*>\s*([0-9.]+|ND)\s*</td>',html)
assert len(pairs)>6000
fx=pd.Series({pd.to_datetime(d,format='%d-%b-%y'):float(v) if v!='ND' else float('nan') for d,v in pairs}).sort_index()
fx.to_csv(OUT/'fed_USDCNY_raw.csv',index_label='date',header=['CNY_per_USD'])
usd=core.join(tr.rename('SPMO'),how='inner')[['QQQ','SPMO','SMH']]
usd=usd.loc[:min(pd.Timestamp('2026-09-30'),fx.last_valid_index())]
assert usd.notna().all().all()
rates=fx.reindex(fx.index.union(usd.index)).sort_index().ffill().reindex(usd.index)
assert rates.notna().all()
filled=fx.reindex(usd.index).isna()
usd=usd/usd.iloc[0]
cny=usd.mul(rates,axis=0);cny=cny/cny.iloc[0]
usd.to_csv(OUT/'panel_USD_diagnostic.csv',index_label='date')
cny.to_csv(OUT/'panel_CNY_diagnostic.csv',index_label='date')
pd.DataFrame({'CNY_per_USD':rates,'carried_reference':filled}).to_csv(OUT/'fx_alignment.csv',index_label='date')
report={
 'status':'diagnostic_unverified',
 'coverage':{'start':str(cny.index[0].date()),'end':str(cny.index[-1].date()),'rows':len(cny)},
 'SPMO':{'issuer_dividend_records':len(events),'unresolved_null_events':unknown_events,
         'earlier_windows_excluded_reason':'Unknown distribution amount; do not silently set to zero',
         'dividends_in_price_period':int((div>0).sum()),
         'raw_price_rows':len(px),'daily_max_abs_TR':float((factors-1).abs().max()),
         'legacy_overlap':len(check),'legacy_max_abs_difference_bps':float(check.difference_bps.abs().max()),
         'legacy_p99_abs_difference_bps':float(check.difference_bps.abs().quantile(.99)),
         'performance_controls':controls},
 'fx':{'source':'Federal Reserve H.10 historical China page','units':'CNY per USD',
       'last_available':str(fx.last_valid_index().date()),'carried_reference_days':int(filled.sum()),
       'method':'Reference-rate valuation and hypothetical conversion; NOT broker executable FX. Prior value on bank holidays; no extension beyond last source observation.'},
 'limitations':['SPMO price history from Nasdaq; distribution history from Invesco. No Tiingo crosscheck yet; no independent full corporate-action signoff.',
                'Issuer market performance can use bid/ask midpoint; NAV and market controls remain distinct. Residuals recorded, not fitted away.',
                'QQQ/SMH inherit existing diagnostic panel limitations. QQQ is a Nasdaq proxy, not pre-inception QNDX history.',
                'FX series ends before 2026-09 month-end, so September 2026 cannot count as a complete terminal month.',
                'Personal taxes omitted; fund distributions reinvested gross. Historical milestone frequencies are not future probabilities.'],
 'input_hashes':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [core_path,legacy_path,*[RAW/n for n in ['spmo_nasdaq_prices.json','spmo_invesco_distributions.json','spmo_invesco_nav.json','spmo_invesco_performance.json','usd_cny_fed.html']]]},
 'output_hashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.glob('*.csv')},
}
(OUT/'data_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if 'hash' not in k},ensure_ascii=False,indent=2))
