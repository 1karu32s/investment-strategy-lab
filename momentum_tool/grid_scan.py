"""参数网格扫描 + 训练/验证切分 + walk-forward 验证

流程：
1. 网格扫描在训练段（2018-01 ~ 2022-12）上跑全部参数组合
2. 输出训练段 top10 与敏感性分析（按维度聚合）
3. 用训练段最优参数在验证段（2023 至今）一次性验证
4. walk-forward：每年用"该年之前全部数据"重选参数，当年执行，全期串联
"""

import itertools

import numpy as np
import pandas as pd

import config
from data_layer import load_prices
from engine import Strategy, run_backtest
from metrics import perf_stats


def scan(prices, universe, start, end):
    rows = []
    combos = list(itertools.product(config.FREQS, config.TOP_NS, config.SIGNALS, [True, False]))
    print(f"共 {len(combos)} 个组合，训练段 {start} ~ {end}")
    for freq, top_n, sig, cash in combos:
        s = Strategy(universe=universe, freq=freq, top_n=top_n, signal=sig, cash_rule=cash)
        try:
            r = run_backtest(prices, s, start=start, end=end)
            st = perf_stats(r["nav"])
            rows.append({"freq": freq, "top_n": top_n, "signal": sig, "cash_rule": cash,
                         **st, "turnover": r["annual_turnover"]})
        except Exception as e:
            rows.append({"freq": freq, "top_n": top_n, "signal": sig, "cash_rule": cash,
                         "error": str(e)})
        print(".", end="", flush=True)
    print()
    return pd.DataFrame(rows)


def sensitivity(df: pd.DataFrame, dim: str) -> pd.DataFrame:
    return df.groupby(dim)[["CAGR", "MaxDD", "Sharpe", "Calmar"]].mean().round(3)


def main():
    prices = load_prices(config.ALL_TICKERS)
    universe = config.UNIVERSES["V1_全家桶"]

    train_s, train_e = "2018-01-01", config.TRAIN_END
    valid_s, valid_e = config.VALID_START, None

    print("\n===== 1) 训练段网格扫描 =====")
    tr = scan(prices, universe, train_s, train_e)
    tr = tr.dropna(subset=["CAGR"])
    print("\n训练段 Top10（按 Calmar）:")
    print(tr.sort_values("Calmar", ascending=False).head(10).to_string(index=False))

    for dim in ["freq", "top_n", "signal", "cash_rule"]:
        print(f"\n--- 敏感性: {dim} ---")
        print(sensitivity(tr, dim).to_string())

    best = tr.sort_values("Calmar", ascending=False).iloc[0]
    print(f"\n训练段最优: freq={best.freq} top{int(best.top_n)} {best.signal} "
          f"cash={best.cash_rule} | 训练段 CAGR {best.CAGR:.1%} MaxDD {best.MaxDD:.1%}")

    print("\n===== 2) 验证段一次性检验（最优参数） =====")
    s = Strategy(universe=universe, freq=best.freq, top_n=int(best.top_n),
                 signal=best.signal, cash_rule=bool(best.cash_rule))
    va = run_backtest(prices, s, start=valid_s, end=valid_e)
    qqq = prices["QQQ"].loc[valid_s:valid_e]
    print(f"验证段(2023 至今): CAGR {perf_stats(va['nav'])['CAGR']:.1%} | "
          f"MaxDD {perf_stats(va['nav'])['MaxDD']:.1%} | "
          f"QQQ 同期 {qqq.iloc[-1] / qqq.iloc[0] - 1:.1%}(累计)")

    print("\n===== 3) Walk-forward（年度滚动，每年重选参数） =====")
    years = range(2019, 2027)
    wf_navs = []
    chosen = []
    for y in years:
        tr_end = f"{y - 1}-12-31"
        tr_y = scan(prices, universe, "2017-01-01", tr_end)   # 扩窗：每年用此前全部数据重选参数
        b = tr_y.dropna(subset=["CAGR"]).sort_values("Calmar", ascending=False).iloc[0]
        sy = Strategy(universe=universe, freq=b.freq, top_n=int(b.top_n),
                      signal=b.signal, cash_rule=bool(b.cash_rule))
        ry = run_backtest(prices, sy, start=f"{y}-01-01", end=f"{y}-12-31")
        wf_navs.append(ry["nav"])
        chosen.append({"year": y, "freq": b.freq, "top_n": int(b.top_n),
                       "signal": b.signal, "cash": b.cash_rule,
                       "year_ret": ry["nav"].iloc[-1] - 1})
        print(f"{y}: {b.freq} top{int(b.top_n)} {b.signal} cash={b.cash_rule} "
              f"→ 当年 {ry['nav'].iloc[-1] - 1:+.1%}")

    # 逐年 nav 复利串联（每年 nav 从 1 起，乘以上一年末累计值）
    wf = wf_navs[0]
    for n in wf_navs[1:]:
        wf = pd.concat([wf, n * wf.iloc[-1]])
    print(f"\nWalk-forward 全期（2019 至今）: CAGR {perf_stats(wf)['CAGR']:.1%} | "
          f"MaxDD {perf_stats(wf)['MaxDD']:.1%}")
    qqq_full = prices["QQQ"].loc["2019-01-01":]
    qqq_nav = qqq_full / qqq_full.iloc[0]
    print(f"QQQ 同期: CAGR {perf_stats(qqq_nav)['CAGR']:.1%} | MaxDD {perf_stats(qqq_nav)['MaxDD']:.1%}")
    print("\n各年选择的参数:")
    print(pd.DataFrame(chosen).to_string(index=False))

    wf.to_csv("results/walkforward_nav.csv")
    tr.to_csv("results/grid_train.csv", index=False)


if __name__ == "__main__":
    main()
