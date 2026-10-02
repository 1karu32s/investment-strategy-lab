"""最后一轮机制测试：vol_guard（波动率状态防御）× abs_filter × 频率，V7 框架"""

import pandas as pd

import config
from data_layer import load_prices
from engine import Strategy, run_backtest
from metrics import annual_returns, perf_stats

prices = load_prices(config.ALL_TICKERS)


def run(name, **kw):
    base = dict(universe=config.RECOMMENDED["universe"], freq="M", top_n=2,
                signal="short136", cash_rule=True, anchor="QQQ", anchor_w=0.65,
                weighting="mom", buffer=0)
    base.update(kw)
    s = Strategy(**base)
    r = run_backtest(prices, s, start="2017-01-01")
    st = perf_stats(r["nav"])
    ann = annual_returns(r["nav"])
    tr = perf_stats(run_backtest(prices, s, start="2018-01-01", end=config.TRAIN_END)["nav"])
    va = perf_stats(run_backtest(prices, s, start=config.VALID_START)["nav"])
    y22 = ann.get(pd.Timestamp("2022-12-31"), float("nan"))
    y23 = ann.get(pd.Timestamp("2023-12-31"), float("nan"))
    print(f"{name:28s} 全段 {st['CAGR']:+.2%}/{st['MaxDD']:.1%}/C{st['Calmar']:.2f} | "
          f"训练 {tr['CAGR']:+.1%} | 23+ {va['CAGR']:+.1%} | "
          f"2022 {y22:+.1%} | 2023 {y23:+.1%} | 换手 {r['annual_turnover']:.1f}")


q = prices["QQQ"].loc["2017-01-01":]
qn = q / q.iloc[0]
print(f"{'QQQ':28s} 全段 {perf_stats(qn)['CAGR']:+.2%}/-35.6%/C0.58 | 训练 +10.9% | "
      f"23+ +31.7% | 2022 -33.1% | 2023 +53.8%")
print("=" * 118)

run("V7 基线(对照)")
run("V7+abs(=回放最优)", abs_filter=True)
print("--- vol_guard 阈值扫描 ---")
for vg in [0.25, 0.30, 0.35]:
    run(f"V7+abs+vg{vg}", abs_filter=True, vol_guard=vg)
for vg in [0.30]:
    run(f"V7+abs+vg{vg} aw0.8", abs_filter=True, vol_guard=vg, anchor_w=0.8)
print("--- 频率补测（V7+abs） ---")
run("V7+abs 2W", abs_filter=True, freq="2W")
run("V7+abs+vg0.30 2W", abs_filter=True, vol_guard=0.30, freq="2W")
