"""双轨定投模拟器 v2（口径修正版，对应审计三项之二/三）
修正 1：XIRR 的投入按每月完整预算计（含未投入的弹药——未投的现金也是资金成本）
修正 2：账户为日频净值（含弹药现金），回撤用 TWR（剔除月初现金流的当日影响）
"""

import pandas as pd

import config
from engine import Strategy, run_backtest

START = "2013-01-02"
BASE, BUDGET, TRACK_SPLIT = 1.0, 2.0, 0.7


def pyramid_factor(dd):
    if dd <= 0.10:
        return 1.0
    if dd <= 0.20:
        return 1.5
    if dd <= 0.30:
        return 2.0
    return 3.0


def xirr(flows: dict, final_value: float, first_day, last_day) -> float:
    def npv(rate):
        out = sum(-v / (1 + rate) ** ((d - first_day).days / 365.25)
                  for d, v in flows.items())
        inn = final_value / (1 + rate) ** ((last_day - first_day).days / 365.25)
        return out + inn
    lo, hi = -0.9, 10.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if npv(mid) > 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def simulate(prices, core_nav, rot_nav, pyramid=True):
    """XIRR 按完整预算记投入；日频账户净值（含弹药现金）；TWR 回撤剔除月初流入"""
    qqq = prices["QQQ"].loc[START:]
    roll_max = qqq.cummax()
    month_first = {}
    for d in qqq.index:
        month_first.setdefault(f"{d.year}-{d.month}", d)

    core = core_nav.reindex(qqq.index).ffill()
    rot = rot_nav.reindex(qqq.index).ffill()

    sa = sb = ammo = 0.0
    flows = {}
    daily_v = pd.Series(index=qqq.index, dtype=float)
    month_state = {}                      # 月标签 -> (sa, sb, ammo) 该月全程有效
    labels = [f"{d.year}-{d.month}" for d in qqq.index]

    for label, t in month_first.items():
        px_q = qqq.loc[t]
        dd = 1 - px_q / roll_max.loc[:t].iloc[-1]
        pf = pyramid_factor(dd) if pyramid else 1.0
        if pyramid:
            w_core = BASE * TRACK_SPLIT * pf
            w_rot = BASE * (1 - TRACK_SPLIT)       # 平时投 1X 存 1X 弹药
        else:
            w_core, w_rot = TRACK_SPLIT, 1 - TRACK_SPLIT
            pf = 1.0                                # 等额=每月满投预算
        want = BUDGET if not pyramid else w_core + w_rot
        spend = max(0.0, min(want, BUDGET + ammo))
        ammo += BUDGET - spend
        wsum = w_core + w_rot
        ca = spend * w_core / wsum
        cb = spend * w_rot / wsum
        sa += ca / core.loc[t]
        sb += cb / rot.loc[t]
        flows[t] = BUDGET                 # 完整预算记投入（无论是否实际买入）
        month_state[label] = (sa, sb, ammo)

    for t, label in zip(qqq.index, labels):
        sa_c, sb_c, am_c = month_state[label]
        daily_v.loc[t] = sa_c * core.loc[t] + sb_c * rot.loc[t] + am_c

    # TWR（基金单位化）：月初流入按前日净值申购份额，日频净值=市值/份额
    units, prev_nav = 0.0, 1.0
    unit_nav = pd.Series(index=qqq.index, dtype=float)
    for i, t in enumerate(qqq.index):
        f = flows.get(t, 0.0)
        if i == 0:
            units = f if f > 0 else 1.0
        elif f > 0:
            units += f / prev_nav
        unit_nav.loc[t] = daily_v.loc[t] / units
        prev_nav = unit_nav.loc[t]
    maxdd = (unit_nav / unit_nav.cummax() - 1).min()

    r = xirr(flows, daily_v.iloc[-1], qqq.index[0], qqq.index[-1])
    return {"XIRR": r, "MaxDD_TWR": maxdd, "终值含弹药": daily_v.iloc[-1],
            "累计投入": sum(flows.values())}


def main():
    from data_layer import load_prices
    prices = load_prices(config.ALL_TICKERS)

    navs = {
        "QQQ": prices["QQQ"].loc[START:],
        "科技池": run_backtest(prices, Strategy(**config.FINAL_ROTATION), start=START)["nav"],
        "LEVERED": run_backtest(prices, Strategy(**config.LEVERED), start=START)["nav"],
    }

    print(f"定投模拟 v2（{START} 至今，月预算 {BUDGET}X，压舱 {TRACK_SPLIT:.0%}，拆分已修正数据）")
    print("口径：XIRR 完整预算；回撤 TWR 日频剔除现金流\n")
    for core_name in ["QQQ", "LEVERED"]:
        for rot_name in ["科技池", "LEVERED"]:
            if core_name == "LEVERED" and rot_name == "科技池":
                continue
            for pyr, tag in [(True, "金字塔"), (False, "等额")]:
                res = simulate(prices, navs[core_name], navs[rot_name], pyramid=pyr)
                print(f"压舱{core_name:6s}+轮动{rot_name:4s} {tag}: "
                      f"XIRR {res['XIRR']:+.2%} | TWR MaxDD {res['MaxDD_TWR']:.1%} | "
                      f"终值 {res['终值含弹药']:7.1f}X / 投入 {res['累计投入']:.0f}X")


if __name__ == "__main__":
    main()
