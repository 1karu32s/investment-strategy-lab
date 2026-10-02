"""低/零 QQQ 含量策略探索：以用户 5050(SPMO/QQQ) 为骨架 vs 零QQQ 池
约束：QQQ 含量 ≤50%；验收：跑赢 QQQ 同期
"""

import pandas as pd

import config
from data_layer import load_prices
from engine import Strategy, run_backtest
from metrics import annual_returns, perf_stats

prices = load_prices(config.ALL_TICKERS)


def run(name, universe, start, cash=True, vg=0.30, **kw):
    base = dict(universe=universe, freq="M", top_n=len(universe), signal="short136",
                cash_rule=cash, weighting="eq", buffer=0, vol_guard=vg)
    base.update(kw)
    s = Strategy(**base)
    r = run_backtest(prices, s, start=start)
    st = perf_stats(r["nav"])
    ann = annual_returns(r["nav"])
    q = prices["QQQ"].loc[start:]
    qn = q / q.iloc[0]
    qs = perf_stats(qn)
    y22 = ann.get(pd.Timestamp("2022-12-31"), float("nan"))
    print(f"{name:30s} {start[:7]}起 CAGR {st['CAGR']:+.2%}/{st['MaxDD']:.0%}/C{st['Calmar']:.2f}"
          f" | QQQ同期 {qs['CAGR']:+.2%}/{qs['MaxDD']:.0%} | 2022 {y22:+.1%} | 换手 {r['annual_turnover']:.1f}")


print("=== A 组（2015-10 起，QQQ 同期 CAGR 约 20.0%/-31%） ===")
run("5050 纯(复现对照)", ["SPMO", "QQQ"], "2015-10-12", cash=False, vg=0.0)
run("5050+守卫0.30", ["SPMO", "QQQ"], "2015-10-12")
run("5050+守卫0.30 无现金规则", ["SPMO", "QQQ"], "2015-10-12", cash=False)
run("5050+守卫0.26", ["SPMO", "QQQ"], "2015-10-12", vg=0.26)
print()
print("=== B 组（2020-01 起，SMH 可参战；QQQ 同期 CAGR 见行内） ===")
run("SPMO/QQQ/SMH 三分+守卫", ["SPMO", "QQQ", "SMH"], "2020-01-02")
run("SPMO/SMH 5050+守卫(零QQQ)", ["SPMO", "SMH"], "2020-01-02")
run("SMH锚0.6+XSMO/MTUM(零QQQ)", ["SMH", "XSMO", "MTUM"], "2020-01-02",
    anchor="SMH", anchor_w=0.6, top_n=2, weighting="mom", abs_filter=True)
run("SPMO锚0.6+SMH/XSMO/MTUM(零QQQ)", ["SPMO", "SMH", "XSMO", "MTUM"], "2015-10-12",
    anchor="SPMO", anchor_w=0.6, top_n=2, weighting="mom", abs_filter=True)
