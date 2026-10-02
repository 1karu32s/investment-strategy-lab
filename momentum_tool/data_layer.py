"""数据层：多源拉取日线收盘价 + 本地 csv 缓存
主源：新浪美股接口（国内稳定，未复权价，绝对收益及相对比较均可能失真，仅供历史诊断）
备用：yfinance（复权价，需 Yahoo 不限流时手动 refresh）
"""

import json
import re
import time
from pathlib import Path

import pandas as pd
import requests

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
META_PATH = DATA_DIR / "_meta.json"

HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"}


def _save_meta(ticker: str, source: str, rows: int):
    import json
    meta = {}
    if META_PATH.exists():
        meta = json.loads(META_PATH.read_text())
    meta[ticker] = {"source": source, "rows": rows,
                    "fetched_at": pd.Timestamp.now().isoformat()}
    META_PATH.write_text(json.dumps(meta, indent=1))


def _cache_path(ticker: str) -> Path:
    return DATA_DIR / f"{ticker}.csv"


def fetch_sina(ticker: str, start: str = "2012-01-01") -> pd.Series:
    """新浪美股日线收盘价（未复权）"""
    url = ("https://stock.finance.sina.com.cn/usstock/api/jsonp_v2.php/x=/"
           f"US_MinKService.getDailyK?symbol={ticker}&len=10000")
    txt = requests.get(url, timeout=20, headers=HEADERS).text
    m = re.search(r"\((\[.*\])\)", txt, re.S)
    if not m:
        raise RuntimeError(f"sina parse fail: {ticker}")
    data = json.loads(m.group(1))
    s = pd.Series({d["d"]: float(d["c"]) for d in data}, name=ticker)
    s.index = pd.to_datetime(s.index)
    return s[s.index >= pd.Timestamp(start)].sort_index()


def fetch_yf(ticker: str, start: str = "2012-01-01") -> pd.Series:
    """yfinance 复权价（备用源）"""
    import yfinance as yf
    df = yf.download(ticker, start=start, auto_adjust=True, progress=False)
    if df.empty:
        raise RuntimeError(f"yf empty: {ticker}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    s = df["Close"].dropna()
    s.name = ticker
    return s


def fetch_one(ticker: str, start: str = "2012-01-01", source: str = "sina") -> pd.Series:
    cp = _cache_path(ticker)
    if cp.exists():
        return pd.read_csv(cp, index_col=0, parse_dates=True)[ticker]
    for fn in ([fetch_sina, fetch_yf] if source == "sina" else [fetch_yf, fetch_sina]):
        try:
            s = fn(ticker, start)
            if len(s) > 0:
                s.to_csv(cp)
                _save_meta(ticker, "sina_unadjusted" if fn is fetch_sina else "yf_adjusted", len(s))
                time.sleep(0.5)
                return s
        except Exception:
            continue
    raise RuntimeError(f"all sources failed: {ticker}")


def load_prices(tickers: list[str]) -> pd.DataFrame:
    """宽表：index=日期, columns=ticker；上市前的 NaN 保留为不可交易标记"""
    return pd.concat([fetch_one(t) for t in tickers], axis=1).sort_index()


def refresh_all(tickers: list[str], source: str = "yf"):
    """手动刷新（如 Yahoo 解封后换复权价重跑）"""
    for t in tickers:
        cp = _cache_path(t)
        cp.unlink(missing_ok=True)
        fetch_one(t, source=source)
