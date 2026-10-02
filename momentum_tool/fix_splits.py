"""拆分检测与修正：扫描全部缓存标的的假跳变（|r|>25%），反推拆分比例并修正历史价格。
已知公告拆分（审计方提供）：
  SMH  2023-05-05  2:1（旧价 ×1/2）
  SOXL 2021-03-02  15:1（旧价 ×1/15）
  TQQQ 2025-xx     由扫描定位后按公告比例处理
"""

import json
from pathlib import Path

import pandas as pd

DATA = Path(__file__).parent / "data"

KNOWN_SPLITS = {
    ("SMH", "2023-05-05"): 2.0,
    ("SOXL", "2021-03-02"): 15.0,
}


def detect(ticker: str, s: pd.Series, thresh=0.25):
    r = s.pct_change()
    bad = r[abs(r) > thresh]
    return [(d.date(), float(v)) for d, v in bad.items()]


def main():
    meta = {}
    report = []
    for f in sorted(DATA.glob("*.csv")):
        if f.stem == "all_prices":
            continue
        t = f.stem
        s = pd.read_csv(f, index_col=0, parse_dates=True)[t]
        events = detect(t, s)
        if not events:
            report.append((t, "干净", []))
            meta[t] = {"splits_fixed": [], "source": "sina_unadjusted+split_fixed"}
            continue
        fixes = []
        for d, v in events:
            ds = str(d)
            ratio = None
            if (t, ds) in KNOWN_SPLITS:
                ratio = KNOWN_SPLITS[(t, ds)]
            elif (1 + v) < 0.05:
                fixes.append((ds, v, "坏点(≈-100%)，需人工核对，暂不修"))
                continue
            elif v < -0.25:                          # 前向拆分：假跌，-50% → 2:1
                cand = round(1 / (1 + v))
                if 1.5 <= cand <= 40 and abs(1 / cand - (1 + v)) <= 0.05:
                    ratio = cand
            elif v > 1.0:                            # 反向拆分：假涨，+900% → 1:10
                cand = round(1 + v)
                if cand >= 2 and abs(cand - (1 + v)) <= 0.05:
                    ratio = 1 / cand
            if ratio is None:
                fixes.append((ds, v, "非整数比例，判为真实事件保留"))
                continue
            # 真实事件保留（如 2020 熔断、2025-04-09），只修整数比例的跳变
            implied = abs((1 / ratio) - (1 + v))
            if implied > 0.05:                       # 与整数比例不符 → 判为真实波动，不修
                fixes.append((ds, v, "真实事件保留"))
                continue
            day = pd.Timestamp(ds)
            s.loc[s.index < day] = s.loc[s.index < day] / ratio
            fixes.append((ds, v, f"修正 ×1/{ratio}"))
            meta.setdefault(t, {"splits_fixed": [], "source": "sina_unadjusted+split_fixed"})
            meta[t]["splits_fixed"].append({"date": ds, "ratio": f"1:{ratio}", "fake_ret": round(v, 4)})
        s.to_csv(f)
        report.append((t, "已处理", fixes))

    for t, status, fixes in report:
        print(f"{t}: {status}")
        for ds, v, action in fixes:
            print(f"    {ds}  {v:+.1%}  → {action}")

    (DATA / "_meta.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False))
    print("\n修正后复检（应全为真实事件）：")
    for f in sorted(DATA.glob("*.csv")):
        if f.stem == "all_prices":
            continue
        t = f.stem
        s = pd.read_csv(f, index_col=0, parse_dates=True)[t]
        events = detect(t, s)
        for d, v in events:
            print(f"    {t} {d} {v:+.1%} 保留")


if __name__ == "__main__":
    main()
