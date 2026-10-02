"""终极检验：升级版纯化 walk-forward（候选集含 vol_guard/aw/abs），跨年连续
对照：QQQ 22.41%、旧纯化版 18.08%、全候选集版 15.37%（均 2019 起）
"""

import itertools

import pandas as pd

import config
from data_layer import load_prices
from engine import Strategy, run_backtest
from metrics import annual_returns, perf_stats

prices = load_prices(config.ALL_TICKERS)

GRID = list(itertools.product(
    config.SIGNALS, [0.65, 0.8], [2, 3], [False, True], [0.0, 0.30]))


def mk(sig, aw, top, absf, vg):
    return Strategy(universe=config.RECOMMENDED["universe"], freq="M", top_n=top,
                    signal=sig, cash_rule=True, anchor="QQQ", anchor_w=aw,
                    weighting="mom", buffer=0, abs_filter=absf, vol_guard=vg)


# 先看回放最优的完整年度序列
print("=== V7+abs+vg0.30 aw0.8 完整年度（回放口径） ===")
r = run_backtest(prices, mk("short136", 0.8, 2, True, 0.30), start="2017-01-01")
q = prices["QQQ"].loc["2017-01-01":]
qn = q / q.iloc[0]
wa, qa = annual_returns(r["nav"]), annual_returns(qn)
print("策略:", " ".join(f"{v:+.0%}" for v in wa))
print("QQQ :", " ".join(f"{v:+.0%}" for v in qa))

state, navs, chosen = None, [], []
print("\n=== walk-forward（每年扩窗重选，48 组合，跨年连续） ===")
for y in range(2019, 2027):
    rows = []
    for sig, aw, top, absf, vg in GRID:
        rr = run_backtest(prices, mk(sig, aw, top, absf, vg),
                          start="2017-01-01", end=f"{y - 1}-12-31")
        rows.append((perf_stats(rr["nav"])["CAGR"], sig, aw, top, absf, vg))
    cagr, sig, aw, top, absf, vg = max(rows)
    ry = run_backtest(prices, mk(sig, aw, top, absf, vg),
                      start=f"{y}-01-01", end=f"{y}-12-31", initial_state=state)
    state = ry["final_state"]
    navs.append(ry["nav"])
    chosen.append({"year": y, "signal": sig, "aw": aw, "top": top, "abs": absf,
                   "vg": vg, "win": f"{cagr:.1%}", "ret": ry["nav"].iloc[-1] - 1})
    print(f"  {y}: {sig} aw={aw} top{top} abs={absf} vg={vg} (窗 {cagr:.1%})"
          f" → {ry['nav'].iloc[-1] - 1:+.1%}")

wf = navs[0]
for n in navs[1:]:
    wf = pd.concat([wf, n * wf.iloc[-1]])
q9 = prices["QQQ"].loc["2019-01-01":]
qn9 = q9 / q9.iloc[0]
wfs, qws = perf_stats(wf), perf_stats(qn9)
print(f"\n升级版 walk-forward: CAGR {wfs['CAGR']:.2%} | MaxDD {wfs['MaxDD']:.2%} | Calmar {wfs['Calmar']:.2f}")
print(f"QQQ 同期           : CAGR {qws['CAGR']:.2%} | MaxDD {qws['MaxDD']:.2%} | Calmar {qws['Calmar']:.2f}")
