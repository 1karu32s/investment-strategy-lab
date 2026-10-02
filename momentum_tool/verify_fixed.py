"""修复后的终验：V7 全段（首日建仓）+ 新口径年度收益 + 跨年连续 walk-forward"""

from data_layer import load_prices
from engine import Strategy, run_backtest
from metrics import annual_returns, perf_stats
import config

prices = load_prices(config.ALL_TICKERS)

print("=" * 70)
print("A) V7 修复后终验（首月建仓 + 年度收益新口径）")
s = Strategy(**config.RECOMMENDED)
r = run_backtest(prices, s, start="2017-01-01")
q = prices["QQQ"].loc["2017-01-01":]
qn = q / q.iloc[0]
st, qst = perf_stats(r["nav"]), perf_stats(qn)
print(f"V7 : CAGR {st['CAGR']:.2%} | MaxDD {st['MaxDD']:.2%} | Calmar {st['Calmar']:.2f} | "
      f"年换手 {r['annual_turnover']:.1f}")
print(f"QQQ: CAGR {qst['CAGR']:.2%} | MaxDD {qst['MaxDD']:.2%} | Calmar {qst['Calmar']:.2f}")
v7_ann = annual_returns(r["nav"])
q_ann = annual_returns(qn)
print("V7 年度(新口径): ", " ".join(f"{v:+.1%}" for v in v7_ann))
print("QQQ 年度(新口径):", " ".join(f"{v:+.1%}" for v in q_ann))
print("首次建仓日:", r["trades"].iloc[0]["date"] if len(r["trades"]) else "N/A")

print("=" * 70)
print("B) walk-forward 修正版（首日建仓 + 每年重选参 + 持仓跨年连续）")
V5 = config.UNIVERSES["V5_含QQQ"]
V6 = config.UNIVERSES["V6_QQQ加SMH"]

import itertools
import pandas as pd


def make_strats(universe):
    out = []
    for sig, top, buf, wt, tr, an in itertools.product(
            config.SIGNALS, [2, 3], [0, 2], ["eq", "mom"], [False, True], [None, "QQQ"]):
        out.append(Strategy(universe=universe, freq="M", top_n=top, signal=sig,
                            cash_rule=False, buffer=buf, weighting=wt,
                            trend_filter=tr, anchor=an))
    return out


strats = make_strats(V5) + make_strats(V6)
state, navs, chosen = None, [], []
for y in range(2019, 2027):
    rows = []
    for sm in strats:
        rr = run_backtest(prices, sm, start="2017-01-01", end=f"{y - 1}-12-31")
        rows.append((sm, perf_stats(rr["nav"])["CAGR"]))
    sm_best = max(rows, key=lambda x: x[1])[0]
    ry = run_backtest(prices, sm_best, start=f"{y}-01-01", end=f"{y}-12-31",
                      initial_state=state)
    state = ry["final_state"]
    navs.append(ry["nav"])
    chosen.append({"year": y, "strat": sm_best.label(), "ret": ry["nav"].iloc[-1] - 1})
    print(f"{y}: {sm_best.label()} → {ry['nav'].iloc[-1] - 1:+.1%}")

wf = navs[0]
for n in navs[1:]:
    wf = pd.concat([wf, n * wf.iloc[-1]])
q_wf = prices["QQQ"].loc["2019-01-01":]
q_wf = q_wf / q_wf.iloc[0]
wfs, qws = perf_stats(wf), perf_stats(q_wf)
print(f"\nwalk-forward(修正版): CAGR {wfs['CAGR']:.2%} | MaxDD {wfs['MaxDD']:.2%}")
print(f"QQQ 同期          : CAGR {qws['CAGR']:.2%} | MaxDD {qws['MaxDD']:.2%}")
