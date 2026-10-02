"""换手效率与信号变体探索：目标=扩大回放优势至 +2pp 以上且降换手"""

import pandas as pd

import config
from data_layer import load_prices
from engine import Strategy, run_backtest
from metrics import annual_returns, perf_stats

prices = load_prices(config.ALL_TICKERS)


def run(name, **kw):
    base = dict(universe=config.RECOMMENDED["universe"], freq="M", top_n=2,
                signal="short136", cash_rule=True, anchor="QQQ", anchor_w=0.8,
                weighting="mom", buffer=0, abs_filter=True, vol_guard=0.30)
    base.update(kw)
    s = Strategy(**base)
    r = run_backtest(prices, s, start="2017-01-01")
    st = perf_stats(r["nav"])
    ann = annual_returns(r["nav"])
    tr = perf_stats(run_backtest(prices, s, start="2018-01-01", end=config.TRAIN_END)["nav"])
    va = perf_stats(run_backtest(prices, s, start=config.VALID_START)["nav"])
    y22 = ann.get(pd.Timestamp("2022-12-31"), float("nan"))
    y23 = ann.get(pd.Timestamp("2023-12-31"), float("nan"))
    print(f"{name:26s} 全段 {st['CAGR']:+.2%}/{st['MaxDD']:.1%}/C{st['Calmar']:.2f} | "
          f"训练 {tr['CAGR']:+.1%} | 23+ {va['CAGR']:+.1%} | "
          f"2022 {y22:+.1%} | 2023 {y23:+.1%} | 换手 {r['annual_turnover']:.1f}")
    return st["CAGR"], r["annual_turnover"]


q = prices["QQQ"].loc["2017-01-01":]
qn = q / q.iloc[0]
print(f"{'QQQ':26s} 全段 {perf_stats(qn)['CAGR']:+.2%}/-35.6%/C0.58 | 训练 +10.9% | "
      f"23+ +31.7% | 2022 -33.1% | 2023 +53.8% | 换手 0.0")
print("=" * 116)

print("--- A) trade_through × buffer（signal 固定 short136, aw0.8） ---")
run("V8 对照")
run("V8+tt", trade_through=True)
run("V8+tt+buf1", trade_through=True, buffer=1)
run("V8+tt+buf2", trade_through=True, buffer=2)
run("V8+buf2(无tt)", buffer=2)

print("--- B) 信号变体（基于 A 最优开关） ---")
run("V8+tt w136", trade_through=True, signal="w136")
run("V8+tt c1236", trade_through=True, signal="c1236")
run("V8+tt+buf1 w136", trade_through=True, buffer=1, signal="w136")
run("V8+tt+buf1 c1236", trade_through=True, buffer=1, signal="c1236")

print("--- C) aw 微调（基于 B 最优信号） ---")
