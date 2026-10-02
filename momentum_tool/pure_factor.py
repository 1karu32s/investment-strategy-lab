"""纯因子池 + 2019 冻结协议：彻底关掉千里眼的版本
池 = 因子家族（动量/价值/质量/现金流/等权/低波），无行业 ETF、无杠杆、无锚定
设计窗口 2012-2019 选参（网格内自选），样本外 2020-2026 一次性执行
守卫参考 SPY（市场基准，中立代理）
"""

import itertools

import pandas as pd

import config
from data_layer import load_prices
from engine import Strategy, run_backtest
from metrics import annual_returns, perf_stats

prices = load_prices(config.ALL_TICKERS)

PURE_FACTOR_POOL = ["SPMO", "MTUM", "XMMO", "XSMO",      # 动量
                    "RPV", "AVLV", "AVUV",               # 价值
                    "QUAL", "COWZ", "RSP", "USMV"]       # 质量/现金流/等权/低波

DESIGN_END = "2019-12-31"
OOS_START = "2020-01-01"

rows = []
for sig, top, cash, vg, absf in itertools.product(
        ["short136", "classic121"], [2, 3], [False, True], [0.0, 0.30], [False, True]):
    s = Strategy(universe=PURE_FACTOR_POOL, freq="M", top_n=top, signal=sig,
                 cash_rule=cash, weighting="mom", buffer=0, vol_guard=vg,
                 abs_filter=absf, trend_ref="SPY")
    r = run_backtest(prices, s, start="2012-01-03", end=DESIGN_END)
    rows.append({"signal": sig, "top": top, "cash": cash, "vg": vg, "abs": absf,
                 **perf_stats(r["nav"])})
    print(".", end="", flush=True)
print()

tr = pd.DataFrame(rows).dropna(subset=["CAGR"])
print("=== 设计窗口 2012-2019 纯因子池 Top8（按 CAGR） ===")
print(tr.sort_values("CAGR", ascending=False).head(8).round(3).to_string(index=False))
q_des = prices["QQQ"].loc["2012-01-03":DESIGN_END]
qs_d = perf_stats(q_des / q_des.iloc[0])
print(f"QQQ 设计窗口: {qs_d['CAGR']:.1%}/{qs_d['MaxDD']:.0%}")

print("\n=== 样本外 2020-2026 一次性执行 ===")
q_oos = prices["QQQ"].loc[OOS_START:]
qn = q_oos / q_oos.iloc[0]
qs_o = perf_stats(qn)
print(f"QQQ 样本外: {qs_o['CAGR']:.2%} / {qs_o['MaxDD']:.1%} / Calmar {qs_o['Calmar']:.2f}")
for _, row in tr.sort_values("CAGR", ascending=False).head(3).iterrows():
    s = Strategy(universe=PURE_FACTOR_POOL, freq="M", top_n=int(row["top"]),
                 signal=row["signal"], cash_rule=bool(row["cash"]), weighting="mom",
                 buffer=0, vol_guard=row["vg"], abs_filter=bool(row["abs"]),
                 trend_ref="SPY")
    r = run_backtest(prices, s, start=OOS_START)
    st = perf_stats(r["nav"])
    ann = annual_returns(r["nav"])
    print(f"{row['signal']} top{int(row['top'])} cash={row['cash']} vg={row['vg']} "
          f"abs={row['abs']}: 样本外 {st['CAGR']:+.2%}/{st['MaxDD']:.1%}/C{st['Calmar']:.2f}")
    print("    年度:", " ".join(f"{v:+.0%}" for v in ann))
    print("    样本外持仓(最近3次):", r["trades"].tail(3)["picked"].tolist())
