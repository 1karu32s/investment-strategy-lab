"""策略迭代：修复前视 bug 后的引擎上，扩展网格 → 训练/验证 → walk-forward
迭代维度（月度频率固定，前期证据一致最优）：
  池 V5/V6 × 信号 3 种 × top_n 2/3 × 缓冲带 0/2 × 等权/动量加权 × 趋势过滤 开/关
"""

import itertools

import pandas as pd

import config
from data_layer import load_prices
from engine import Strategy, run_backtest
from metrics import annual_returns, perf_stats

V5 = config.UNIVERSES["V5_含QQQ"]
V6 = config.UNIVERSES["V6_QQQ加SMH"]


def make_strats(universe):
    out = []
    for sig, top, buf, wt, tr, an in itertools.product(
            config.SIGNALS, [2, 3], [0, 2], ["eq", "mom"], [False, True],
            [None, "QQQ"]):
        out.append(Strategy(universe=universe, freq="M", top_n=top, signal=sig,
                            cash_rule=False, buffer=buf, weighting=wt,
                            trend_filter=tr, anchor=an))
    return out


def eval_grid(prices, strats, start, end):
    rows = []
    for s in strats:
        r = run_backtest(prices, s, start=start, end=end)
        st = perf_stats(r["nav"])
        rows.append({"pool": "V5" if s.universe == V5 else "V6",
                     "signal": s.signal, "top": s.top_n, "buf": s.buffer,
                     "wt": s.weighting, "trend": s.trend_filter,
                     "anchor": s.anchor or "-", **st,
                     "turn": r["annual_turnover"]})
    return pd.DataFrame(rows)


def best_strat(row):
    return Strategy(universe=V5 if row["pool"] == "V5" else V6, freq="M",
                    top_n=int(row["top"]), signal=row["signal"], cash_rule=False,
                    buffer=int(row["buf"]), weighting=row["wt"],
                    trend_filter=bool(row["trend"]),
                    anchor=None if row["anchor"] == "-" else row["anchor"])


def main():
    prices = load_prices(config.ALL_TICKERS)
    qqq = prices["QQQ"]

    # 0) 修复后基线复跑（原 V5 最优配置）
    s0 = Strategy(universe=V5, freq="M", top_n=2, signal="short136", cash_rule=False)
    r0 = run_backtest(prices, s0, start="2017-01-01")
    q17 = qqq.loc["2017-01-01":]
    print("=== 修复前视 bug 后：V5 旧最优(M top2 short136) 2017 至今 ===")
    print(f"策略: {perf_stats(r0['nav'])}  年换手 {r0['annual_turnover']:.1f}")
    print(f"QQQ : {perf_stats(q17 / q17.iloc[0])}")

    strats = make_strats(V5) + make_strats(V6)

    # 1) 训练段网格
    print("\n=== 训练段 2018-2022 网格（192 组合） ===")
    tr = eval_grid(prices, strats, "2018-01-01", config.TRAIN_END)
    q_tr = perf_stats(qqq.loc["2018-01-01":config.TRAIN_END] /
                      qqq.loc["2018-01-01":].iloc[0])
    print(f"QQQ 训练段: CAGR {q_tr['CAGR']:.1%} MaxDD {q_tr['MaxDD']:.1%} Calmar {q_tr['Calmar']:.2f}")
    print("\n训练段 Top10（按 CAGR）:")
    print(tr.sort_values("CAGR", ascending=False).head(10)
          .round(3).to_string(index=False))
    print("\n训练段 Top10（按 Calmar）:")
    print(tr.sort_values("Calmar", ascending=False).head(10)
          .round(3).to_string(index=False))

    # 2) 验证段：训练段按 CAGR 前 5（MaxDD 不差于 QQQ 的 -36%）
    cand = tr[tr["MaxDD"] > -0.36].sort_values("CAGR", ascending=False).head(5)
    print("\n=== 验证段 2023 至今（候选=训练段 CAGR 前 5） ===")
    q_va = perf_stats(qqq.loc[config.VALID_START:] / qqq.loc[config.VALID_START:].iloc[0])
    print(f"QQQ 验证段: CAGR {q_va['CAGR']:.1%} MaxDD {q_va['MaxDD']:.1%}")
    for _, row in cand.iterrows():
        s = best_strat(row)
        rv = run_backtest(prices, s, start=config.VALID_START)
        ra = run_backtest(prices, s, start="2017-01-01")
        print(f"{row['pool']} {row['signal']} top{int(row['top'])} buf{int(row['buf'])} "
              f"{row['wt']} trend={row['trend']}: 验证 CAGR {perf_stats(rv['nav'])['CAGR']:+.1%} "
              f"MaxDD {perf_stats(rv['nav'])['MaxDD']:.1%} | 全段 CAGR "
              f"{perf_stats(ra['nav'])['CAGR']:.1%} MaxDD {perf_stats(ra['nav'])['MaxDD']:.1%}")

    # 3) Walk-forward：每年扩窗重选（按训练 CAGR），当年执行
    print("\n=== Walk-forward（每年重选） ===")
    wf_navs, chosen = [], []
    for y in range(2019, 2027):
        tr_y = eval_grid(prices, strats, "2017-01-01", f"{y - 1}-12-31")
        b = tr_y.sort_values("CAGR", ascending=False).iloc[0]
        s = best_strat(b)
        ry = run_backtest(prices, s, start=f"{y}-01-01", end=f"{y}-12-31")
        wf_navs.append(ry["nav"])
        chosen.append({"year": y, **{k: b[k] for k in
                                     ["pool", "signal", "top", "buf", "wt", "trend", "anchor"]},
                       "year_ret": ry["nav"].iloc[-1] - 1})
        print(f"{y}: {b['pool']} {b['signal']} top{int(b['top'])} buf{int(b['buf'])} "
              f"{b['wt']} trend={b['trend']} anchor={b['anchor']} → {ry['nav'].iloc[-1] - 1:+.1%}")
    # 逐年 nav 复利串联（每年 nav 从 1 起，乘以上一年末累计值）
    wf = wf_navs[0]
    for n in wf_navs[1:]:
        wf = pd.concat([wf, n * wf.iloc[-1]])
    q_wf = qqq.loc["2019-01-01":]
    print(f"\nWalk-forward 全期: CAGR {perf_stats(wf)['CAGR']:.1%} MaxDD {perf_stats(wf)['MaxDD']:.1%}"
          f" | QQQ: CAGR {perf_stats(q_wf / q_wf.iloc[0])['CAGR']:.1%}"
          f" MaxDD {perf_stats(q_wf / q_wf.iloc[0])['MaxDD']:.1%}")
    print("\n各年参数选择:")
    print(pd.DataFrame(chosen).to_string(index=False))

    tr.to_csv("results/iter_grid_train.csv", index=False)


if __name__ == "__main__":
    main()
