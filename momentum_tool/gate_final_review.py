"""闸门终审（脚本生成版）：validate_gates 接入 + 变异测试独立输出目录
本脚本是终审报告的唯一生成入口（此前 v3 为手工 patch，不可复现——已纠正）。
"""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd

import frozen_run as fr

RESULTS = fr.RESULTS
SRC = Path(__file__).parent / "frozen_run.py"
DG = str(Path(__file__).parent / "data")
PANEL = os.environ.get("FROZEN_PANEL", f"{DG}/panel.csv")
CASH = os.environ.get("FROZEN_CASH", f"{DG}/cash.csv")


def load_mutated(name, mutations):
    src = SRC.read_text()
    for old, new in mutations:
        assert old in src, f"anchor missing: {old[:50]}"
        src = src.replace(old, new, 1)
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir=str(SRC.parent)) as f:
        f.write(src)
        path = f.name
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    Path(path).unlink()
    return mod


def inject_real_contribution():
    bad = load_mutated("bad_contribution", [
        ("nav_pre = value / units              # 当日收盘、入金前净值",
         "nav_pre = (prev_v / units) if (units > 0 and isinstance(locals().get('prev_v'), (int, float)) and prev_v) else (value / units)")])
    idx6 = pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-06"])
    d6 = pd.DataFrame({"QQQ": [1.0, 1.0, 0.5]}, index=idx6)
    sm6 = {idx6[0]: {"trend": False, "dd": 0.0, "picked": []},
           idx6[2]: {"trend": False, "dd": 0.0, "picked": []}}
    df_bad, _, _ = bad.simulate(d6, list(sm6.keys()), sm6, "B0", idx6[0], idx6[-1],
                                0.0, 0.0, initial=100, monthly=10)
    navs = df_bad["nav"]
    dd_bad = float((navs / navs.cummax().clip(lower=1.0) - 1).min())
    return abs(dd_bad + 0.50) > 1e-9, {"bad_engine_dd": dd_bad}


def inject_real_releveraging():
    bad = load_mutated("bad_glide", [
        ('if month >= 37 and scheme in ("L0", "L1"):',
         'if month >= 3700 and scheme in ("L0", "L1"):')])
    w49 = bad.target("L0", {"trend": True, "dd": 0.0, "picked": []}, 49, glide=True)
    w49_ok = fr.target("L0", {"trend": True, "dd": 0.0, "picked": []}, 49, glide=True)
    return (w49.get("TQQQ", 0) > 0) and (w49_ok.get("TQQQ", 0) == 0), {
        "bad_m49_tqqq": w49.get("TQQQ", 0), "good_m49_tqqq": 0}


def inject_real_split():
    panel = pd.read_csv(PANEL, index_col=0, parse_dates=True)
    panel = panel[[c for c in ["QQQ", "TQQQ", "SMH", "IGV", "FDN", "XBI", "SPY"]
                   if c in panel.columns]]
    poisoned = panel.copy()
    mid = poisoned.index[len(poisoned) // 2]
    poisoned.loc[mid, "QQQ"] = poisoned["QQQ"].iloc[len(poisoned) // 2 - 1] * 0.5
    ed = fr.month_firsts(poisoned.index)
    sm = fr.signals(poisoned, ed)
    g = fr.gate_checks(panel=poisoned, exec_days=ed, sig_map=sm)
    try:
        fr.validate_gates(g, cash_required=True)
        return False, {"note": "坏面板竟通过严格校验"}
    except RuntimeError as e:
        return "split_day_continuity" in str(e), {"error": str(e)[:200]}


def mutated_entry_block():
    """变异版跑完整 main（独立输出目录，不覆盖正式结果），验证模拟前阻断"""
    src = SRC.read_text()
    mut = src.replace(
        "nav_pre = value / units              # 当日收盘、入金前净值",
        "nav_pre = (prev_v / units) if (units > 0 and isinstance(locals().get('prev_v'), (int, float)) and prev_v) else (value / units)", 1)
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir=str(SRC.parent)) as f:
        f.write(mut)
        mutpath = f.name
    with tempfile.TemporaryDirectory() as outdir:      # 独立输出目录
        r = subprocess.run([sys.executable, mutpath],
                           env={**os.environ,
                                "FROZEN_PANEL": PANEL, "FROZEN_CASH": CASH,
                                "FROZEN_QUICK": "1",
                                "FROZEN_SUMMARY_DIR": outdir},
                           capture_output=True, text=True, timeout=900)
    Path(mutpath).unlink()
    ok = (r.returncode != 0 and "闸门校验失败" in r.stderr
          and "contribution_price_correct" in r.stderr)
    return ok, {"exit": r.returncode,
                "stderr_tail": r.stderr.strip().splitlines()[-1][:200],
                "output_isolated": True}


def main():
    # 1) 主入口闸门 + 严格校验（本脚本通过的前提）
    panel = pd.read_csv(PANEL, index_col=0, parse_dates=True)
    panel = panel[[c for c in ["QQQ", "TQQQ", "SMH", "IGV", "FDN", "XBI", "SPY"]
                   if c in panel.columns]]
    ed = fr.month_firsts(panel.index)
    sm = fr.signals(panel, ed)
    gates = fr.gate_checks(panel, ed, sm)
    fr.validate_gates(gates, cash_required=True)        # 不通过即抛错退出
    gate_pass = {k: v for k, v in gates.items() if not k.endswith(("_detail",))}

    # 严格校验隔离场景
    iso = {}
    try:
        fr.validate_gates({}, cash_required=True)
        iso["empty_dict"] = False
    except RuntimeError:
        iso["empty_dict"] = True
    for name, patch in [
            ("false_value", {"zero_flat_conservation": False}),
            ("none_value", {"buy_hold_identity": None}),
            ("missing_gate", None)]:
        gg = {g: True for g in fr.REQUIRED_GATES}
        if patch:
            gg.update(patch)
        else:
            gg.pop("recovery_and_dd_basis")
        try:
            fr.validate_gates(gg, cash_required=True)
            iso[name] = False
        except RuntimeError:
            iso[name] = True
    gg = {**{g: True for g in fr.REQUIRED_GATES},
          "cash_series_daily_factor": "skipped_no_bil"}
    try:
        fr.validate_gates(gg, cash_required=True)
        iso["skipped_cash_when_required"] = False
    except RuntimeError:
        iso["skipped_cash_when_required"] = True
    # 删除反例：现金闸门缺失必须阻断
    gg2 = {g: True for g in fr.REQUIRED_GATES}
    try:
        fr.validate_gates(gg2, cash_required=True)          # 四项现金全缺
        iso["cash_gates_all_deleted"] = False
    except RuntimeError:
        iso["cash_gates_all_deleted"] = True
    gg3 = {**{g: True for g in fr.REQUIRED_GATES},
           **{g: True for g in fr.CASH_GATES if g != "cash_gap_blocks"}}
    try:
        fr.validate_gates(gg3, cash_required=True)          # 仅缺 cash_gap_blocks
        iso["cash_gap_blocks_deleted"] = False
    except RuntimeError:
        iso["cash_gap_blocks_deleted"] = True
    iso["cash_true_when_not_required"] = fr.validate_gates(
        {**{g: True for g in fr.REQUIRED_GATES}, **{g: True for g in fr.CASH_GATES}},
        cash_required=False) is True

    injections = {"bad_contribution_pricing": inject_real_contribution(),
                  "releveraging": inject_real_releveraging(),
                  "split_jump": inject_real_split(),
                  "mutated_entry_blocks_before_simulation": mutated_entry_block()}

    all_ok = (all(iso.values())
              and all(v[0] for v in injections.values())
              and all(v is True for k, v in gate_pass.items()
                      if k in fr.REQUIRED_GATES or k in fr.CASH_GATES))

    review = {
        "status": "gate_final_review_v3_generated_by_script",
        "generated_by": "gate_final_review.py（唯一生成入口；此前手工 patch 已废除）",
        "main_entry_gates": gate_pass,
        "strict_validation_isolated": iso,
        "real_fault_injections": {k: {"detected": bool(v[0]), "detail": v[1]}
                                  for k, v in injections.items()},
        "verdict": "通过（21 项闸门 + 严格校验隔离场景 + 4 项真实注入 + 变异主入口模拟前阻断）"
                   if all_ok else "不通过",
        "data_gate_status_unchanged": "diagnostic_unverified；主比较升格由验收方裁决",
    }
    (RESULTS / "gate_final_review.json").write_text(
        json.dumps(review, indent=1, ensure_ascii=False, default=str))
    print("主入口闸门:", len([v for v in gate_pass.values() if v is True]), "项 True")
    print("严格校验隔离:", iso)
    print("真实注入:", {k: v[0] for k, v in injections.items()})
    print("裁决:", review["verdict"])
    if not all_ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
