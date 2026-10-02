"""回测引擎：动量轮动（无杠杆因子池版）
实现约定：
- 无前视：调仓执行日 T 用 T-1 收盘信号、T 收盘价成交；T 当天收益归旧仓，新仓从 T+1 起算
- 动态加入：成员上市满 MIN_HISTORY_DAYS 个交易日才参与排名
- 持仓区间 (T_j, T_{j+1}]：费用扣在 T_j 当日（当日收益仍属旧仓）
- 段内近似：两次调仓之间按每日等权再平衡（段短误差可忽略，换取向量化速度）
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

import config


@dataclass
class Strategy:
    universe: list
    freq: str = "M"              # W / 2W / M / Q
    top_n: int = 3
    signal: str = "comp3612"     # classic121 / comp3612 / short136
    cash_rule: bool = False      # 最强者绝对动量<0 时全池切现金
    buffer: int = 0              # 缓冲带：旧持仓仍排名前 top_n+buffer 则保留，降换手
    weighting: str = "eq"        # eq 等权 / mom 动量得分加权
    trend_filter: bool = False   # 趋势过滤：参考资产跌破 200 日线时切现金
    trend_ref: str = "QQQ"
    anchor: str = None           # 锚定资产：其动量>0 时固定占 anchor_w，其余槽位轮动
    anchor_w: float = 0.5
    abs_filter: bool = False     # 资产级绝对动量过滤：仅 score>0 的资产可入选（GEM 式）
    fast_exit: bool = False      # 慢进快出：建仓月度、段内每周检查持仓 score<0 即切现金
    vol_guard: float = 0.0       # >0 时启用：参考资产 63 日年化波动超此值 → 锚减半+强制现金规则
    vol_cash: bool = True        # vol_guard 触发时是否叠加现金规则（False=仅降锚不退出）
    trade_through: bool = False  # 持仓集合与上期相同时跳过调仓（消除排序微切换的无效换手）
    cost_bps: float = config.COST_BPS

    def label(self) -> str:
        return (f"{self.freq}|top{self.top_n}|{self.signal}|{'CashOn' if self.cash_rule else 'CashOff'}"
                f"|buf{self.buffer}|{self.weighting}|{'Trend' if self.trend_filter else 'NoTrend'}")


def compute_signal(px: pd.Series, signal: str) -> float:
    """基于截至 T-1 的价格序列计算动量分值，窗口数据不足返回 NaN"""
    n = len(px)
    if signal == "classic121":
        if n < 253:
            return np.nan
        return px.iloc[-22] / px.iloc[-253] - 1.0
    if signal == "comp3612":
        if n < 253:
            return np.nan
        r = np.mean([px.iloc[-1] / px.iloc[-64] - 1,
                     px.iloc[-1] / px.iloc[-127] - 1,
                     px.iloc[-1] / px.iloc[-253] - 1])
        vol = px.iloc[-127:].pct_change().std() * np.sqrt(252)
        return r / vol if vol > 0 else np.nan
    if signal == "short136":
        if n < 127:
            return np.nan
        r = np.mean([px.iloc[-1] / px.iloc[-22] - 1,
                     px.iloc[-1] / px.iloc[-64] - 1,
                     px.iloc[-1] / px.iloc[-127] - 1])
        vol = px.iloc[-64:].pct_change().std() * np.sqrt(252)
        return r / vol if vol > 0 else np.nan
    if signal == "w136":            # 敏感加权：0.5×1M + 0.3×3M + 0.2×6M
        if n < 127:
            return np.nan
        r = (0.5 * (px.iloc[-1] / px.iloc[-22] - 1)
             + 0.3 * (px.iloc[-1] / px.iloc[-64] - 1)
             + 0.2 * (px.iloc[-1] / px.iloc[-127] - 1))
        vol = px.iloc[-64:].pct_change().std() * np.sqrt(252)
        return r / vol if vol > 0 else np.nan
    if signal == "c1236":           # 四窗口等权 (1+3+6+12)/4
        if n < 253:
            return np.nan
        r = np.mean([px.iloc[-1] / px.iloc[-22] - 1,
                     px.iloc[-1] / px.iloc[-64] - 1,
                     px.iloc[-1] / px.iloc[-127] - 1,
                     px.iloc[-1] / px.iloc[-253] - 1])
        vol = px.iloc[-64:].pct_change().std() * np.sqrt(252)
        return r / vol if vol > 0 else np.nan
    raise ValueError(signal)


def rebalance_days(index: pd.DatetimeIndex, freq: str) -> list:
    """每个调仓周期的第一个交易日"""
    if freq == "M":
        keys = [f"{d.year}-{d.month}" for d in index]
    elif freq == "ME":            # 每月最后一个交易日
        return list(pd.Series(index, index=index).groupby(
            [f"{d.year}-{d.month}" for d in index]).apply(lambda x: x.index[-1]))
    elif freq == "Q":
        keys = [f"{d.year}-{(d.month - 1) // 3}" for d in index]
    elif freq == "W":
        keys = [d.isocalendar()[:2] for d in index]
    elif freq == "2W":
        keys = [(d.year, d.isocalendar()[1] // 2) for d in index]
    else:
        raise ValueError(freq)
    s = pd.Series(keys, index=index)
    return list(s[~s.duplicated()].index)


def run_backtest(prices: pd.DataFrame, strat: Strategy, start=None, end=None,
                 initial_state=None) -> dict:
    """initial_state=(weights dict, picked list)：跨期续跑时继承上期末持仓（walk-forward 用）"""
    px = prices[strat.universe].loc[start:end].dropna(how="all")
    idx = px.index
    rets = px.pct_change()
    cash_daily = config.CASH_RATE / 252.0

    rebal = [d for d in rebalance_days(idx, strat.freq) if d >= idx[0]]
    daily_r = pd.Series(cash_daily, index=idx)     # 无 initial_state 时起点段现金
    trades, holdings = [], []
    prev_weights, prev_picked, turnover_sum = {}, [], 0.0

    if initial_state is not None:
        # 起点前缀段 [idx[0], rebal[0]] 按继承持仓计收益（含 rebal[0] 当日，费用记当日）
        init_w, init_picked = initial_state
        pre_end = rebal[0] if rebal else idx[-1]
        pre_idx = idx[: idx.get_loc(pre_end) + 1]
        cols = [c for c in init_w if c != "CASH" and c in rets.columns]
        if not cols:
            daily_r.loc[pre_idx] = cash_daily
        else:
            w = pd.Series({c: init_w[c] for c in cols})
            daily_r.loc[pre_idx] = (rets.loc[pre_idx, cols] * w).sum(axis=1).fillna(0.0).values
        prev_weights, prev_picked = dict(init_w), list(init_picked)

    for j, t0 in enumerate(rebal):
        t1 = rebal[j + 1] if j + 1 < len(rebal) else idx[-1]
        seg_idx = idx[idx.get_loc(t0) + 1: idx.get_loc(t1) + 1]   # 持仓区间 (t0, t1]
        pos = prices.index.get_loc(t0)                             # 信号基于 T-1（全量口径）
        if pos == 0:
            continue
        asof = prices.index[pos - 1]

        scores = {}
        for c in strat.universe:
            hist = prices[c].loc[:asof].dropna()                   # 全量历史，防窗口不足
            if len(hist) >= config.MIN_HISTORY_DAYS and hist.index[-1] == asof:
                v = compute_signal(hist, strat.signal)
                if not np.isnan(v):
                    scores[c] = v
        ranked = sorted(scores, key=scores.get, reverse=True)
        if strat.abs_filter:                                        # 资产级绝对动量过滤
            ranked = [c for c in ranked if scores[c] > 0]

        picked = ranked[:strat.top_n]
        if strat.buffer > 0 and prev_picked:                       # 缓冲带：旧持仓未跌出则保留
            qual = ranked[:strat.top_n + strat.buffer]
            keep = [c for c in prev_picked if c in qual]
            new = [c for c in ranked[:strat.top_n] if c not in keep]
            picked = (keep + new)[:strat.top_n]

        is_cash = (not ranked) or (strat.cash_rule and scores[ranked[0]] < 0)
        anchor_w_eff = strat.anchor_w
        if strat.vol_guard > 0:                                     # 波动率状态防御
            ref = prices[strat.trend_ref].loc[:asof].dropna()
            realized_vol = ref.iloc[-63:].pct_change().std() * np.sqrt(252)
            if realized_vol > strat.vol_guard:
                anchor_w_eff = strat.anchor_w / 2.0
                if strat.vol_cash:
                    ref_score = scores.get(strat.trend_ref,
                                           scores[ranked[0]] if ranked else 0.0)
                    is_cash = is_cash or ref_score < 0
        if strat.trend_filter and not is_cash:                     # 参考资产 200 日线过滤
            ref = prices[strat.trend_ref].loc[:asof].dropna()
            if len(ref) >= 200 and ref.iloc[-1] < ref.iloc[-200:].mean():
                is_cash = True
        if is_cash:
            picked = []

        if is_cash:
            target = {"CASH": 1.0}
        elif strat.anchor and scores.get(strat.anchor, float("nan")) > 0:
            rest = [c for c in ranked if c != strat.anchor][:strat.top_n - 1]
            if rest:
                target = {strat.anchor: anchor_w_eff}
                for c in rest:
                    target[c] = (1 - anchor_w_eff) / len(rest)
                picked = [strat.anchor] + rest
            else:
                target = {strat.anchor: 1.0}
                picked = [strat.anchor]
        elif strat.weighting == "mom" and picked and min(scores[c] for c in picked) > 0:
            tot = sum(scores[c] for c in picked)
            target = {c: scores[c] / tot for c in picked}
        else:
            target = {c: 1.0 / len(picked) for c in picked}

        turn = 0.5 * sum(abs(target.get(c, 0.0) - prev_weights.get(c, 0.0))
                         for c in set(target) | set(prev_weights))
        if (strat.trade_through and not is_cash and prev_picked
                and set(picked) == set(prev_picked)):
            target = dict(prev_weights)                             # 持仓集合不变：不调仓不扣费
            turn = 0.0
        daily_r.loc[t0] -= turn * strat.cost_bps / 1e4             # 建仓日扣费（当日收益属旧仓）
        turnover_sum += turn

        if len(seg_idx):
            if is_cash:
                daily_r.loc[seg_idx] = cash_daily
            else:
                hold_end = len(seg_idx)                             # 默认整段持有
                if strat.fast_exit:                                 # 周度检查退出（慢进快出）
                    wk_keys = [f"{d.isocalendar()[0]}-w{d.isocalendar()[1]}"
                               for d in seg_idx]
                    wk_pos = (pd.Series(range(len(seg_idx)))
                              .groupby(wk_keys).apply(lambda x: x.iloc[-1]))
                    for pw in wk_pos:
                        chk = seg_idx[pw]
                        cpos = prices.index.get_loc(chk)
                        if cpos == 0:
                            continue
                        asof_wk = prices.index[cpos - 1]
                        bad = False
                        for c in picked:
                            hist = prices[c].loc[:asof_wk].dropna()
                            if (len(hist) >= config.MIN_HISTORY_DAYS
                                    and compute_signal(hist, strat.signal) < 0):
                                bad = True
                                break
                        if bad:
                            hold_end = pw + 1                        # 触发周当日仍持有，次日起现金
                            break
                daily_r.loc[seg_idx[:hold_end]] = (
                    rets.loc[seg_idx[:hold_end], picked].mul(target).sum(axis=1)
                    .fillna(0.0).values)
                if hold_end < len(seg_idx):                         # 退出后至下次月度调仓：现金
                    exit_turn = 0.5 * float(sum(target.values()))   # 持仓→现金的卖出换手
                    daily_r.loc[seg_idx[hold_end]] -= exit_turn * strat.cost_bps / 1e4
                    daily_r.loc[seg_idx[hold_end:]] = cash_daily
        prev_weights, prev_picked = target, picked
        trades.append({"date": t0, "picked": "CASH" if is_cash else ",".join(picked),
                       "turnover": round(turn, 3)})
        holdings.append({"date": t0, **{c: round(w, 3) for c, w in target.items()}})

    nav = (1 + daily_r).cumprod()
    years = len(idx) / 252.0
    return {
        "nav": nav,
        "annual_turnover": turnover_sum / years,
        "n_rebal": len(rebal),
        "trades": pd.DataFrame(trades),
        "holdings": pd.DataFrame(holdings),
        "final_state": (prev_weights, prev_picked),   # 供跨期续跑继承
    }
