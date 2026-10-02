# Investment Strategy Lab

ETF 策略研究、份额账务回测、冻结方案比较与资金积累目标分析。

**状态：`diagnostic_unverified`。** 引擎历史验收仅适用于冻结方案及已测试路径；数据限制仍存在。研究结果不是未来收益或达标概率，不是自动交易程序。

## 目录

- `momentum_tool/frozen_run.py`：七组冻结实验，逐日份额账务、月度入金、费用、现金收益、滚动五年配对。
- `momentum_tool/gate_final_review.py`：必需闸门检查、隔离反例、源码变异与主入口阻断验证。
- `momentum_tool/probe_routing.py`：现金输入扰动经过真实 main 输出路径的探针。
- `momentum_tool/engine.py` 与 `explore*`、`grid_scan.py`、`wf*` 等：旧探索代码。部分段内计算采用每日恒权近似，不能继承冻结执行器的审计结论。`config.py` 中历史推荐已作废。
- `protocols/frozen_comparison_v1.json`：七组冻结研究规格（描述性协议，不是可直接加载的参数文件）。
- `research/a7/`：三基金静态配置归因、人民币参考汇率估值、首次达标及达标后回落分析。
- `scripts/`：Tiingo 下载与离线拆股、分红、总收益核验。
- `tests/`：无需行情、无需联网的合成数据测试。

仓库不包含原始行情、认证信息、个人资金配置或历史账户输出。原工作目录未移动。

## 安装与离线测试

Python 3.10+，建议独立虚拟环境：

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

合成测试用于确认打包后核心路径可运行，不替代完整的历史数据验收。

## 下载与核验数据

```sh
python scripts/download_tiingo.py --tickers QQQ TQQQ SMH IGV FDN XBI SPY BIL --start 2011-12-20 --end 2026-09-30 --out downloads/tiingo
# 下载器打印实际时间戳目录；token 通过隐藏输入读取，不写入源码。
python scripts/validate_tiingo.py downloads/tiingo/实际时间戳目录
```

下载、核验、准入主回测是三个不同状态。下载器不会自动替换主面板。跨源、交易日完整性、拆股及分配基准仍需核对；原始数据的使用与再分发遵守供应商许可。输出目录默认被 Git 忽略。

## 七组冻结运行

输入格式和前置条件见 [数据接口](docs/DATA.md)。准备文件后在项目根目录执行：

```sh
export FROZEN_PANEL="$PWD/data/panel.csv"
export FROZEN_CASH="$PWD/data/cash.csv"
export FROZEN_BIL_REFERENCE="$PWD/data/bil_market_total_return.csv"
export FROZEN_SUMMARY_DIR="$PWD/results/frozen"
mkdir -p "$FROZEN_SUMMARY_DIR"
python momentum_tool/gate_final_review.py
python momentum_tool/frozen_run.py
```

`FROZEN_QUICK=1` 只裁剪工作量；未指定输出目录时自动使用临时目录。若显式指定输出目录，仍会写入该目录，验证时必须选择独立目录。

```sh
FROZEN_SUMMARY_DIR="$PWD/results/probe" python momentum_tool/probe_routing.py
```

探针自身归档在 `momentum_tool/results/frozen/probe_archive/`，两个 main 使用临时输出目录。探针沿用历史 2014-06 扰动日期，输入必须覆盖该区间。

## 通用资金目标比较

公开的 `protocol.example.json` 是示例金额，**不是个人资产记录**。修改本金、月供、目标时复制成本地私有配置：

```sh
cp research/a7/protocol.example.json research/a7/protocol.local.json
# 编辑 execution 下 initial_RMB / monthly_RMB / primary_goal_RMB / secondary_goal_RMB
export A7_PROTOCOL="$PWD/research/a7/protocol.local.json"
export A7_NORMALIZED_DIR="$PWD/data/a7_normalized"
export A7_OUTPUT="$PWD/results/a7"
python research/a7/run_comparison.py
```

输入是 `panel_CNY_diagnostic.csv` 与 `fx_alignment.csv`；输出目标字段为 `primary_*` / `secondary_*`。五年和七年窗口、10/30bp 成本、四组静态候选保持原研究结构。QQQ 用作长期纳指敞口代理，不虚构 QNDX 上市前实绩。

`research/a7/fetch_sources.py` 获取 SPMO 公开源与汇率参考源；`normalize.py <下载目录>` 还需要 `FROZEN_PANEL`（QQQ/SMH 总收益）和 `SPMO_LEGACY_CSV`（独立对照），不能从下载成功直接跳到数据放行。抓取时间范围沿用本轮研究截止日，换区间须重新审查覆盖。

## 迁移范围

本次整理调整路径、通用资金配置及说明，保留策略规则。没有上传历史原始数据或旧审计通过报告来冒充新环境已验收。原始与打包源码 SHA256 见 `docs/source_manifest.json`。

尚未实现券商订单、个人税务、真实可成交换汇、任意标的自动研究。重叠历史窗口不能视为独立的未来概率样本。
