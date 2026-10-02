"""候选集纯化的 walk-forward：科技池+锚+现金退出结构固定（先验），
每年仅在小参数网格（signal × anchor_w × top_n × abs_filter）内扩窗重选，跨年持仓连续。
对照：全候选集自适应 walk-forward = 15.37%，QQQ = 22.41%（2019 起）
"""

import itertools

import pandas as pd

import config
from data_layer import load_prices
from engine import Strategy, run_backtest
from metrics import annual_returns, perf_stats

prices = load_prices(config.ALL_TICKERS)

GRID = list(itertools.product(
    config.SIGNALS, [0.5, 0.65, 0.8], [2, 3], [False, True]))


def mk(sig, aw, top, absf):
    return Strategy(universe=config.RECOMMENDED["universe"], freq="M", top_n=top,
                    signal=sig, cash_rule=True, anchor="QQQ", anchor_w=aw,
                    weighting="mom", buffer=0, abs_filter=absf)


state, navs, chosen = None, [], []
print("每年选择（扩窗 CAGR 最优）：")
for y in range(2019, 2027):
    rows = []
    for sig, aw, top, absf in GRID:
        rr = run_backtest(prices, mk(sig, aw, top, absf),
                          start="2017-01-01", end=f"{y - 1}-12-31")
        rows.append((perf_stats(rr["nav"])["CAGR"], sig, aw, top, absf))
    cagr, sig, aw, top, absf = max(rows)
    ry = run_backtest(prices, mk(sig, aw, top, absf),
                      start=f"{y}-01-01", end=f"{y}-12-31", initial_state=state)
    state = ry["final_state"]
    navs.append(ry["nav"])
    chosen.append({"year": y, "signal": sig, "anchor_w": aw, "top_n": top,
                   "abs": absf, "win_cagr": f"{cagr:.1%}", "year_ret": ry["nav"].iloc[-1] - 1})
    print(f"  {y}: {sig} aw={aw} top{top} abs={absf} (窗内 {cagr:.1%}) → 当年 {ry['nav'].iloc[-1] - 1:+.1%}")

wf = navs[0]
for n in navs[1:]:
    wf = pd.concat([wf, n * wf.iloc[-1]])
q = prices["QQQ"].loc["2019-01-01":]
qn = q / q.iloc[0]
wfs, qws = perf_stats(wf), perf_stats(qn)
print(f"\n纯化 walk-forward: CAGR {wfs['CAGR']:.2%} | MaxDD {wfs['MaxDD']:.2%} | Calmar {wfs['Calmar']:.2f}")
print(f"QQQ 同期        : CAGR {qws['CAGR']:.2%} | MaxDD {qws['MaxDD']:.2%} | Calmar {qws['Calmar']:.2f}")
print("\n逐年对比:")
wa = annual_returns(wf)
qa = annual_returns(qn)
for y in range(2019, 2027):
    ts = pd.Timestamp(f"{y}-12-31")
    if ts in wa.index:
        print(f"  {y}: 策略 {wa[ts]:+.1%} vs QQQ {qa[ts]:+.1%}")
