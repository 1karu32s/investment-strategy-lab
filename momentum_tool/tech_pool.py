"""科技池动量轮动（轨道 B）：科技子板块池 + 验证过的稳健参数（克制扫描）
参数来源：月度/short136/cash/vg0.30 均为前几轮多重复核的稳健平原区取值
"""

import pandas as pd

import config
from data_layer import load_prices
from engine import Strategy, run_backtest
from metrics import annual_returns, perf_stats

prices = load_prices(config.ALL_TICKERS)

print("=== 科技池数据覆盖 ===")
for t in config.TECH_POOL:
    s = prices[t].dropna()
    print(f"{t}: {s.index[0].date()} → {s.index[-1].date()} ({len(s)} 条)")
print()
print("=== 近3年子板块相关性 ===")
ret = prices.pct_change().loc["2023-09-29":]
print(ret[config.TECH_POOL].corr().round(2).to_string())
print()

def run(name, start, **kw):
    base = dict(universe=config.TECH_POOL, freq="M", top_n=3, signal="short136",
                cash_rule=True, weighting="mom", buffer=0, vol_guard=0.30,
                trend_ref="QQQ")
    base.update(kw)
    s = Strategy(**base)
    r = run_backtest(prices, s, start=start)
    st = perf_stats(r["nav"])
    ann = annual_returns(r["nav"])
    q = prices["QQQ"].loc[start:]
    qs = perf_stats(q / q.iloc[0])
    y22 = ann.get(pd.Timestamp("2022-12-31"), float("nan"))
    print(f"{name:26s} {start[:7]}起 {st['CAGR']:+.2%}/{st['MaxDD']:.1%}/C{st['Calmar']:.2f}"
          f" | QQQ {qs['CAGR']:+.2%}/{qs['MaxDD']:.0%} | 2022 {y22:+.0%} | 换手 {r['annual_turnover']:.1f}")
    print("    年度:", " ".join(f"{v:+.0%}" for v in ann))
    return r

r = run("科技池 top3+守卫", "2013-01-02")
run("科技池 top2+守卫", "2013-01-02", top_n=2)
run("科技池 top3 无守卫", "2013-01-02", vol_guard=0.0)
run("科技池 top3 守卫0.32", "2013-01-02", vol_guard=0.32)

print("\n最近 6 次调仓（top3+守卫）:")
print(r["trades"].tail(6).to_string(index=False))
