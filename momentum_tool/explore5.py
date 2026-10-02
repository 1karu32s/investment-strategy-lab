"""杠杆路线：3x ETF + 波动率守卫（守卫看 QQQ 1x 波动，危机时拉 3x 出场）
注意：3x 与 1x 不同池排名（波动率调整信号会系统性压低 3x 排名）
"""

import pandas as pd

import config
from data_layer import load_prices
from engine import Strategy, run_backtest
from metrics import annual_returns, perf_stats

prices = load_prices(config.ALL_TICKERS)


def run(name, universe, start, cash=True, vg=0.30, top=None, sig="short136", **kw):
    base = dict(universe=universe, freq="M", top_n=top or len(universe), signal=sig,
                cash_rule=cash, weighting="eq", buffer=0, vol_guard=vg)
    base.update(kw)
    s = Strategy(**base)
    r = run_backtest(prices, s, start=start)
    st = perf_stats(r["nav"])
    ann = annual_returns(r["nav"])
    q = prices["QQQ"].loc[start:]
    qs = perf_stats(q / q.iloc[0])
    y22 = ann.get(pd.Timestamp("2022-12-31"), float("nan"))
    yrs = " ".join(f"{v:+.0%}" for v in ann)
    print(f"{name:30s} {start[:7]}起 {st['CAGR']:+.1%}/{st['MaxDD']:.0%}/C{st['Calmar']:.2f}"
          f" | QQQ {qs['CAGR']:+.1%}/{qs['MaxDD']:.0%} | 2022 {y22:+.0%} | 换手 {r['annual_turnover']:.1f}")
    print(f"    年度: {yrs}")


print("=== 基准（2012 起 QQQ） ===")
q = prices["QQQ"].loc["2012-01-03":]
print(f"QQQ 2012起 {perf_stats(q/q.iloc[0])['CAGR']:+.1%}/{perf_stats(q/q.iloc[0])['MaxDD']:.0%}")
print()
print("=== A) 3x 单持 + 守卫（2012 起，全压力场景覆盖） ===")
run("TQQQ 纯持有(对照)", ["TQQQ"], "2012-01-03", cash=False, vg=0.0)
run("TQQQ+守卫0.30", ["TQQQ"], "2012-01-03")
run("SOXL 纯持有(对照)", ["SOXL"], "2012-01-03", cash=False, vg=0.0)
run("SOXL+守卫0.30", ["SOXL"], "2012-01-03")
run("UPRO+守卫0.30", ["UPRO"], "2012-01-03")
print()
print("=== B) 3x 池轮动（2012 起） ===")
run("TQQQ/SOXL top1+守卫", ["TQQQ", "SOXL"], "2012-01-03", top=1, weighting="mom")
run("TQQQ/SOXL 各半+守卫", ["TQQQ", "SOXL"], "2012-01-03")
run("TQQQ/SOXL/UPRO top1+守卫", ["TQQQ", "SOXL", "UPRO"], "2012-01-03", top=1, weighting="mom")
print()
print("=== C) 1x+3x 混合（用户 5050 的杠杆增强版） ===")
run("SPMO/TQQQ 各半+守卫", ["SPMO", "TQQQ"], "2015-10-12")
run("SPMO/SOXL 各半+守卫", ["SPMO", "SOXL"], "2015-10-12")
run("QQQ/SOXL 各半+守卫", ["QQQ", "SOXL"], "2012-01-03")
