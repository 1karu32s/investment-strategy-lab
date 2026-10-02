"""月度执行信号：按冻结方案输出本月操作单
方案（已三重验证）：QQQ80 + TQQQ15(10月均线趋势) + 储备5%(回撤分档) + 预设退出时间表
用法：python monthly_signal.py [方案起始日 YYYY-MM-DD] [当前持仓描述可忽略]
"""

import sys
from datetime import date

import pandas as pd

from data_layer import load_prices
import config

SCHEME_START = sys.argv[1] if len(sys.argv) > 1 else date.today().strftime("%Y-%m-%d")


def main():
    prices = load_prices(["QQQ", "TQQQ", "SPY"])
    qqq = prices["QQQ"].dropna()
    asof = qqq.index[-1]                       # 最新收盘
    hist = qqq.loc[:asof]
    me = hist.resample("ME").last().dropna()
    trend = len(me) >= 10 and hist.iloc[-1] > me.iloc[-10:].mean()
    dd = 1 - hist.iloc[-1] / hist.cummax().iloc[-1]
    reserve = 0.05 if dd < 0.1 else 0.03 if dd < 0.2 else 0.01 if dd < 0.3 else 0.0

    # 月份计数（自方案起始）
    start = pd.Timestamp(SCHEME_START)
    month_no = (asof.year - start.year) * 12 + (asof.month - start.month) + 1

    w = {"QQQ": 0.8 + (0.05 - reserve),
         "TQQQ": 0.15 if trend else 0.0,
         "CASH": reserve + (0.0 if trend else 0.15)}
    notes = []

    # 退出时间表（预先承诺，不因盈亏调整）
    if 37 <= month_no <= 48:                   # 第37-48月：TQQQ 每月 -1.25pp 转 QQQ
        a = (month_no - 36) / 12
        old = w["TQQQ"]
        w["TQQQ"] = old * (1 - a)
        w["QQQ"] += 0.15 * a
        notes.append(f"退出阶段A（第{month_no}月）：TQQQ 目标已降至 {w['TQQQ']:.2%}")
    elif 49 <= month_no <= 60:                 # 第49-60月：线性转 40% QQQ + 60% SPY
        b = (month_no - 48) / 12
        w = {c: v * (1 - b) for c, v in w.items()}
        w["QQQ"] = w.get("QQQ", 0) + 0.4 * b
        w["SPY"] = w.get("SPY", 0) + 0.6 * b
        notes.append(f"退出阶段B（第{month_no}月）：QQQ/SPY 目标 {0.4 - (0.4 - w['QQQ']):.0%}/{w['SPY']:.0%}")
    elif month_no > 60:
        w = {"QQQ": 0.4, "SPY": 0.6}
        notes.append("方案已结束：维持 40% QQQ + 60% SPY")

    print(f"=== 月度信号（数据截至 {asof.date()}）===")
    print(f"方案第 {month_no} 个月（起始 {SCHEME_START}）")
    print(f"QQQ 距历史高点回撤: {dd:.1%} → 储备档位 {reserve:.0%}")
    print(f"10 个月末均线趋势: {'成立 → 持有 TQQQ' if trend else '失效 → 增强仓转现金'}")
    print(f"本月目标配置: " + "  ".join(f"{c} {v:.0%}" for c, v in w.items() if v > 0))
    for n in notes:
        print(f"※ {n}")
    print("\n执行提醒：每月第一个交易日按上月末数据执行；先投当月预算，再调到目标比例；"
          "趋势失效留下的现金不参与下跌加仓。")


if __name__ == "__main__":
    main()
