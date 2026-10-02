"""主流程路由探针（归档版 = 实际执行版本）
两份现金输入经过同一正常输出路径（subprocess → frozen_run.main → summary.json），
比较主输出差异。与 executor_relay 归档汇报一致：
  - QUICK 模式（3 方案 × 首尾各 3 窗口，同一真实代码路径）
  - 扰动 = 指定日期 2014-06（首窗口覆盖期内）单日 +100bp
产出：results/frozen/probe_archive/{normal_summary, perturbed_summary, probe_routing_result}.json
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd

DG = str(Path(__file__).parent / "data")
ARCHIVE = Path(__file__).parent / "results" / "frozen" / "probe_archive"
ARCHIVE.mkdir(parents=True, exist_ok=True)
PERTURB_DAY_WINDOW = ("2014-06-02", "2014-06-30")
PERTURB_BPS = 0.01                      # 单日 +100bp（可读级传导验证）


def run_main(cash, outdir):
    r = subprocess.run(
        [sys.executable, str(Path(__file__).parent / "frozen_run.py")],
        env={**os.environ,
             "FROZEN_PANEL": os.environ.get("FROZEN_PANEL", f"{DG}/panel.csv"),
             "FROZEN_CASH": str(cash),
             "FROZEN_SUMMARY_DIR": str(outdir),
             "FROZEN_QUICK": "1"},
        capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-500:])


def main():
    cash = os.environ.get("FROZEN_CASH", f"{DG}/cash.csv")

    with tempfile.TemporaryDirectory() as d1:
        run_main(cash, d1)
        (ARCHIVE / "normal_summary.json").write_text(
            Path(d1, "summary.json").read_text())
    cs = pd.read_csv(cash, index_col=0, parse_dates=True)
    day = cs.loc[PERTURB_DAY_WINDOW[0]:PERTURB_DAY_WINDOW[1]].index[0]
    cs.loc[day, cs.columns[0]] += PERTURB_BPS
    pert = Path(ARCHIVE) / "probe_cash_perturbed_100bp.csv"
    cs.to_csv(pert)
    with tempfile.TemporaryDirectory() as d2:
        run_main(pert, d2)
        (ARCHIVE / "perturbed_summary.json").write_text(
            Path(d2, "summary.json").read_text())
    pert.unlink()

    a = json.load(open(ARCHIVE / "normal_summary.json"))
    b = json.load(open(ARCHIVE / "perturbed_summary.json"))
    ma = {k: v["median"] for k, v in a["paired"].items()
          if k.count("|") == 1 and k.endswith("|glide")}
    mb = {k: v["median"] for k, v in b["paired"].items()
          if k.count("|") == 1 and k.endswith("|glide")}
    diffs = {k: [ma[k], mb[k]] for k in ma if ma[k] != mb[k]}
    ta = a.get("glide_5y", {}).get("R0", {}).get("terminal_median")
    tb = b.get("glide_5y", {}).get("R0", {}).get("terminal_median")

    result = {"probe": "指定日期单日+100bp，QUICK 双跑同一正常输出路径",
              "perturbed_day": str(day.date()),
              "paired_median_changed": diffs,
              "R0_glide_terminal_median": {"normal": ta, "perturbed": tb},
              "verdict": "通过——现金输入经正常输出路径传导"
                         if diffs or ta != tb else "失败"}
    (ARCHIVE / "probe_routing_result.json").write_text(
        json.dumps(result, indent=1, ensure_ascii=False))
    print(json.dumps(result, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
