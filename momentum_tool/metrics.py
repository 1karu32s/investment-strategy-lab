"""绩效指标与对比报告"""

import numpy as np
import pandas as pd

import config

RF = config.CASH_RATE


def perf_stats(nav: pd.Series) -> dict:
    nav = nav.dropna()
    years = len(nav) / 252.0
    cagr = (nav.iloc[-1] / nav.iloc[0]) ** (1 / years) - 1 if years > 0 else np.nan
    daily = nav.pct_change().dropna()
    vol = daily.std() * np.sqrt(252)
    dd = (nav / nav.cummax() - 1).min()
    sharpe = (daily.mean() * 252 - RF) / vol if vol > 0 else np.nan
    calmar = cagr / abs(dd) if dd < 0 else np.nan
    return {"CAGR": cagr, "Vol": vol, "MaxDD": dd, "Sharpe": sharpe, "Calmar": calmar}


def annual_returns(nav: pd.Series) -> pd.Series:
    """日历年收益 = 年末净值 / 上一年末净值 - 1；首年以回测起点净值为基准（部分年）"""
    year_end = nav.resample("YE").last()
    prev = year_end.shift(1)
    prev.iloc[0] = nav.iloc[0]
    return year_end / prev - 1


def stress_report(nav: pd.Series) -> dict:
    out = {}
    for name, (s, e) in config.STRESS_WINDOWS.items():
        seg = nav.loc[s:e]
        if len(seg) > 1:
            out[name] = seg.iloc[-1] / seg.iloc[0] - 1
        else:
            out[name] = np.nan
    return out


def compare_table(results: dict[str, pd.Series]) -> pd.DataFrame:
    rows = []
    for name, nav in results.items():
        st = perf_stats(nav)
        rows.append({"策略": name, **{k: round(v, 3) if v == v else np.nan for k, v in st.items()}})
    return pd.DataFrame(rows).set_index("策略")
