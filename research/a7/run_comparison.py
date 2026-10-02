"""Personal cash-flow diagnostics; reuse audited accounting via static-weight adapter."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import time
import sys
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parent
OUT=Path(os.environ.get('A7_OUTPUT', ROOT/'results'))
OUT.mkdir(parents=True,exist_ok=True)
NORMALIZED=Path(os.environ.get('A7_NORMALIZED_DIR', ROOT/'normalized'))
PROTOCOL=Path(os.environ.get('A7_PROTOCOL', ROOT/'protocol.example.json'))
protocol=json.loads(PROTOCOL.read_text())
INITIAL=float(protocol['execution']['initial_RMB'])
MONTHLY=float(protocol['execution']['monthly_RMB'])
PRIMARY_GOAL=float(protocol['execution']['primary_goal_RMB'])
SECONDARY_GOAL=float(protocol['execution']['secondary_goal_RMB'])
if INITIAL <= 0 or MONTHLY < 0 or PRIMARY_GOAL <= 0 or SECONDARY_GOAL <= 0:
    raise ValueError('Capital and targets must be positive; contributions nonnegative')
SNAP=ROOT.parents[1]/'momentum_tool/frozen_run.py'
sys.path.insert(0,str(SNAP.parent))
os.environ['FROZEN_SUMMARY_DIR']=str(OUT/'engine_unused_output')
spec=importlib.util.spec_from_file_location('primary_accounting',SNAP)
fr=importlib.util.module_from_spec(spec);spec.loader.exec_module(fr)
weights=protocol['candidates']
original_target=fr.target
fr.target=lambda scheme,sig,month,glide:dict(weights[scheme])
panel=pd.read_csv(NORMALIZED/'panel_CNY_diagnostic.csv',index_col=0,parse_dates=True)
fx=pd.read_csv(NORMALIZED/'fx_alignment.csv',index_col=0,parse_dates=True)
groups=pd.Series(panel.index,index=panel.index).groupby(panel.index.to_period('M'))
month_first=groups.first();month_last=groups.last()
# The source FX release lacks the last September sessions. Exclude that final
# month from complete evaluation horizons and contributions at an invented close.
complete_months=month_last.index[month_last.index<panel.index[-1].to_period('M')]
exec_days=set(month_last.loc[complete_months])
sm={d:{'trend':False,'dd':0.,'picked':[]} for d in exec_days}

def account(prices,scheme,start,end,cost,monthly=MONTHLY,initial=INITIAL):
    initial_sm={start:{'trend':False,'dd':0.,'picked':[]}}
    first,_,state=fr.simulate(prices,[start],initial_sm,scheme,start,start,cost,0.,initial=initial)
    next_day=prices.index[prices.index.get_loc(start)+1]
    rest,metrics,_=fr.simulate(prices,exec_days,sm,scheme,next_day,end,cost,0.,monthly=monthly,initial_state=state)
    df=pd.concat([first,rest])
    return df

# A small relevant adapter check: the new two-phase contribution schedule must
# conserve initial capital plus 60 monthly contributions, and constant FX scaling must not change account values.
test_idx=pd.bdate_range('2018-01-01','2022-12-30')
flat=pd.DataFrame(1.,index=test_idx,columns=panel.columns)
saved_ed,saved_sm=exec_days,sm
test_last=pd.Series(test_idx,index=test_idx).groupby(test_idx.to_period('M')).last()
exec_days=set(test_last);sm={d:{} for d in exec_days}
flat_account=account(flat,'N100',test_idx[0],test_idx[-1],0.)
assert np.isclose(flat_account.value.iloc[-1], INITIAL+60*MONTHLY, rtol=1e-12)
assert np.allclose(flat_account.nav,1.,rtol=0,atol=1e-12)
scaled=account(flat*7.,'N100',test_idx[0],test_idx[-1],0.)
pd.testing.assert_series_equal(flat_account.value,scaled.value,check_exact=False,rtol=1e-12)
exec_days,sm=saved_ed,saved_sm

eligible=[]
for period,start in month_first.items():
    end_period=period+59
    if period==panel.index[0].to_period('M'):
        eligible.append({'start_month':str(period),'eligible':False,'reason':'initial month lacks beginning coverage'})
    elif end_period not in complete_months:
        eligible.append({'start_month':str(period),'eligible':False,'reason':'fewer than 60 complete months'})
    else:
        eligible.append({'start_month':str(period),'eligible':True,'reason':'complete common prices and FX reference'})
pd.DataFrame(eligible).to_csv(OUT/'window_eligibility.csv',index=False)
starts=[pd.Period(r['start_month'],freq='M') for r in eligible if r['eligible']]
rows=[];t0=time.time()
for cost in protocol['execution']['cost_per_dollar_bought_or_sold']:
    for si,period in enumerate(starts):
        start=month_first.loc[period]
        long_period=min(period+83,complete_months[-1])
        end=month_last.loc[long_period]
        for scheme in weights:
            df=account(panel,scheme,start,end,cost)
            # Save full daily account for the earliest start; all windows get
            # reproducible dates and aggregate outcomes in window_results.csv.
            if si==0:df.to_csv(OUT/f'first_start_daily_{scheme}_{round(cost*10000)}bp.csv',index_label='date')
            for horizon in [60,84]:
                final_period=period+horizon-1
                if final_period>long_period:continue
                stop=month_last.loc[final_period];window=df.loc[:stop]
                contributed=INITIAL+MONTHLY*horizon
                months=(stop-start).days/365.25*12
                peak=np.maximum(window.nav.cummax(),1.)
                record={'scheme':scheme,'cost_bps':round(cost*10000),'horizon_months':horizon,
                        'start':str(start.date()),'end':str(stop.date()),'contributed':contributed,
                        'terminal':float(window.value.iloc[-1]),'TWR_MaxDD':float((window.nav/peak-1).min()),
                        'below_contributions':bool(window.value.iloc[-1]<contributed),
                        'fx_carried_execution_days':int(fx.loc[[d for d in exec_days if start<=d<=stop],'carried_reference'].sum())}
                for goal,tag in [(PRIMARY_GOAL,'primary'),(SECONDARY_GOAL,'secondary')]:
                    hits=window.index[window.value>=goal]
                    hit=hits[0] if len(hits) else None
                    record[f'{tag}_hit']=hit is not None
                    record[f'{tag}_hit_date']=str(hit.date()) if hit is not None else None
                    record[f'{tag}_months']=(hit-start).days/365.25*12 if hit is not None else None
                    record[f'{tag}_restricted_months']=record[f'{tag}_months'] if hit is not None else months
                    record[f'{tag}_fell_below_after_hit']=bool((window.loc[hit:,'value']<goal).any()) if hit is not None else None
                    record[f'{tag}_terminal_above']=bool(window.value.iloc[-1]>=goal)
                rows.append(record)
        if si%15==0:print(f'{round(cost*10000)}bp {si+1}/{len(starts)} starts; {time.time()-t0:.1f}s',flush=True)
results=pd.DataFrame(rows)
results.to_csv(OUT/'window_results.csv',index=False)
summaries={};pairs={}
for (cost,horizon,scheme),g in results.groupby(['cost_bps','horizon_months','scheme']):
    summaries[f'{scheme}|{horizon}m|{cost}bp']={
        'n':len(g),'terminal_median':float(g.terminal.median()),'terminal_P10':float(g.terminal.quantile(.1)),
        'terminal_min':float(g.terminal.min()),'primary_hit_windows':int(g.primary_hit.sum()),
        'primary_terminal_above_windows':int(g.primary_terminal_above.sum()),
        'primary_fell_back_windows':int(g.primary_fell_below_after_hit.fillna(False).sum()),
        'secondary_hit_windows':int(g['secondary_hit'].sum()),
        'worst_TWR_MaxDD':float(g.TWR_MaxDD.min()),'below_contributions_windows':int(g.below_contributions.sum())}
for cost in [10,30]:
 for horizon in [60,84]:
  subset=results[(results.cost_bps==cost)&(results.horizon_months==horizon)]
  for treatment,control,label in protocol['mechanism_pairs']:
    a=subset[subset.scheme==treatment].set_index('start');b=subset[subset.scheme==control].set_index('start')
    assert a.index.equals(b.index)
    ratio=a.terminal/b.terminal
    saved=b.primary_restricted_months-a.primary_restricted_months
    both=a.primary_hit&b.primary_hit
    both_saved=b.loc[both,'primary_months']-a.loc[both,'primary_months']
    key=f'{treatment}_vs_{control}|{horizon}m|{cost}bp'
    pairs[key]={'n':len(a),'terminal_ratio_median':float(ratio.median()),'terminal_ratio_P10':float(ratio.quantile(.1)),
                'terminal_win_count':int((ratio>1).sum()),'restricted_primary_months_saved_median':float(saved.median()),
                'both_hit_count':int(both.sum()),'both_hit_months_saved_median':float(both_saved.median()) if len(both_saved) else None,
                'only_treatment_hit':int((a.primary_hit&~b.primary_hit).sum()),'only_control_hit':int((~a.primary_hit&b.primary_hit).sum())}
summary={'status':'diagnostic_unverified','protocol':str(PROTOCOL),
         'currency':'nominal CNY, gross dividend reinvestment, before personal taxes',
         'data_report':str(NORMALIZED/'data_report.json'),
         'proxy':'QQQ represents Nasdaq exposure; not pre-inception QNDX returns',
         'window_counts':results.groupby(['horizon_months','cost_bps','scheme']).size().to_dict().__str__(),
         'schemes':summaries,'pairs':pairs,
         'limitations':['Overlapping historical windows, not independent future probabilities.',
                        'Milestone touching is not wealth preservation; terminal-above and subsequent-fall counts are separate.',
                        'Seven-year comparison uses fewer complete windows than five-year, not a same-cohort probability improvement.',
                        'No leverage, no extra dip money, no parameter optimization in this stage.'],
         'hashes':{'protocol':hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),
                   'engine':hashlib.sha256(SNAP.read_bytes()).hexdigest(),
                   'runner':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                   'panel':hashlib.sha256((NORMALIZED/'panel_CNY_diagnostic.csv').read_bytes()).hexdigest()},
         'adapter_checks':{'flat_60_contributions_conserved':True,'flat_NAV_identity':True,'currency_scale_identity':True}}
(OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'schemes':{k:v for k,v in summaries.items() if '|60m|10bp' in k},
                  'pairs':{k:v for k,v in pairs.items() if '|60m|10bp' in k},'elapsed_seconds':time.time()-t0},ensure_ascii=False,indent=2))
