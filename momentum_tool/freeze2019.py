"""千里眼检验：2019 年冻结实验
设计窗口 2012-01~2019-12（只用当时可得数据选结构与参数，含当时已存在的 ETF；
本地 SMH 数据 2019-12 起，天然无法被 2019 设计者选用）
样本外 2020-01~2026-09 一次性执行，对照 QQQ
"""

import itertools

import pandas as pd

import config
from data_layer import load_prices
from engine import Strategy, run_backtest
from metrics import perf_stats

prices = load_prices(config.ALL_TICKERS)

DESIGN_END = "2019-12-31"
OOS_START = "2020-01-01"

# 2019 年设计者的候选结构（时代合法性：均为 2019 年已存在且知名的 ETF）
STRUCTURES = {
    "A_因子池": ["SPMO", "MTUM", "RPV", "COWZ", "RSP"],
    "B_因子加QQQ": ["SPMO", "MTUM", "RPV", "COWZ", "RSP", "QQQ"],
    "C_5050加守卫": ["SPMO", "QQQ"],
    "D_QQQ加SOXL": ["QQQ", "SOXL"],
    "E_QQQ加TQQQ": ["QQQ", "TQQQ"],
}

rows = []
for name, uni in STRUCTURES.items():
    for sig, cash, vg in itertools.product(["short136", "classic121"],
                                           [False, True], [0.0, 0.30]):
        s = Strategy(universe=uni, freq="M", top_n=len(uni), signal=sig,
                     cash_rule=cash, weighting="eq", buffer=0, vol_guard=vg)
        r = run_backtest(prices, s, start="2012-01-03", end=DESIGN_END)
        rows.append({"struct": name, "signal": sig, "cash": cash, "vg": vg,
                     **perf_stats(r["nav"])})
        print(".", end="", flush=True)
print()

tr = pd.DataFrame(rows).dropna(subset=["CAGR"])
print("=== 2019 年设计窗口（2012-2019）Top8（按 CAGR） ===")
print(tr.sort_values("CAGR", ascending=False).head(8).round(3).to_string(index=False))

q_des = prices["QQQ"].loc["2012-01-03":DESIGN_END]
q_des = q_des / q_des.iloc[0]
print(f"\nQQQ 设计窗口: CAGR {perf_stats(q_des)['CAGR']:.1%} / MaxDD {perf_stats(q_des)['MaxDD']:.0%}")

# 冻结最优（含并列前3都做样本外，观察选择敏感性）
print("\n=== 样本外执行（2020-01 ~ 2026-09，无千里眼） ===")
q_oos = prices["QQQ"].loc[OOS_START:]
q_oos = q_oos / q_oos.iloc[0]
qs = perf_stats(q_oos)
print(f"QQQ 样本外: CAGR {qs['CAGR']:.2%} / MaxDD {qs['MaxDD']:.1%} / Calmar {qs['Calmar']:.2f}")
for _, row in tr.sort_values("CAGR", ascending=False).head(3).iterrows():
    uni = STRUCTURES[row["struct"]]
    s = Strategy(universe=uni, freq="M", top_n=len(uni), signal=row["signal"],
                 cash_rule=bool(row["cash"]), weighting="eq", buffer=0,
                 vol_guard=row["vg"])
    r = run_backtest(prices, s, start=OOS_START)
    st = perf_stats(r["nav"])
    print(f"{row['struct']:10s} {row['signal']} cash={row['cash']} vg={row['vg']}: "
          f"样本外 CAGR {st['CAGR']:+.2%} / MaxDD {st['MaxDD']:.1%} / Calmar {st['Calmar']:.2f}")
