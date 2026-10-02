"""第三实现交叉验证：复刻用户的 QQQ80 + TQQQ15(10月均线趋势) + 储备5% 方案
与用户独立引擎（evaluate.py）对照：目标数字 20.97% / -34.66%（2013-01 起）
无前视：调仓日 T 用 T-1 收盘算信号，T 收盘成交，新仓自 T+1 起算（费用记 T 日近似记段首日）
"""

import pandas as pd

from data_layer import load_prices
import config


def main():
    prices = load_prices(config.ALL_TICKERS)
    qqq, tqqq = prices["QQQ"], prices["TQQQ"]
    idx = qqq.loc["2013-01-01":].index
    months = pd.Series(idx, index=idx).groupby(
        [f"{d.year}-{d.month}" for d in idx]).first().values
    rets = pd.DataFrame({"QQQ": qqq.pct_change(), "TQQQ": tqqq.pct_change()}).loc["2013-01-01":]
    cash_daily = 0.02 / 252

    daily_r = pd.Series(0.0, index=idx)
    prev_w = {}
    for i, t in enumerate(months):
        asof = qqq.index[qqq.index.get_loc(t) - 1]
        hist = qqq.loc[:asof]
        me = hist.resample("ME").last().dropna()
        trend = len(me) >= 10 and hist.iloc[-1] > me.iloc[-10:].mean()
        dd = 1 - hist.iloc[-1] / hist.cummax().iloc[-1]
        reserve = 0.05 if dd < 0.1 else 0.03 if dd < 0.2 else 0.01 if dd < 0.3 else 0.0
        w = {"QQQ": 0.8 + (0.05 - reserve),
             "TQQQ": 0.15 if trend else 0.0,
             "CASH": reserve + (0.0 if trend else 0.15)}
        t1 = months[i + 1] if i + 1 < len(months) else idx[-1]
        seg = idx[idx.get_loc(t) + 1: idx.get_loc(t1) + 1]
        if len(seg) == 0:
            prev_w = w
            continue
        cost = 0.5 * sum(abs(w.get(c, 0) - prev_w.get(c, 0))
                         for c in set(w) | set(prev_w)) * 0.001
        pr = (rets.loc[seg, "QQQ"] * w["QQQ"]
              + rets.loc[seg, "TQQQ"] * w["TQQQ"]).fillna(0.0) \
            + cash_daily * w["CASH"]
        pr.iloc[0] -= cost
        daily_r.loc[seg] = pr.values
        prev_w = w

    nav = (1 + daily_r).cumprod()
    years = len(idx) / 252
    cagr = nav.iloc[-1] ** (1 / years) - 1
    maxdd = (nav / nav.cummax() - 1).min()
    print(f"第三实现: CAGR {cagr:+.2%} | MaxDD {maxdd:.2%}")
    print("对照（用户引擎）: CAGR +20.97% | MaxDD -34.66%")
    print(f"差异: {abs(cagr - 0.2097) * 100:.2f}pp / {abs(maxdd + 0.3466) * 100:.2f}pp")


if __name__ == "__main__":
    main()
