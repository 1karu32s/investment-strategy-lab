"""快速结构测试：参数少、过拟合风险低的三个变体 vs QQQ"""

import pandas as pd

import config
from data_layer import load_prices
from engine import Strategy, run_backtest
from metrics import annual_returns, perf_stats


def show(name, s, prices, full="2017-01-01"):
    r = run_backtest(prices, s, start=full)
    st = perf_stats(r["nav"])
    tr = perf_stats(run_backtest(prices, s, start="2018-01-01", end=config.TRAIN_END)["nav"])
    va = perf_stats(run_backtest(prices, s, start=config.VALID_START)["nav"])
    print(f"{name:38s} 全段 {st['CAGR']:+.1%}/{st['MaxDD']:.0%} | 训练 {tr['CAGR']:+.1%} | "
          f"验证 {va['CAGR']:+.1%}/{va['MaxDD']:.0%} | 换手 {r['annual_turnover']:.1f}")
    return r


def main():
    prices = load_prices(config.ALL_TICKERS)
    V5 = config.UNIVERSES["V5_含QQQ"]
    V6 = config.UNIVERSES["V6_QQQ加SMH"]
    V7 = ["QQQ", "SMH", "SPMO", "XSMO", "MTUM"]      # 纯科技动量池

    q = prices["QQQ"].loc["2017-01-01":]
    print(f"{'QQQ 买入持有':38s} 全段 {perf_stats(q / q.iloc[0])['CAGR']:+.1%}/-36% | "
          f"训练 +10.9% | 验证 +31.7%/-23%")
    print("=" * 100)

    print("--- A) 纯 QQQ 时序动量（单资产+动量退出，参数最少） ---")
    for sig in ["short136", "classic121", "comp3612"]:
        show(f"QQQ-TSM {sig} 现金退出",
             Strategy(universe=["QQQ"], freq="M", top_n=1, signal=sig, cash_rule=True), prices)

    print("\n--- B) 锚定权重扫描（V5 short136 top2 mom, anchor=QQQ） ---")
    for w in [0.5, 0.65, 0.8]:
        show(f"V5 anchor_w={w}",
             Strategy(universe=V5, freq="M", top_n=2, signal="short136", cash_rule=False,
                      weighting="mom", anchor="QQQ", anchor_w=w), prices)
    for w in [0.65, 0.8]:
        show(f"V6 anchor_w={w}",
             Strategy(universe=V6, freq="M", top_n=2, signal="short136", cash_rule=False,
                      weighting="mom", anchor="QQQ", anchor_w=w), prices)

    print("\n--- C) V7 纯科技动量池 ---")
    for cash in [False, True]:
        show(f"V7 top2 short136 cash={cash}",
             Strategy(universe=V7, freq="M", top_n=2, signal="short136", cash_rule=cash,
                      weighting="mom"), prices)
    show("V7+QQQ锚0.65",
         Strategy(universe=V7, freq="M", top_n=2, signal="short136", cash_rule=False,
                  weighting="mom", anchor="QQQ", anchor_w=0.65), prices)

    # 最有希望的候选看年度收益明细
    print("\n--- 候选年度收益对比 ---")
    for name, s in [
        ("QQQ", None),
        ("QQQ-TSM classic121", Strategy(universe=["QQQ"], freq="M", top_n=1,
                                        signal="classic121", cash_rule=True)),
        ("V5 anchor0.65", Strategy(universe=V5, freq="M", top_n=2, signal="short136",
                                   cash_rule=False, weighting="mom", anchor="QQQ",
                                   anchor_w=0.65)),
        ("V7 top2 mom", Strategy(universe=V7, freq="M", top_n=2, signal="short136",
                                 cash_rule=False, weighting="mom")),
    ]:
        if s is None:
            nav = prices["QQQ"].loc["2017-01-01":]
            nav = nav / nav.iloc[0]
        else:
            nav = run_backtest(prices, s, start="2017-01-01")["nav"]
        print(f"{name:22s}", " ".join(f"{v:+.0%}" for v in annual_returns(nav)))


if __name__ == "__main__":
    main()
