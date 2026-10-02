"""主入口：拉数据 → 基线回测 → 对比基准"""

import pandas as pd

import config
from data_layer import load_prices
from engine import Strategy, run_backtest
from metrics import annual_returns, compare_table, perf_stats, stress_report


def main():
    print("加载数据 ...")
    prices = load_prices(config.ALL_TICKERS)
    print(prices.apply(lambda s: s.first_valid_index().date()).to_string())

    start, end = "2017-01-01", None
    strat = Strategy(universe=config.UNIVERSES["V1_全家桶"], freq="M", top_n=3,
                     signal="comp3612", cash_rule=True)
    res = run_backtest(prices, strat, start=start, end=end)

    bench = {t: prices[t].dropna() for t in ["QQQ", "SPY"]}
    eq_w = prices[config.UNIVERSES["V1_全家桶"]].loc[start:].pct_change().mean(axis=1)
    eq_w_nav = (1 + eq_w.fillna(0)).cumprod()

    navs = {"因子轮动V1": res["nav"], "QQQ": bench["QQQ"] / bench["QQQ"].iloc[0],
            "SPY": bench["SPY"] / bench["SPY"].iloc[0], "池等权": eq_w_nav}
    tbl = compare_table({k: v.loc["2017-01-01":] for k, v in navs.items()})
    print("\n=== 基线对比（2017 至今） ===")
    print(tbl.to_string())
    print(f"\n年换手率: {res['annual_turnover']:.1f} 倍 | 调仓次数: {res['n_rebal']}")

    print("\n=== 压力场景 ===")
    for name, r in stress_report(res["nav"]).items():
        qqq_r = stress_report(bench["QQQ"]).get(name)
        print(f"{name}: 策略 {r:+.1%} | QQQ {qqq_r:+.1%}")

    print("\n=== 年度收益 ===")
    ann = pd.DataFrame({k: annual_returns(v.loc["2017-01-01":]) for k, v in navs.items()})
    print((ann * 100).round(1).to_string())

    print("\n=== 最近 8 次调仓 ===")
    print(res["trades"].tail(8).to_string(index=False))

    res["nav"].to_csv("results/baseline_nav.csv")
    print("\n基线 nav 已存 results/baseline_nav.csv")


if __name__ == "__main__":
    main()
