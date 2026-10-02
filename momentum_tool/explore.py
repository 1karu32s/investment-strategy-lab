"""机制分层探索：在 V7 框架上逐个开/关新机制，看边际贡献
机制：abs_filter（资产级绝对动量过滤）、fast_exit（周度退出）、ME（月末调仓）
"""

import pandas as pd

import config
from data_layer import load_prices
from engine import Strategy, run_backtest
from metrics import annual_returns, perf_stats


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
    y22, y23 = ann.get(pd.Timestamp("2022-12-31")), ann.get(pd.Timestamp("2023-12-31"))
    print(f"{name:26s} 全段 {st['CAGR']:+.2%}/{st['MaxDD']:.1%}/C{st['Calmar']:.2f} | "
          f"训练 {tr['CAGR']:+.1%} | 23+ {va['CAGR']:+.1%} | "
          f"2022 {y22:+.1%} | 2023 {y23:+.1%} | 换手 {r['annual_turnover']:.1f}")
    return st["CAGR"]


prices = load_prices(config.ALL_TICKERS)
q = prices["QQQ"].loc["2017-01-01":]
qn = q / q.iloc[0]
qs = perf_stats(qn)
qa = annual_returns(qn)
print(f"{'QQQ':26s} 全段 {qs['CAGR']:+.2%}/{qs['MaxDD']:.1%}/C{qs['Calmar']:.2f} | "
      f"训练 +10.9% | 23+ +31.7% | 2022 {qa[pd.Timestamp('2022-12-31')]:+.1%} | "
      f"2023 {qa[pd.Timestamp('2023-12-31')]:+.1%}")
print("=" * 110)

run("V7 基线(对照)")
run("+abs_filter", abs_filter=True)
run("+fast_exit", fast_exit=True)
run("+abs+fast", abs_filter=True, fast_exit=True)
run("月末调仓 ME", freq="ME")
run("ME+abs", freq="ME", abs_filter=True)
run("ME+abs+fast", freq="ME", abs_filter=True, fast_exit=True)
print("--- anchor_w / top_n 微调（基于上面最优机制） ---")
run("abs+fast aw0.75", abs_filter=True, fast_exit=True, anchor_w=0.75)
run("abs+fast top3", abs_filter=True, fast_exit=True, top_n=3)
run("ME+abs+fast aw0.75", freq="ME", abs_filter=True, fast_exit=True, anchor_w=0.75)
