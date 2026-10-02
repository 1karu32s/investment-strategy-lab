"""冻结实验执行器：frozen_comparison_v1.json 的适配实现
状态：diagnostic_unverified（数据闸门未过：新浪未复权价，缺分红再投资总收益序列；
现金收益用 0%/2% 固定年化诊断，现金机制主结论按规格阻断）

账务结构（对应 accounting gate）：
- 每月首个交易日 T 收盘成交；月初现金流先入账再再平衡；同日新资金不赚当日早先收益
- T 日收益归调仓前持仓，新仓自 T+1 起算；买卖均计费（每美元 cost_bps）
- 份额段内不变（段内逐日市值估值，非恒权近似）
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

import os as _os

DATA = Path(__file__).parent / "data"
RESULTS = Path(_os.environ.get("FROZEN_SUMMARY_DIR",
                               Path(__file__).parent / "results" / "frozen"))
RESULTS.mkdir(parents=True, exist_ok=True)

TICKERS = ["QQQ", "TQQQ", "SMH", "IGV", "FDN", "XBI", "SPY"]
POOL = ["SMH", "IGV", "FDN", "XBI"]
STATUS = "diagnostic_unverified"

COST_MAIN, COST_STRESS = 0.0010, 0.0030
CASH_RATES = [0.0, 0.02]


def load_panel():
    px = {}
    for t in TICKERS:
        s = pd.read_csv(DATA / f"{t}.csv", index_col=0, parse_dates=True)[t].dropna()
        px[t] = s
    return pd.DataFrame(px).sort_index()


def month_firsts(idx):
    s = pd.Series(idx, index=idx)
    return list(s.groupby([f"{d.year}-{d.month}" for d in idx]).first().values)


def signals(panel, exec_days):
    """T-1 收盘信息：trend / drawdown / rotation（严格按冻结规格公式）"""
    out = {}
    qqq = panel["QQQ"].dropna()
    for d in exec_days:
        hist = panel.loc[panel.index < d]
        if hist.empty:
            # 首个执行日无 T-1 信息：保守默认（趋势关、零回撤、无轮动选择）
            out[d] = {"trend": False, "dd": 0.0, "picked": []}
            continue
        q = qqq.loc[:hist.index[-1]]
        me = q.resample("ME").last().dropna()
        trend = len(me) >= 10 and q.iloc[-1] > me.iloc[-10:].mean()
        dd = 1 - q.iloc[-1] / q.cummax().iloc[-1]
        scores = {}
        for c in POOL:
            h = panel[c].dropna()
            h = h.loc[:hist.index[-1]]
            if len(h) >= 253:
                s = 0.5 * ((h.iloc[-1] / h.iloc[-127] - 1) + (h.iloc[-1] / h.iloc[-253] - 1))
                if s > 0:
                    scores[c] = (float(s), c)          # tie 按字母序
        picked = [c for _, c in sorted(scores.values(), key=lambda x: (-x[0], x[1]))[:2]]
        out[d] = {"trend": bool(trend), "dd": float(dd), "picked": picked}
    return out


def pool_ready(panel, d):
    """M0/M1 主比较门槛：四只均 ≥253 有效日且最近 253 个市场交易日无缺失"""
    hist = panel.loc[panel.index < d]
    if len(hist) < 253:
        return False
    recent = hist.iloc[-253:]
    return all(recent[c].notna().all() and len(panel[c].dropna()) >= 253 for c in POOL)


def target(scheme, sig, month, glide):
    """返回 dict 目标权重（含 CASH）。glide=True 应用五年退出日历。"""
    t, dd = sig["trend"], sig["dd"]
    if scheme == "B0":
        w = {"QQQ": 1.0}
    elif scheme == "R0":
        w = {"QQQ": 0.95, "CASH": 0.05}
    elif scheme == "R1":
        cash = 0.05 if dd < 0.10 else 0.03 if dd < 0.20 else 0.01 if dd < 0.30 else 0.0
        w = {"QQQ": 1 - cash, "CASH": cash}
    elif scheme == "L0":
        w = {"QQQ": 0.85, "TQQQ": 0.15}
    elif scheme == "L1":
        w = {"QQQ": 0.85, "TQQQ": 0.15, "CASH": 0.0}
        if not t:
            w = {"QQQ": 0.85, "CASH": 0.15}
    elif scheme == "M0":
        w = {"QQQ": 0.80, "CASH": 0.20} if not t else {"QQQ": 0.80}
        if t:
            for c in POOL:
                w[c] = 0.05
    elif scheme == "M1":
        w = {"QQQ": 0.80, "CASH": 0.20} if not t else {"QQQ": 0.80, "CASH": 0.0}
        if t:
            for c in sig["picked"]:
                w[c] = w.get(c, 0) + 0.10
            w["CASH"] = 0.20 - 0.10 * len(sig["picked"])
            if w["CASH"] <= 0:
                del w["CASH"]
    else:
        raise ValueError(scheme)

    if glide:                                            # 五年退出日历（规格：退出后保持零杠杆）
        if month >= 37 and scheme in ("L0", "L1"):
            a = min(1.0, (month - 36) / 12)              # 自 37 月起持续应用，槽位清零后保持零
            if scheme == "L1" and not t:
                w["CASH"] = w.get("CASH", 0) * (1 - a)
            elif "TQQQ" in w:
                w["TQQQ"] = w["TQQQ"] * (1 - a)
                if w["TQQQ"] < 1e-12:
                    del w["TQQQ"]
            w["QQQ"] = w.get("QQQ", 0) + 0.15 * a
        if 49 <= month <= 60:                            # 混合基于已清杠杆的当月目标
            b = (month - 48) / 12
            w = {c: v * (1 - b) for c, v in w.items()}
            w["QQQ"] = w.get("QQQ", 0) + 0.4 * b
            w["SPY"] = w.get("SPY", 0) + 0.6 * b
        elif month > 60:
            w = {"QQQ": 0.4, "SPY": 0.6}
    return w


def simulate(panel, exec_days, sig_map, scheme, start, end, cost, cash_rate,
             initial=1.0, monthly=0.0, glide=False, require_pool=False,
             initial_state=None, cash_returns=None, cash_strict=False):
    """逐日份额账务。initial_state=(sh dict, cash, units, month) 供跨段续跑。
    cash_returns: 逐日现金收益序列（值为日收益率，index=交易日）——无额外换仓费的
    现金代理参考（如 BIL 总收益路径）；优先于标量 cash_rate。
    cash_strict: True 时序列覆盖期内的缺口日阻断（不按 0 收益静默通过）。
    返回 DataFrame(日频账户)、指标 dict、final_state。"""
    px = panel.loc[start:end]
    idx = px.index
    marks = px.ffill()
    cols = list(panel.columns)

    def _cash_factor(d_cur, d_prev):
        """d_prev 收盘 → d_cur 收盘 的现金收益因子。
        cash_strict=True：序列覆盖期内缺失日直接阻断（缺口不得伪装成 0 收益）；
        序列覆盖期之外的日期（窗口超出序列起点前）由资格清单排除，不在模拟内报错。"""
        if cash_returns is not None:
            if d_cur in cash_returns.index:
                return 1.0 + float(cash_returns.loc[d_cur])
            if cash_strict:
                lo, hi = cash_returns.index[0], cash_returns.index[-1]
                if lo < d_cur <= hi:
                    raise RuntimeError(f"cash series gap at {d_cur}")
            return 1.0
        return (1 + cash_rate) ** ((d_cur - d_prev).days / 365.25)

    if initial_state is not None:
        sh, cash, units, month = initial_state
        # 补上段边界隔夜现金收益（与整段连续运行一致）
        pos0 = panel.index.get_loc(idx[0])
        if pos0 > 0 and cash > 0:
            prev_day = panel.index[pos0 - 1]
            cash *= _cash_factor(idx[0], prev_day)
    else:
        sh = {c: 0.0 for c in cols}
        cash = initial
        units, month = 0.0, 0
    flows = {}
    value_rows, exec_log = [], []

    for i, d in enumerate(idx):
        if i > 0 and cash > 0:
            cash *= _cash_factor(d, idx[i - 1])
        vals = {c: sh[c] * marks.at[d, c] if sh[c] else 0.0 for c in cols}
        value = cash + sum(vals.values())
        contribution = 0.0
        if d in exec_days and d in sig_map:
            if require_pool and not pool_ready(panel, d):
                exec_log.append({"date": str(d.date()), "note": "pool_not_ready"})
            else:
                month += 1
                contribution = monthly
                if i == 0 and initial_state is None:
                    flows[d] = initial + contribution
                    units = initial + contribution       # 初始份额=投入本金，首笔费用体现为净值<1
                else:
                    nav_pre = value / units              # 当日收盘、入金前净值
                    units += contribution / nav_pre
                    if contribution:
                        flows[d] = contribution
                cash += contribution
                value += contribution
                w = target(scheme, sig_map[d], month, glide)
                # 成交须有当日真实报价：覆盖所有实际交易的资产（买入 或 卖出清仓）
                for c in cols:
                    if c != "CASH" and (w.get(c, 0) > 0 or sh[c] > 0) \
                            and pd.isna(px.at[d, c]):
                        raise RuntimeError(f"missing execution quote {d} {c}")
                fee = 0.0
                for _ in range(12):                      # 费用与卖出互动的定点迭代
                    traded = sum(abs(w.get(c, 0) * (value - fee) - vals[c]) for c in cols)
                    fee = cost * traded
                after = value - fee
                for c in cols:
                    sh[c] = (w.get(c, 0) * after / px.at[d, c]) if w.get(c, 0) > 0 else 0.0
                cash = w.get("CASH", 0) * after
                value = after
                prev_v = value
                exec_log.append({"date": str(d.date()), "month": month,
                                 "w": {k: round(v, 4) for k, v in w.items()},
                                 "fee": round(fee, 6), "turnover": round(traded / max(value, 1e-12), 4)})
                value_rows.append((d, value, units, cash, dict(sh)))
                continue
        value_rows.append((d, value, units if units > 0 else value, cash, dict(sh)))
        prev_v = value

    df = pd.DataFrame(value_rows, columns=["date", "value", "units", "cash", "sh"])
    sh_cols = sorted({c for s in df["sh"] for c in s})
    for c in sh_cols:
        df[f"sh_{c}"] = [s.get(c, 0.0) for s in df["sh"]]
    df = df.drop(columns=["sh"]).set_index("date")
    df["nav"] = df["value"] / df["units"].replace(0, np.nan)
    df["nav"] = df["nav"].ffill().fillna(df["value"] / max(df["value"].iloc[0], 1e-12))
    years = (idx[-1] - idx[0]).days / 365.25
    # 回撤基准含交易前净值 1.0（首笔费用计入首日回撤）
    peak = np.maximum(df["nav"].cummax(), 1.0)
    dd_series = df["nav"] / peak - 1.0
    twr_dd = float(dd_series.min())
    # 恢复时间：最大回撤的谷底 → 首次回到该谷底对应前峰值
    trough = dd_series.idxmin()
    pre_peak = float(peak.loc[trough])
    after = df["nav"].loc[trough:]
    rec = after[after >= pre_peak]
    rec_days = int((rec.index[0] - trough).days) if len(rec) else None
    final_state = ({c: sh[c] for c in cols}, cash, units, month)
    xirr_v = xirr(flows, df["value"].iloc[-1], idx[-1]) if flows else None
    return df, {"terminal": float(df["value"].iloc[-1]), "contributed": float(sum(flows.values())),
                "XIRR": xirr_v, "TWR_MaxDD": twr_dd, "recovery_days": rec_days,
                "months": month, "years": years, "exec_log": exec_log}, final_state


def xirr(flows, terminal, end):
    if not flows:
        return None
    t0 = min(flows)
    cf = [(-v, (d - t0).days / 365.25) for d, v in flows.items()] + [(terminal, (end - t0).days / 365.25)]

    def npv(r):
        return sum(v / (1 + r) ** t for v, t in cf)
    lo, hi = -0.999, 10.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if npv(mid) > 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def gate_checks(panel, exec_days, sig_map):
    """账务闸门：任何一项 False 即阻断主流程（main 里 fail-stop）"""
    res = {}
    # 1) 零收益守恒：平坦价格 + 零息 + 零费 → 终值=投入、XIRR=0
    flat = panel.copy()
    flat.loc[:, :] = 1.0
    fm = signals(flat, exec_days)
    _, s, _ = simulate(flat, exec_days, fm, "B0", flat.index[0], flat.index[-1],
                    0.0, 0.0, initial=12, monthly=1)
    res["zero_flat_conservation"] = bool(abs(s["terminal"] - s["contributed"]) < 1e-6
                                         and abs(s["XIRR"] or 0) < 1e-8)
    # 1b) 入金价格反例：当日腰斩后入金，TWR 回撤必须恰为 -50%
    demo = flat.iloc[:3].copy()
    demo.loc[:, :] = 1.0
    idx3 = demo.index
    demo2 = pd.DataFrame(1.0, index=idx3, columns=["QQQ"])
    demo2.loc[idx3[2], "QQQ"] = 0.5
    ed3 = [idx3[0], idx3[2]]
    sm3 = {idx3[0]: {"trend": False, "dd": 0.0, "picked": []},
           idx3[2]: {"trend": False, "dd": 0.0, "picked": []}}
    d3, s3, _fs3 = simulate(demo2, ed3, sm3, "B0", idx3[0], idx3[2], 0.0, 0.0,
                      initial=100, monthly=10)
    navs = d3["nav"]
    dd3 = float((navs / navs.cummax() - 1).min())
    res["contribution_price_correct"] = bool(abs(dd3 + 0.50) < 1e-9)
    # 2) 纯持有恒等
    df, s, _fs = simulate(panel, exec_days, sig_map, "B0", panel.index[0], panel.index[-1],
                     0.0, 0.0)
    qq = panel["QQQ"].dropna()
    q_first = qq.loc[qq.index >= df.index[0]].iloc[0]
    q_last = qq.loc[qq.index <= df.index[-1]].iloc[-1]
    res["buy_hold_identity"] = bool(
        abs(df["value"].iloc[-1] / df["value"].iloc[0] - q_last / q_first) < 1e-6)
    # 3) 未来价格扰动不改变此前信号
    future = panel.copy()
    future.loc["2022-02-02":, "QQQ"] *= 2
    sig2 = signals(future, exec_days)
    res["no_lookahead_future_perturb"] = bool(all(
        sig_map[d] == sig2[d] for d in sig_map if d < pd.Timestamp("2022-02-02")))
    # 4) 执行日信号不受当日价格影响（真实验证，非直接赋值）
    dayperturb = panel.copy()
    probe = pd.Timestamp("2021-06-01")
    d0 = min(exec_days, key=lambda x: abs(x - probe))
    dayperturb.loc[d0, :] = dayperturb.loc[d0, :] * 1.5   # 扰动执行日当天价格
    sig3 = signals(dayperturb, exec_days)
    res["exec_uses_prior_close"] = bool(sig_map[d0] == sig3[d0])
    # 5) 缺执行报价必须报错（真实阻断测试）
    holed = panel.copy()
    holed.loc[d0, "QQQ"] = np.nan
    try:
        simulate(holed, exec_days, sig_map, "B0", d0, None, 0.001, 0.02)
        res["missing_quote_raises"] = False
    except RuntimeError:
        res["missing_quote_raises"] = True
    # 6) 退出日历：第 49-60 月 TQQQ 权重必须为 0（L0/L1）
    w49 = target("L0", {"trend": True, "dd": 0.0, "picked": []}, 49, glide=True)
    w60 = target("L1", {"trend": True, "dd": 0.0, "picked": []}, 60, glide=True)
    res["glide_no_releveraging"] = bool(w49.get("TQQQ", 0) == 0 and w60.get("TQQQ", 0) == 0)
    # 6b) 清仓卖出也须当日报价（持有但目标权重为零的资产）
    d4 = pd.DataFrame({"QQQ": [1.0, 1.0, 1.0], "TQQQ": [1.0, 1.0, np.nan]},
                      index=pd.to_datetime(["2020-01-02", "2020-01-03", "2020-02-03"]))
    ed4 = list(d4.index)
    sm4 = {ed4[0]: {"trend": True, "dd": 0.0, "picked": []},
           ed4[2]: {"trend": False, "dd": 0.0, "picked": []}}
    try:
        simulate(d4, ed4, sm4, "L1", ed4[0], ed4[2], 0.001, 0.0)
        res["liquidation_needs_quote"] = False
    except RuntimeError:
        res["liquidation_needs_quote"] = True
    # 6c) 回撤与恢复反例：nav 1.0→2.0→1.2→2.1 → TWR 回撤 -40%，恢复 1 天
    d5 = pd.DataFrame({"QQQ": [1.0, 2.0, 1.2, 2.1]},
                      index=pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07"]))
    sm5 = {d5.index[0]: {"trend": False, "dd": 0.0, "picked": []}}
    df5, s5, _ = simulate(d5, [d5.index[0]], sm5, "B0", d5.index[0], d5.index[-1], 0.0, 0.0)
    res["recovery_and_dd_basis"] = bool(
        abs(s5["TWR_MaxDD"] + 0.4) < 1e-9 and s5["recovery_days"] == 1)
    # 6d) 跨段一致性：整段 = 前段 + 状态继承后段（逐日价值一致）
    seg_point = pd.Timestamp("2018-07-02")
    seg_prev = panel.index[panel.index.get_loc(seg_point) - 1]
    df_full, _, _ = simulate(panel, exec_days, sig_map, "L1", panel.index[0], None,
                             0.001, 0.02, initial=10.0, monthly=1.0, glide=True)
    _, _, st_a = simulate(panel, exec_days, sig_map, "L1", panel.index[0], seg_prev,
                          0.001, 0.02, initial=10.0, monthly=1.0, glide=True)
    df_b, _, _ = simulate(panel, exec_days, sig_map, "L1", seg_point, None,
                          0.001, 0.02, monthly=1.0, glide=True, initial_state=st_a)
    ov = df_full.loc[df_b.index[0]:]
    res["segment_consistency"] = bool(np.allclose(
        ov["value"].values, df_b["value"].values, rtol=1e-9, atol=1e-9))
    # 6e) 逐日现金序列：日收益应用反例（flat 价格，日2现金 +10% → 账户恰 +0.5）
    idx6 = pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-06"])
    d6 = pd.DataFrame({"QQQ": [1.0, 1.0, 1.0]}, index=idx6)
    sm6 = {idx6[0]: {"trend": False, "dd": 0.0, "picked": []}}
    cr6 = pd.Series([0.0, 0.10, 0.0], index=idx6)
    df6, s6, _ = simulate(d6, [idx6[0]], sm6, "R0", idx6[0], idx6[-1], 0.0, 0.0,
                          initial=100, cash_returns=cr6)
    res["cash_series_daily_factor"] = bool(abs(df6["value"].iloc[-1] - 100.5) < 1e-9)
    # 6f) 逐日现金序列模式下的跨段一致性
    cr_real = None
    bil_path = Path(_os.environ.get("FROZEN_BIL_REFERENCE", DATA / "bil_market_total_return.csv"))
    if bil_path.exists():
        b = pd.read_csv(bil_path, parse_dates=["date"]).set_index("date")
        cr_real = b["gross_exdate_total_return_index"].pct_change().dropna()
    if cr_real is not None:
        seg2 = pd.Timestamp("2021-07-01")
        seg2_prev = panel.index[panel.index.get_loc(seg2) - 1]
        dfx, _, _ = simulate(panel, exec_days, sig_map, "L1", panel.index[0], None,
                             0.001, 0.0, initial=10.0, monthly=1.0,
                             cash_returns=cr_real)
        _, _, stx = simulate(panel, exec_days, sig_map, "L1", panel.index[0], seg2_prev,
                             0.001, 0.0, initial=10.0, monthly=1.0,
                             cash_returns=cr_real)
        dfx2, _, _ = simulate(panel, exec_days, sig_map, "L1", seg2, None,
                              0.001, 0.0, monthly=1.0, initial_state=stx,
                              cash_returns=cr_real)
        ovx = dfx.loc[dfx2.index[0]:]
        res["cash_series_segment_consistency"] = bool(np.allclose(
            ovx["value"].values, dfx2["value"].values, rtol=1e-9, atol=1e-9))
        # 6g) 端到端扰动：现金序列变化必须传导到主流程输出（R0 含 5% 现金仓）
        cr_pert = cr_real.copy()
        mid = cr_pert.index[len(cr_pert) // 2]
        cr_pert.loc[mid] += 0.001                   # 单日 +10bp 扰动
        dfp, sp, _ = simulate(panel, exec_days, sig_map, "R0", "2016-10-03", None,
                              0.001, 0.0, initial=1.0, monthly=1.0,
                              cash_returns=cr_pert)
        dfq, sq, _ = simulate(panel, exec_days, sig_map, "R0", "2016-10-03", None,
                              0.001, 0.0, initial=1.0, monthly=1.0,
                              cash_returns=cr_real)
        res["cash_perturbation_e2e"] = bool(
            sp["terminal"] != sq["terminal"]
            and abs(sp["terminal"] - sq["terminal"]) > 1e-12)
        # 6h) 现金序列覆盖期内的缺口必须阻断（缺口≠0收益）
        cr_gap = cr_real.drop(cr_real.index[len(cr_real) // 3])
        try:
            simulate(panel, exec_days, sig_map, "R0", "2016-10-03", None,
                     0.001, 0.0, initial=1.0, monthly=1.0,
                     cash_returns=cr_gap, cash_strict=True)
            res["cash_gap_blocks"] = False
        except RuntimeError:
            res["cash_gap_blocks"] = True
    else:
        res["cash_series_segment_consistency"] = "skipped_no_bil_series"
        res["cash_perturbation_e2e"] = "skipped_no_bil_series"
        res["cash_gap_blocks"] = "skipped_no_bil_series"
    # 拆股日连续性：修正重建后 |r|>35% 只允许已知真实事件
    known_events = {pd.Timestamp("2020-03-16"), pd.Timestamp("2020-03-12"),
                    pd.Timestamp("2025-04-09"), pd.Timestamp("2020-03-24")}
    viol = []
    for c in panel.columns:
        r = panel[c].pct_change()
        for d, v in r[abs(r) > 0.35].items():
            if d not in known_events:
                viol.append((c, str(d.date()), round(float(v), 4)))
    res["split_day_continuity"] = len(viol) == 0          # 恒为 bool，失败必被 fail-stop 拦截
    res["split_day_continuity_detail"] = viol
    # 卖出转现金须计费：L1 趋势关闭卖出 TQQQ 槽，费用恰为 cost×卖出额
    idx7 = pd.to_datetime(["2020-01-02", "2020-02-03"])
    d7 = pd.DataFrame({"QQQ": [1.0, 1.0], "TQQQ": [1.0, 1.0]}, index=idx7)
    # A: 两月趋势都开（仅首月建仓费）；B: 次月趋势关（建仓费+卖出TQQQ槽费）
    smA = {idx7[0]: {"trend": True, "dd": 0.0, "picked": []},
           idx7[1]: {"trend": True, "dd": 0.0, "picked": []}}
    smB = {idx7[0]: {"trend": True, "dd": 0.0, "picked": []},
           idx7[1]: {"trend": False, "dd": 0.0, "picked": []}}
    _, tA0, _ = simulate(d7, list(smA.keys()), smA, "L1", idx7[0], idx7[-1], 0.0, 0.0, initial=100)
    _, tA1, _ = simulate(d7, list(smA.keys()), smA, "L1", idx7[0], idx7[-1], 0.001, 0.0, initial=100)
    _, tB1, _ = simulate(d7, list(smB.keys()), smB, "L1", idx7[0], idx7[-1], 0.001, 0.0, initial=100)
    fee_setup = tA0["terminal"] - tA1["terminal"]        # 纯建仓费
    fee_total = tA0["terminal"] - tB1["terminal"]        # 建仓+卖出费
    sell_fee = fee_total - fee_setup                     # 差分=卖出转现金的费用
    expected = 0.15 * 0.001 * tA1["terminal"]            # 卖出15%仓位×10bp（按扣建仓费后价值）
    res["sell_into_cash_fee"] = bool(abs(sell_fee - expected) / expected < 1e-3)
    # 未来价格扰动前：份额、净值、账户价值逐日不变
    if panel.index[-1] > pd.Timestamp("2019-01-01"):
        cut = pd.Timestamp("2018-06-01")
        _, _, _ = simulate(panel, exec_days, sig_map, "L1", panel.index[0], None,
                           0.001, 0.02, initial=10, monthly=1)
        fut = panel.copy()
        fut.loc[cut:, :] = fut.loc[cut:, :] * 2
        sm_f = signals(fut, exec_days)
        cut_prev = panel.index[panel.index.get_loc(cut) - 1]   # 不含 cut 日（其价格已改）
        dfa, _, _ = simulate(panel, exec_days, sig_map, "L1", panel.index[0], cut_prev,
                             0.001, 0.02, initial=10, monthly=1)
        dfb, _, _ = simulate(fut, exec_days, sm_f, "L1", fut.index[0], cut_prev,
                             0.001, 0.02, initial=10, monthly=1)
        res["perturb_before_invariance"] = bool(
            np.allclose(dfa["value"].values, dfb["value"].values, rtol=1e-12, atol=1e-12)
            and np.allclose(dfa["nav"].values, dfb["nav"].values, rtol=1e-12, atol=1e-12)
            and np.allclose(dfa["units"].values, dfb["units"].values, rtol=1e-12, atol=1e-12))
    # 闸门自检：注入假拆股跳变，fail-stop 逻辑必须判失败
    poisoned = panel.copy()
    col = poisoned.columns[0]
    mid = poisoned.index[len(poisoned) // 2]
    poisoned.loc[mid, col] = poisoned[col].iloc[len(poisoned) // 2 - 1] * 0.5
    r_bad = poisoned[col].pct_change()
    fake_jumps = [d for d, v in r_bad[abs(r_bad) > 0.35].items() if d not in known_events]
    res["split_gate_selfcheck"] = len(fake_jumps) > 0      # 注入必被检出
    # T 日收益归属：切换日 TQQQ+20% 不得计入新仓（终值须恰 100）
    idx8 = pd.to_datetime(["2020-01-02", "2020-01-03", "2020-02-03", "2020-02-04"])
    d8 = pd.DataFrame({"QQQ": [1.0, 1.0, 1.0, 1.0],
                       "TQQQ": [1.0, 1.0, 1.2, 1.2]}, index=idx8)
    sm8 = {idx8[0]: {"trend": False, "dd": 0.0, "picked": []},
           idx8[2]: {"trend": True, "dd": 0.0, "picked": []}}
    df8, _, _ = simulate(d8, list(sm8.keys()), sm8, "L1", idx8[0], idx8[-1], 0.0, 0.0,
                         initial=100)
    res["t_day_attribution"] = bool(abs(df8["value"].iloc[-1] - 100.0) < 1e-9)
    # 年度边界首日收益：直接测生产函数 metrics.annual_returns（拦住其回归）
    from metrics import annual_returns as _ar
    idx9 = pd.to_datetime(["2025-12-30", "2025-12-31", "2026-01-02", "2026-01-05"])
    nav9 = pd.Series([1.0, 1.0, 1.1, 1.1], index=idx9)
    res["annual_boundary_firstday"] = bool(abs(_ar(nav9).iloc[-1] - 0.10) < 1e-9)
    # 份额漂移重放（主输入抽样窗口，容忍 1e-8）
    if panel.index[-1] > pd.Timestamp("2019-07-01"):
        s_win, e_win = pd.Timestamp("2019-01-02"), pd.Timestamp("2019-06-30")
        dfp, mp, _ = simulate(panel, exec_days, sig_map, "L0", s_win, e_win,
                              0.001, 0.02, initial=1000)
        el = {pd.Timestamp(e["date"]): e for e in mp["exec_log"]}
        sh = {c: 0.0 for c in panel.columns}
        cash, vals_r = 1000.0, []
        for d in dfp.index:
            v = cash + sum(sh[c] * panel.at[d, c] for c in sh if sh[c])
            if d in el and d in sig_map:
                w, fee = el[d]["w"], el[d]["fee"]
                after = v - fee
                for c in sh:
                    sh[c] = w.get(c, 0) * after / panel.at[d, c] if w.get(c, 0) > 0 else 0.0
                cash = w.get("CASH", 0) * after
                v = after
            vals_r.append(v)
        rel = float((pd.Series(vals_r, index=dfp.index) / dfp["value"] - 1).abs().max())
        res["intra_segment_drift_replay"] = bool(rel < 1e-8)
        res["intra_segment_drift_replay_detail"] = rel
    # 扰动前不变（完整运行，历史前缀含各资产份额）
    if panel.index[-1] > pd.Timestamp("2018-07-01"):
        cut = pd.Timestamp("2018-06-01")
        cut_prev = panel.index[panel.index.get_loc(cut) - 1]
        fut = panel.copy()
        fut.loc[cut:, :] = fut.loc[cut:, :] * 2
        sm_f = signals(fut, exec_days)
        dfa, _, _ = simulate(panel, exec_days, sig_map, "L1", panel.index[0], None,
                             0.001, 0.02, initial=10, monthly=1)
        dfb, _, _ = simulate(fut, exec_days, sm_f, "L1", fut.index[0], None,
                             0.001, 0.02, initial=10, monthly=1)
        cols = ["value", "units", "nav"] + [c for c in dfa.columns if c.startswith("sh_")]
        ok_cols = all(np.allclose(dfa[c].loc[:cut_prev].values,
                                  dfb[c].loc[:cut_prev].values,
                                  rtol=1e-12, atol=1e-12) for c in cols)
        res["perturb_before_invariance"] = bool(ok_cols and len(dfa) == len(dfb))
    return res


REQUIRED_GATES = [
    "zero_flat_conservation", "contribution_price_correct", "buy_hold_identity",
    "no_lookahead_future_perturb", "exec_uses_prior_close", "missing_quote_raises",
    "glide_no_releveraging", "liquidation_needs_quote", "recovery_and_dd_basis",
    "segment_consistency", "split_day_continuity", "split_gate_selfcheck",
    "sell_into_cash_fee", "t_day_attribution", "annual_boundary_firstday",
    "intra_segment_drift_replay", "perturb_before_invariance",
]
CASH_GATES = ["cash_series_daily_factor", "cash_series_segment_consistency",
              "cash_perturbation_e2e", "cash_gap_blocks"]


def validate_gates(gates, cash_required):
    """严格布尔校验。阻断条件（必需与现金闸门一致）：
      - 缺失、None、False、或任何非 (True / 显式 skipped:...) 值 → 阻断
    cash_required 决定 skipped 的适用性：
      - True 时现金闸门 skipped（未跑）→ 阻断（当前输入要求逐日现金）
      - False 时 skipped 合法（标量诊断模式未跑现金测试）；
        现金测试 True 恒合法（测试通过与当前输入是否适用是两回事）"""
    def _bad(v, required_here):
        if v is True:
            return False
        if isinstance(v, str) and v.startswith("skipped"):
            return required_here          # skipped 仅在"该测试被要求时"阻断
        return True                        # None/False/其他 → 一律阻断
    missing = [g for g in REQUIRED_GATES + CASH_GATES if g not in gates]
    not_ok = [k for k in REQUIRED_GATES if k in gates and gates[k] is not True]
    cash_bad = [g for g in CASH_GATES if g in gates and _bad(gates[g], cash_required)]
    bad = missing + not_ok + cash_bad
    if bad:
        raise RuntimeError(f"闸门校验失败（缺失/非True/现金状态不符）: {bad}")
    return True


def m_scheme_start(panel, exec_days):
    """M 系起点 = 冻结规则决定：池内四资产 253 有效日且最近 253 市场日无缺失的
    首个执行日（无硬编码日期）"""
    for d in exec_days:
        if pool_ready(panel, d):
            return pd.Timestamp(d)
    return None


def window_eligibility(panel, exec_days, cash_cov=None, start_min="2013-01-01"):
    """P2 逐窗资格清单：起点/终点（起点月+59 的月末，与模拟终点一致）/60 执行月/
    信号预热/池完整/窗口内面板缺值/现金覆盖，及合格判定与原因。
    终点规则统一为 +59 月：窗口=起点月起共 60 个执行月。"""
    months = pd.Series(panel.index, index=panel.index).groupby(
        [f"{d.year}-{d.month}" for d in panel.index]).first()
    rows = []
    pool_cols = POOL
    for d0 in months.values:
        d0 = pd.Timestamp(d0)
        if d0 < pd.Timestamp(start_min):
            continue
        end = (d0.to_period("M") + 59).end_time.normalize()
        n_exec = sum(1 for d in months.values
                     if d0 <= pd.Timestamp(d) <= min(end, pd.Timestamp(panel.index[-1])))
        reasons = []
        ok = True
        if end > pd.Timestamp(panel.index[-1]):
            ok = False
            reasons.append("数据不足60执行月")
        if n_exec < 60 and ok is False:
            pass
        # 信号预热：TQQQ/轮动需 252 日历史；QQQ 趋势需 10 个月末
        hist = panel.loc[panel.index < d0]
        warm = len(hist) >= 253
        if not warm:
            ok = False
            reasons.append(f"预热不足({len(hist)}日<253)")
        pool_ok = pool_ready(panel, d0)
        # 窗口内面板缺值明细（不删除不填充，如实记录）
        win = panel.loc[d0:min(end, pd.Timestamp(panel.index[-1]))]
        missing = {c: int(win[c].isna().sum()) for c in panel.columns
                   if win[c].isna().sum() > 0}
        if missing:
            ok = False
            reasons.append(f"面板缺值{missing}")
        cash_ok = True
        if cash_cov is not None:
            cash_ok = (cash_cov[0] <= d0) and (cash_cov[1] >= min(end, pd.Timestamp(panel.index[-1])))
            if not cash_ok:
                ok = False
                reasons.append("现金序列未覆盖窗口")
        rows.append({"start": d0.date(), "end": min(end, pd.Timestamp(panel.index[-1])).date(),
                     "exec_months_available": n_exec,
                     "warmup_days": len(hist), "pool_ready": bool(pool_ok),
                     "panel_missing": json.dumps(missing) if missing else "",
                     "cash_covered": bool(cash_ok),
                     "eligible": bool(ok),
                     "reason": "; ".join(reasons) if reasons else "合格"})
    return pd.DataFrame(rows)


def main():
    import os
    import sys
    if _os.environ.get("FROZEN_QUICK") == "1" and "FROZEN_SUMMARY_DIR" not in _os.environ:
        # QUICK/验证运行禁止写正式交付目录
        import tempfile as _tf
        _os.environ["FROZEN_SUMMARY_DIR"] = _tf.mkdtemp(prefix="frozen_quick_")
        print(f"QUICK 模式输出已隔离至: {_os.environ['FROZEN_SUMMARY_DIR']}")
    RESULTS = Path(_os.environ.get("FROZEN_SUMMARY_DIR",
                                   str(Path(__file__).parent / "results" / "frozen")))
    # 输入选择：默认旧缓存；FROZEN_PANEL/FROZEN_CASH 指定 P0 诊断面板与逐日现金
    panel_path = os.environ.get("FROZEN_PANEL")
    cash_path = os.environ.get("FROZEN_CASH")
    cash_series_file = None
    if panel_path:
        p = pd.read_csv(panel_path, index_col=0, parse_dates=True)
        p = p[[c for c in ["QQQ", "TQQQ", "SMH", "IGV", "FDN", "XBI", "SPY"]
               if c in p.columns]]
        panel = p.dropna(how="all")
        input_note = f"P0 诊断面板(Tiingo 重建, 与 candidate 累计互证 0-2.3bp): {panel_path}"
    else:
        panel = load_panel()
        input_note = "旧新浪缓存(未复权)"
    if cash_path:
        cash_series_file = cash_path
    print(f"输入: {input_note}" + (f" | 现金序列: {cash_path}" if cash_path else " | 现金: 标量诊断利率"))
    exec_days = month_firsts(panel.index)
    sig_map = signals(panel, exec_days)

    cr_series = None
    if cash_series_file:
        cs = pd.read_csv(cash_series_file, index_col=0, parse_dates=True)
        cr_series = cs.iloc[:, 0]
    gates = gate_checks(panel, exec_days, sig_map)
    gate_pass = {k: v for k, v in gates.items() if not k.endswith(("_detail",))}
    gate_details = {k: v for k, v in gates.items() if k.endswith(("_detail",))}
    (RESULTS / "engine_gate_results.json").write_text(
        json.dumps({"status": STATUS, "gates": gate_pass,
                    "gate_details": gate_details}, indent=1, ensure_ascii=False))
    validate_gates(gates, cash_required=cr_series is not None)   # 模拟开始前严格校验

    quick = _os.environ.get("FROZEN_QUICK") == "1"
    schemes = ["B0", "R0", "L1"] if quick else ["B0", "R0", "R1", "L0", "L1", "M0", "M1"]
    start_main = pd.Timestamp("2013-01-02")
    # M 系起点由冻结的历史充分性规则决定（无硬编码日期）
    m_start = m_scheme_start(panel, exec_days)
    starts = {s: (m_start if s in ("M0", "M1") else start_main) for s in schemes}
    print(f"M 系规则起点: {m_start.date() if m_start is not None else 'N/A（池永不就绪）'}")

    # P2 逐窗资格清单（+59 月终点与模拟一致；含缺值/预热/池/现金覆盖明细）
    bil_path = Path(_os.environ.get("FROZEN_BIL_REFERENCE", DATA / "bil_market_total_return.csv"))
    cash_cov = None
    if cr_series is not None:
        cash_cov = (cr_series.index[0], cr_series.index[-1])
    elif bil_path.exists():
        b = pd.read_csv(bil_path, parse_dates=["date"]).set_index("date")
        cash_cov = (b.index[0], b.index[-1])
    elig = window_eligibility(panel, exec_days, cash_cov=cash_cov)
    elig.to_csv(RESULTS / "window_eligibility.csv", index=False)
    n_elig = int(elig["eligible"].sum())
    print(f"逐窗资格清单: {len(elig)} 个候选窗口, {n_elig} 个合格 "
          f"(明细见 results/frozen/window_eligibility.csv)")

    summary = {"status": STATUS,
               "data_note": input_note + "；拆股日重建已修正(F=prod(u>t))并经独立验收面板逐日互证；数据闸门未过，全部结果为诊断性",
               "cash_note": ("BIL 逐日现金(诊断, 无换仓费现金代理)" if cr_series is not None else "现金 0%/2% 为固定诊断利率"),
               "full_one_shot": {}, "constant_rule_5y": {}, "glide_5y": {}}

    # A) 一次性全期（恒定规则，10bp 主成本；30bp 与现金0%做敏感性）
    for s in schemes:
        for cost, tag in [(COST_MAIN, "cost10"), (COST_STRESS, "cost30")]:
            for cr, crtag in ([(0.02, "cash2")] if cost == COST_MAIN else [(0.02, "cash2"), (0.0, "cash0")]):
                cr_ser = None if crtag == "cash0" else cr_series   # cash0: 真正关闭序列
                df, m, _ = simulate(panel, exec_days, sig_map, s, starts[s], None, cost, cr,
                                 require_pool=(s in ("M0", "M1")),
                                 cash_returns=cr_ser, cash_strict=cr_ser is not None)
                key = f"{s}|{tag}|{crtag}"
                summary["full_one_shot"][key] = {k: v for k, v in m.items() if k != "exec_log"}

    # B) 五年窗口：恒定规则 + 退出日历 两套，主成本 10bp、现金 2%
    # 终点规则与模拟一致：起点月 +59 的月末（60 个执行月；含 2021-10 起点）
    win_starts = [pd.Timestamp(d) for d in exec_days if pd.Timestamp(d) >= pd.Timestamp("2013-01-01")]
    if quick:
        win_starts = win_starts[:3] + win_starts[-3:]
    win_starts = [d for d in win_starts
                  if (d.to_period("M") + 59).end_time.normalize()
                  <= panel.index[-1] + pd.Timedelta(days=5)]
    paired_rows = []
    for s in schemes:
        ws = [d for d in win_starts if d >= starts[s]]
        for glide, gtag in [(False, "const"), (True, "glide")]:
            terms, xirrs, dds = [], [], []
            for d0 in ws:
                e = (d0.to_period("M") + 59).end_time.normalize()
                df, m, _ = simulate(panel, exec_days, sig_map, s, d0, e, COST_MAIN, 0.02,
                                 initial=12, monthly=1, glide=glide,
                                 require_pool=(s in ("M0", "M1")),
                                 cash_returns=cr_series, cash_strict=cr_series is not None)
                if m["months"] != 60:
                    continue
                terms.append(m["terminal"]); xirrs.append(m["XIRR"]); dds.append(m["TWR_MaxDD"])
            if terms:
                summary[f"{'glide_5y' if glide else 'constant_rule_5y'}"][s] = {
                    "windows": len(terms),
                    "terminal_min": min(terms), "terminal_P10": float(np.percentile(terms, 10)),
                    "terminal_median": float(np.median(terms)),
                    "terminal_P90": float(np.percentile(terms, 90)), "terminal_max": max(terms),
                    "xirr_median": float(np.median(xirrs)), "worst_TWR_dd": min(dds),
                    "loss_fraction": float(np.mean([t < 72 for t in terms]))}

    # C) 配对（同窗口终值比）：9 对比较 × 敏感性（主 10bp/现金2%；30bp 与 现金0% 覆盖五年 glide）
    comps = [("R0", "B0"), ("R1", "R0"), ("R1", "B0"), ("L0", "B0"), ("L1", "L0"),
             ("L1", "B0"), ("M1", "M0"), ("M0", "B0"), ("M1", "B0")]
    if quick:
        comps = [c for c in comps if c[0] in schemes and c[1] in schemes]
    for glide, gtag in [(True, "glide"), (False, "const")]:
        sens = [(COST_MAIN, 0.02, "")]
        if glide:                                        # 决策口径加敏感性
            sens += [(COST_STRESS, 0.02, "|cost30"), (COST_MAIN, 0.0, "|cash0")]
        for cost, cr, stag in sens:
            cr_ser = None if stag == "|cash0" else cr_series   # cash0: 真正关闭序列
            for tr, ctl in comps:
                ws = [d for d in win_starts if d >= max(starts[tr], starts[ctl])]
                ratios = []
                for d0 in ws:
                    e = (d0.to_period("M") + 59).end_time.normalize()
                    _, mt, _fst = simulate(panel, exec_days, sig_map, tr, d0, e, cost, cr,
                                     initial=12, monthly=1, glide=glide,
                                     require_pool=(tr in ("M0", "M1")),
                                     cash_returns=cr_ser, cash_strict=cr_ser is not None)
                    _, mc, _fsc = simulate(panel, exec_days, sig_map, ctl, d0, e, cost, cr,
                                     initial=12, monthly=1, glide=glide,
                                     require_pool=(ctl in ("M0", "M1")),
                                     cash_returns=cr_ser, cash_strict=cr_ser is not None)
                    if mt["months"] == 60 and mc["months"] == 60 and mc["terminal"] > 0:
                        ratios.append((str(d0.date()), mt["terminal"] / mc["terminal"]))
                if ratios:
                    vals = [r for _, r in ratios]
                    summary.setdefault("paired", {})[f"{tr}_vs_{ctl}|{gtag}{stag}"] = {
                        "n": len(vals), "min": min(vals), "P10": float(np.percentile(vals, 10)),
                        "median": float(np.median(vals)), "P90": float(np.percentile(vals, 90)),
                        "max": max(vals), "win_rate": float(np.mean([v > 1 for v in vals]))}
                    if not stag:
                        pd.DataFrame(ratios, columns=["start", "ratio"]).to_csv(
                            RESULTS / f"paired_{tr}_vs_{ctl}_{gtag}.csv", index=False)

    # 接线断言：cash0 必须真正关闭现金序列。仅对含现金仓位的方案对生效——
    # 双方均无现金仓的对（如 L0_vs_B0）cash0 与主结果相同是正确行为
    no_cash_pairs = {"L0_vs_B0"}
    if cr_series is not None:
        for key, v in summary.get("paired", {}).items():
            base_key = key.replace("|cash0", "")
            if key.endswith("|cash0") and base_key in summary["paired"]:
                if base_key.split("|")[0] not in no_cash_pairs and \
                        v["median"] == summary["paired"][base_key]["median"]:
                    raise RuntimeError(f"cash0 敏感性与主结果相同，接线失效: {key}")
    (RESULTS / "summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False, default=str))
    print(json.dumps({k: v for k, v in summary.items() if k not in ("full_one_shot",)}, indent=1, ensure_ascii=False, default=str)[:3000])
    print(f"\n交付物目录: {RESULTS}")


if __name__ == "__main__":
    main()
