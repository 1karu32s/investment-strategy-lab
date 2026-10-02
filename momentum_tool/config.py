# ============================================================
# 【状态声明】本文件中 RECOMMENDED / LEVERED / FINAL_ROTATION /
# PYRAMID_TIERS 均为历史开发记录（v13 审计已撤回其结论表述）。
# 当前有效实验规格：protocols/
# frozen_comparison_v1.json（B0/R0/R1/L0/L1/M0/M1 七组冻结方案）。
# frozen_run.py 是唯一调用入口，不依赖本文件任何别名。
# ============================================================

"""标的池与参数矩阵配置"""

# 全部候选标的（含基准）
ALL_TICKERS = [
    "SPMO",  # S&P 500 动量
    "MTUM",  # MSCI 美国动量
    "XMMO",  # S&P 中盘 400 动量
    "XSMO",  # S&P 小盘 600 动量
    "AVUV",  # Avantis 小盘价值
    "AVLV",  # Avantis 大盘价值
    "RPV",   # 深度价值
    "COWZ",  # 自由现金流 100
    "RSP",   # S&P 500 等权
    "SMH",   # 半导体（进攻翼，V6）
    "QQQ",   # 纳指 100（基准/轮动成员）
    "SPY",   # 标普 500（基准）
    "TQQQ",  # 3x 纳指（杠杆路线）
    "SOXL",  # 3x 半导体（杠杆路线）
    "UPRO",  # 3x 标普（杠杆路线）
    "XBI",   # 生物科技（低相关候选）
    "XLE",   # 能源（低相关候选）
    "URA",   # 铀/核能（低相关候选）
    "QUAL",  # 质量因子（纯因子池）
    "USMV",  # 低波动因子（纯因子池）
    # SPDR 十大行业 ETF（备用）
    "XLK", "XLY", "XLP", "XLV", "XLE", "XLI", "XLU", "XLRE", "XLC",
    # 科技子板块 ETF（科技轮动池）
    "IGV",   # 软件
    "FDN",   # 互联网
    "CIBR",  # 网络安全
    "SKYY",  # 云计算
    "BOTZ",  # 机器人/AI
]

# 用户定义的最终策略结构：科技池动量轮动（轨道B） + QQQ 金字塔定投压舱石（轨道A）
TECH_POOL = ["QQQ", "SMH", "IGV", "FDN", "XBI", "CIBR", "SKYY", "BOTZ"]

# [历史作废 v13——v11 收益数字已因 XIRR 口径错误撤回] 最终策略：双轨 + 金字塔定投
# [历史作废] 压舱石：QQQ 定投金字塔（同预算口径下拖累收益 5.6-7.9pp，v13 撤回）
# [历史作废] 轮动仓：科技池 top2（M1 假设检验中，见 frozen_comparison_v1）
FINAL_ROTATION = dict(
    universe=TECH_POOL, freq="M", top_n=2, signal="short136", cash_rule=True,
    weighting="mom", buffer=0, vol_guard=0.30, trend_ref="QQQ",
)
PYRAMID_TIERS = [(0.10, 1.5), (0.20, 2.0), (0.30, 3.0)]   # (回撤阈值, 投入倍数)
TRACK_SPLIT = 0.7                                          # 压舱石占比

# 池子变体：V4 含 AVLV（成立 2021，仅用于短时段附加实验）
UNIVERSES = {
    "V1_全家桶": ["SPMO", "MTUM", "XSMO", "AVUV", "RPV", "COWZ", "RSP"],   # 主线，共同起点约 2017-2019
    "V2_纯动量": ["SPMO", "MTUM", "XMMO", "XSMO"],
    "V3_价值翼": ["AVUV", "RPV", "COWZ", "RSP"],
    "V4_含AVLV": ["SPMO", "MTUM", "XSMO", "AVUV", "RPV", "COWZ", "RSP", "AVLV"],  # 2021-09 后数据完整
    "V5_含QQQ": ["SPMO", "MTUM", "XSMO", "AVUV", "RPV", "COWZ", "RSP", "QQQ"],
    "V6_QQQ加SMH": ["SPMO", "MTUM", "XSMO", "AVUV", "RPV", "COWZ", "RSP", "QQQ", "SMH"],
}

# 调仓频率
FREQS = ["W", "2W", "M", "Q"]

# 动量信号类型
#   classic121 : 12 个月收益剔除最近 1 个月（SPMO 指数同款思路）
#   comp3612   : (3M+6M+12M)/3 收益 ÷ 6M 波动率（风险调整复合）
#   short136   : (1M+3M+6M)/3 收益 ÷ 3M 波动率（灵敏版）
SIGNALS = ["classic121", "comp3612", "short136"]

TOP_NS = [2, 3, 4]

# 成员上市满多少个交易日才参与排名（避免新股噪音 + 保证信号窗口有数据）
MIN_HISTORY_DAYS = 273  # 约 13 个月

# 交易成本（单边，bp：佣金+价差+冲击）
COST_BPS = 10

# 空仓期间现金收益（年化，货基近似）
CASH_RATE = 0.02

# 训练/验证切分
TRAIN_END = "2022-12-31"   # 训练段 2018-01 ~ 2022-12（含 2018Q4 / 2020 / 2022 三次压力）
VALID_START = "2023-01-01" # 验证段 2023-01 ~ 至今（牛市为主）

# 压力场景定义
STRESS_WINDOWS = {
    "2018Q4暴跌": ("2018-09-20", "2018-12-24"),
    "2020疫情V型": ("2020-02-19", "2020-03-23"),
    "2022熊市": ("2022-01-03", "2022-10-12"),
    "2023-25牛市": ("2023-01-03", "2026-09-29"),
}

# 推荐策略 V9（低 QQQ 含量路线，回应用户"不要高 Q 含量"约束）：
# 三分 SPMO/QQQ/SMH 等权 + 波动率守卫 0.30（QQQ 含量 33%）
# 2020-01 起（SMH 数据起点）: CAGR 21.87% / MaxDD -30% / 2022 +3.4% vs QQQ 20.04%/-36%
# 注意：2017 起口径仅 20.13%（SMH 2021 才参战）——优势依赖 2020 后半导体周期（时代偏差）
# 零 QQQ 替代：["SPMO","SMH"] 同参数 = 20.48%/-31%/2022 -8.8%（2020 起）
# 旧 V8.1（QQQ 锚 90%）: 21.22%/-28.5%（2017 起），保留于 git 历史
RECOMMENDED = dict(
    universe=["SPMO", "QQQ", "SMH"],
    freq="M", top_n=3, signal="short136", cash_rule=False,
    weighting="eq", buffer=0, vol_guard=0.30,
)

# [历史作废 v13] 3x 杠杆档（冻结清单 frozen_comparison_v1 不调用本配置）
# SPMO45/Q30/SOXL25 + 守卫 0.30（参考 SMH 波动，更早感知半导体危机）
# 2015-10 起: CAGR 38.92% / MaxDD -50% / Calmar 0.78 / 2022 -9% vs QQQ 19.3%
# 警示：TQQQ/UPRO 路线已证伪（2012 起 14 年 CAGR 仅 2.4%，守卫救不了纯 3x）；
# SOXL 仓位 20-50% 回撤均为 -49~-51%（闪崩+路径复利，月度守卫拦不住跨月腰斩）
LEVERED = dict(
    universe=["SPMO", "QQQ", "SOXL"], freq="M", top_n=3, signal="short136",
    cash_rule=False, anchor="SPMO", anchor_w=0.45, weighting="eq",
    buffer=0, vol_guard=0.30, trend_ref="SMH",
)
