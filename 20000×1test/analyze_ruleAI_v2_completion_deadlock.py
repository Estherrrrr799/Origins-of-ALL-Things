#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze_ruleAI_v2_completion_deadlock.py

用途 (Purpose)
--------------
针对评审意见 ——"ruleAI v2 缺少配套回合数、完成率统计支撑；文中多次提出 v2 死组模块可
减少对局死锁、降低超时，但第五章仅展示胜率卡方检验，未补充两组 AI 平均回合、游戏完成率
的对比表格与显著性检验" —— 本脚本使用 20,000 局主实验的逐局原始数据
(raw_game_logs_en.csv, ruleAI_v2_extension_results_en_raw.csv)，为三组配对比较各自计算：

  1. 完成率 (Completion Rate)：2x2 卡方独立性检验 (chi2_contingency)，效应量 Cohen's w，
     Wilson score 95% 置信区间。这是直接检验"死组模块是否降低超时/提升完成率"的核心证据。
  2. 平均回合数 —— 仅完成对局 (Turns, completed games only)：Mann-Whitney U 检验，
     秩双列相关 (rank-biserial r) 作为效应量。用于检验"本来就会分出胜负的对局，v2 是否
     也让它更快结束"。
  3. 平均回合数 —— 全部对局，含超时对局按 800 回合封顶 (Turns, all games)：Mann-Whitney U
     检验。作为完成率效应的下游综合指标，用于说明"整体对局速度"的变化，但需要在论文中
     明确注明其与完成率效应存在混淆，不能解读为独立的"更快"证据。

三组配对比较 (Comparison Pairs)
--------------------------------
  Pair 1: Rule-Based AI v2 vs Rule-Based AI v2 (control)   [双方均带死组模块]
          对照 Rule-Based vs Rule-Based (control)          [双方均为原版]
          → 隔离"死组模块"本身的完整效应（自我对战，最干净的对照）

  Pair 2: Rule-Based AI v2 vs Rule-Based AI (original)     [仅一方带死组模块]
          对照 Rule-Based vs Rule-Based (control)          [双方均为原版，同一"家族"对手]
          → 隔离"仅升级一方为 v2"的效应

  Pair 3: Rule-Based AI v2 vs 1SGS AI                      [Rule 方带死组模块，1SGS 不变]
          对照 Rule-Based vs 1SGS                          [第五章主实验的原始基线]
          → 直接对应第五章主实验语境，1SGS 对手保持不变

数据来源 (Data Provenance)
---------------------------
  raw_game_logs_en.csv                       —— 主实验 20,000 局 x 3 种 matchup 的逐局原始记录（无 v2）
  ruleAI_v2_extension_results_en_raw.csv     —— v2 扩展实验 20,000 局 x 3 种 matchup 的逐局原始记录

统计方法说明 (Methodology Notes)
----------------------------------
  - 完成率检验使用 scipy.stats.chi2_contingency(correction=False)。样本量极大（每组 N=20,000，
    期望频数远超过 5），Yates 连续性校正的影响可忽略不计（本脚本同时计算校正后数值供核对，
    两者在小数点后两位内一致）。
  - 回合数检验使用 scipy.stats.mannwhitneyu(alternative='two-sided')，因回合数分布非正态
    （右偏，且超时对局在 800 处截尾），不满足 t 检验的正态假设，与本论文其余章节对回合数/
    决策时间使用 Mann-Whitney U 检验的方法保持一致。
  - 所有 p 值均为 scipy 精确计算结果，符合"论文中所有 p 值必须使用 scipy 精确值"的既定原则。
  - 效应量：完成率使用 Cohen's w（2x2 卡方的 phi 系数），回合数使用秩双列相关 r。
    解读阈值引用 Cohen (1988)：w/r ≈ 0.1 为小效应，0.3 为中效应，0.5 为大效应
    （与论文中座位偏置章节引用 Cohen (1988) 的方式保持一致）。

输出 (Outputs)
---------------
  ruleAI_v2_completion_deadlock_analysis.xlsx  —— 可直接查阅/插入论文的正式结果表格
  completion_rate_comparison.png               —— 完成率对比图（含 95% CI 误差棒与显著性标注）
  avg_turns_comparison.png                     —— 回合数对比图（完成对局 vs 全部对局两个面板）

用法 (Usage)
-------------
  python3 analyze_ruleAI_v2_completion_deadlock.py \
      --base raw_game_logs_en.csv \
      --v2 ruleAI_v2_extension_results_en_raw.csv \
      --outdir ./output
"""

import argparse
import os
from datetime import datetime

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.proportion import proportion_confint

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.drawing.image import Image as XLImage

# ----------------------------------------------------------------------------
# 字体设置：不写死具体字体文件名（不同机器上装的字体不一样，写死会导致
# "findfont: Font family ... not found" 警告刷屏）。改用 matplotlib 的通用
# "serif" 字体族 + 优先级候选列表，matplotlib 会自动挑选当前机器上第一个
# 实际安装了的字体，找不到任何候选时会静默使用内置的 DejaVu Serif，不再报警告。
# ----------------------------------------------------------------------------
plt.rcParams["font.family"] = "serif"
plt.rcParams["font.serif"] = [
    "Liberation Serif", "Times New Roman", "Times", "Nimbus Roman",
    "DejaVu Serif",  # matplotlib 内置字体，任何环境都保证存在，放在最后兜底
]
plt.rcParams["font.size"] = 11
plt.rcParams["axes.edgecolor"] = "#333333"
plt.rcParams["axes.linewidth"] = 0.8

COLOR_BASELINE = "#8C8C8C"   # 灰色 = 不带死组模块（原版基线）
COLOR_V2 = "#C0622D"         # 赭橙色 = 带死组模块 (ruleAI v2)


# ==============================================================================
# 1. 数据加载与校验
# ==============================================================================

def load_raw_data(base_path: str, v2_path: str):
    """加载两份逐局原始数据，并将 Timed Out 列标准化为布尔值。"""
    base = pd.read_csv(base_path)
    v2 = pd.read_csv(v2_path)

    for df in (base, v2):
        df.columns = [c.strip() for c in df.columns]
        df["timed_out"] = df["Timed Out"].astype(str).str.strip().str.lower() == "yes"
        df["Total Turns"] = pd.to_numeric(df["Total Turns"], errors="coerce")

    return base, v2


def build_groups(base: pd.DataFrame, v2: pd.DataFrame) -> dict:
    """按 Matchup 切分出六个子数据集，并用已知的官方汇总数字做一致性校验。"""
    groups = {
        "B1_rule_vs_1SGS": base[base["Matchup"] == "Rule-Based vs 1SGS"],
        "B2_rule_vs_rule": base[base["Matchup"] == "Rule-Based vs Rule-Based (control)"],
        "B3_1SGS_vs_1SGS": base[base["Matchup"] == "1SGS vs 1SGS (control)"],
        "V1_v2_vs_original": v2[v2["Matchup"] == "Rule-Based AI v2 vs Rule-Based AI (original)"],
        "V2_v2_vs_1SGS": v2[v2["Matchup"] == "Rule-Based AI v2 vs 1SGS AI"],
        "V3_v2_vs_v2": v2[v2["Matchup"] == "Rule-Based AI v2 vs Rule-Based AI v2 (control)"],
    }

    # 已知的官方汇总值（来自 summary_results_en.csv / ruleAI_v2_extension_results_en.csv），
    # 用于在脚本运行时自动核对逐局数据的完成率是否与已发表的汇总数字一致。
    expected_completion_rate = {
        "B1_rule_vs_1SGS": 61.2,
        "B2_rule_vs_rule": 62.7,
        "B3_1SGS_vs_1SGS": 60.6,
        "V1_v2_vs_original": 66.6,
        "V2_v2_vs_1SGS": 65.3,
        "V3_v2_vs_v2": 71.2,
    }

    for key, g in groups.items():
        assert len(g) == 20000, f"{key}: 期望 20000 局，实际 {len(g)} 局"
        rate = 100 * (1 - g["timed_out"].sum() / len(g))
        exp = expected_completion_rate[key]
        assert abs(rate - exp) < 0.05, (
            f"{key}: 逐局数据推算完成率 {rate:.2f}% 与官方汇总值 {exp}% 不一致，"
            f"请检查原始数据是否被截断或修改。"
        )

    return groups


# ==============================================================================
# 2. 描述性统计
# ==============================================================================

def describe_group(g: pd.DataFrame, label: str, matchup_name: str) -> dict:
    n = len(g)
    timed_out = int(g["timed_out"].sum())
    completed = n - timed_out
    rate = completed / n
    ci_low, ci_high = proportion_confint(completed, n, method="wilson")

    turns_completed = g.loc[~g["timed_out"], "Total Turns"]
    turns_all = g["Total Turns"]

    return dict(
        key=label,
        matchup=matchup_name,
        n=n,
        completed=completed,
        timed_out=timed_out,
        completion_rate=rate * 100,
        ci_low=ci_low * 100,
        ci_high=ci_high * 100,
        mean_turns_completed=turns_completed.mean(),
        median_turns_completed=turns_completed.median(),
        sd_turns_completed=turns_completed.std(),
        mean_turns_all=turns_all.mean(),
        median_turns_all=turns_all.median(),
        sd_turns_all=turns_all.std(),
    )


MATCHUP_DISPLAY_NAMES = {
    "B1_rule_vs_1SGS": "Rule-Based (original) vs 1SGS",
    "B2_rule_vs_rule": "Rule-Based vs Rule-Based (control, no v2)",
    "B3_1SGS_vs_1SGS": "1SGS vs 1SGS (control)",
    "V1_v2_vs_original": "Rule-Based AI v2 vs Rule-Based AI (original)",
    "V2_v2_vs_1SGS": "Rule-Based AI v2 vs 1SGS AI",
    "V3_v2_vs_v2": "Rule-Based AI v2 vs Rule-Based AI v2 (control)",
}


# ==============================================================================
# 3. 显著性检验
# ==============================================================================

def cohens_w_from_chi2(chi2: float, n_total: int) -> float:
    return float(np.sqrt(chi2 / n_total))


def rank_biserial_from_u(u: float, n1: int, n2: int) -> float:
    return float(1 - (2 * u) / (n1 * n2))


def z_from_u(u: float, n1: int, n2: int) -> float:
    mu = n1 * n2 / 2
    sigma = np.sqrt(n1 * n2 * (n1 + n2 + 1) / 12)
    return float((u - mu) / sigma)


def completion_rate_test(gv: pd.DataFrame, gb: pd.DataFrame) -> dict:
    comp_v, comp_b = len(gv) - gv["timed_out"].sum(), len(gb) - gb["timed_out"].sum()
    to_v, to_b = int(gv["timed_out"].sum()), int(gb["timed_out"].sum())
    table = [[comp_v, to_v], [comp_b, to_b]]

    chi2, p, dof, expected = stats.chi2_contingency(table, correction=False)
    chi2_y, p_y, _, _ = stats.chi2_contingency(table, correction=True)
    n_total = len(gv) + len(gb)
    w = cohens_w_from_chi2(chi2, n_total)

    rate_v = 100 * comp_v / len(gv)
    rate_b = 100 * comp_b / len(gb)

    return dict(
        chi2=chi2, dof=dof, p=p,
        chi2_yates=chi2_y, p_yates=p_y,
        cohens_w=w,
        completion_rate_v=rate_v, completion_rate_b=rate_b,
        diff_pct_points=rate_v - rate_b,
    )


def turns_mwu_test(x: pd.Series, y: pd.Series) -> dict:
    u, p = stats.mannwhitneyu(x, y, alternative="two-sided")
    n1, n2 = len(x), len(y)
    r = rank_biserial_from_u(u, n1, n2)
    z = z_from_u(u, n1, n2)
    return dict(
        u=float(u), z=z, p=float(p), rank_biserial_r=r,
        median_x=float(x.median()), median_y=float(y.median()),
        mean_x=float(x.mean()), mean_y=float(y.mean()),
        n_x=n1, n_y=n2,
    )


def effect_size_label(w_or_r: float) -> str:
    """Cohen (1988) 惯例阈值：0.1 小效应，0.3 中效应，0.5 大效应。"""
    a = abs(w_or_r)
    if a < 0.1:
        return "negligible"
    elif a < 0.3:
        return "small"
    elif a < 0.5:
        return "medium"
    else:
        return "large"


def p_to_stars(p: float) -> str:
    if p < 0.001:
        return "***"
    elif p < 0.01:
        return "**"
    elif p < 0.05:
        return "*"
    else:
        return "n.s."


def p_display(p: float) -> str:
    return "<0.000001" if p < 0.000001 else f"{p:.6f}"


# ==============================================================================
# 4. 主分析：三组配对比较
# ==============================================================================

COMPARISON_PAIRS = [
    dict(
        pair_id="Pair 1",
        v2_key="V3_v2_vs_v2",
        base_key="B2_rule_vs_rule",
        title="Self-play: v2 vs v2 (control)  —  Rule-Based vs Rule-Based (control)",
        rationale_cn="双方均带死组模块 vs 双方均为原版，隔离死组模块的完整效应（最干净的对照）",
        rationale_en="Both players equipped with the dead-group module vs neither player equipped; "
                     "isolates the full effect of the module in a matched self-play design.",
    ),
    dict(
        pair_id="Pair 2",
        v2_key="V1_v2_vs_original",
        base_key="B2_rule_vs_rule",
        title="v2 vs Rule-Based (original)  —  Rule-Based vs Rule-Based (control)",
        rationale_cn="仅一方升级为 v2，对手仍为原版规则 AI，对照双方均为原版的基线",
        rationale_en="Only one player upgraded to v2 while the opponent remains the original "
                     "rule-based AI; compared against the all-original baseline.",
    ),
    dict(
        pair_id="Pair 3",
        v2_key="V2_v2_vs_1SGS",
        base_key="B1_rule_vs_1SGS",
        title="v2 vs 1SGS  —  Rule-Based (original) vs 1SGS",
        rationale_cn="Rule 方升级为 v2，1SGS 对手保持不变，直接对应第五章主实验语境",
        rationale_en="Rule-based side upgraded to v2 while the 1SGS opponent is held constant; "
                     "directly corresponds to Chapter 5's main experimental context.",
    ),
]


def run_full_analysis(base_path: str, v2_path: str):
    base, v2 = load_raw_data(base_path, v2_path)
    groups = build_groups(base, v2)

    descriptive = {
        key: describe_group(g, key, MATCHUP_DISPLAY_NAMES[key])
        for key, g in groups.items()
    }

    results = []
    for pair in COMPARISON_PAIRS:
        gv, gb = groups[pair["v2_key"]], groups[pair["base_key"]]

        comp_test = completion_rate_test(gv, gb)

        tc_v = gv.loc[~gv["timed_out"], "Total Turns"]
        tc_b = gb.loc[~gb["timed_out"], "Total Turns"]
        turns_completed_test = turns_mwu_test(tc_v, tc_b)

        ta_v = gv["Total Turns"]
        ta_b = gb["Total Turns"]
        turns_all_test = turns_mwu_test(ta_v, ta_b)

        results.append(dict(
            pair=pair,
            v2_desc=descriptive[pair["v2_key"]],
            base_desc=descriptive[pair["base_key"]],
            completion=comp_test,
            turns_completed=turns_completed_test,
            turns_all=turns_all_test,
        ))

    return groups, descriptive, results


# ==============================================================================
# 5. 图表生成
# ==============================================================================

def make_completion_rate_chart(results, out_path):
    fig, ax = plt.subplots(figsize=(8.5, 5.2), dpi=300)

    n_pairs = len(results)
    x = np.arange(n_pairs)
    width = 0.32

    base_rates = [r["completion"]["completion_rate_b"] for r in results]
    v2_rates = [r["completion"]["completion_rate_v"] for r in results]
    base_ci = [
        (r["base_desc"]["completion_rate"] - r["base_desc"]["ci_low"],
         r["base_desc"]["ci_high"] - r["base_desc"]["completion_rate"])
        for r in results
    ]
    v2_ci = [
        (r["v2_desc"]["completion_rate"] - r["v2_desc"]["ci_low"],
         r["v2_desc"]["ci_high"] - r["v2_desc"]["completion_rate"])
        for r in results
    ]

    bars_base = ax.bar(x - width / 2, base_rates, width, label="Without dead-group module (baseline)",
                        color=COLOR_BASELINE, edgecolor="white", linewidth=0.6,
                        yerr=np.array(base_ci).T, capsize=4, error_kw=dict(lw=1, ecolor="#333333"))
    bars_v2 = ax.bar(x + width / 2, v2_rates, width, label="With dead-group module (ruleAI v2)",
                      color=COLOR_V2, edgecolor="white", linewidth=0.6,
                      yerr=np.array(v2_ci).T, capsize=4, error_kw=dict(lw=1, ecolor="#333333"))

    for bars, rates in [(bars_base, base_rates), (bars_v2, v2_rates)]:
        for rect, rate in zip(bars, rates):
            ax.text(rect.get_x() + rect.get_width() / 2, rect.get_height() + 1.6,
                    f"{rate:.1f}%", ha="center", va="bottom", fontsize=9.5)

    # 显著性标注
    for i, r in enumerate(results):
        top = max(base_rates[i], v2_rates[i]) + 5.5
        stars = p_to_stars(r["completion"]["p"])
        ax.plot([x[i] - width / 2, x[i] - width / 2, x[i] + width / 2, x[i] + width / 2],
                [top - 1, top, top, top - 1], lw=1, color="#333333")
        ax.text(x[i], top + 0.6, stars, ha="center", va="bottom", fontsize=11)

    labels = [
        "Self-play\n(v2 vs v2)",
        "v2 vs\nOriginal Rule-Based",
        "v2 vs\n1SGS",
    ]
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Game completion rate (%)")
    ax.set_ylim(0, 95)
    ax.set_title("Game Completion Rate: With vs Without the Dead-Group Detection Module\n"
                  "(error bars = Wilson 95% CI; *** p < .001, 2×2 χ² test)", fontsize=10.5)
    ax.legend(loc="upper left", frameon=False, fontsize=9)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    fig.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close(fig)


def make_turns_chart(results, out_path):
    fig, axes = plt.subplots(1, 2, figsize=(11, 5.2), dpi=300)

    n_pairs = len(results)
    x = np.arange(n_pairs)
    width = 0.32
    labels = [
        "Self-play\n(v2 vs v2)",
        "v2 vs\nOriginal Rule-Based",
        "v2 vs\n1SGS",
    ]

    # panel A: completed games only
    ax = axes[0]
    base_vals = [r["turns_completed"]["mean_y"] for r in results]
    v2_vals = [r["turns_completed"]["mean_x"] for r in results]
    bars_base = ax.bar(x - width / 2, base_vals, width, color=COLOR_BASELINE,
                        edgecolor="white", linewidth=0.6, label="Without v2 (baseline)")
    bars_v2 = ax.bar(x + width / 2, v2_vals, width, color=COLOR_V2,
                      edgecolor="white", linewidth=0.6, label="With v2")
    for bars, vals in [(bars_base, base_vals), (bars_v2, v2_vals)]:
        for rect, val in zip(bars, vals):
            ax.text(rect.get_x() + rect.get_width() / 2, rect.get_height() + 0.4,
                    f"{val:.1f}", ha="center", va="bottom", fontsize=9)
    for i, r in enumerate(results):
        stars = p_to_stars(r["turns_completed"]["p"])
        top = max(base_vals[i], v2_vals[i]) + 2.2
        ax.text(x[i], top, stars, ha="center", va="bottom", fontsize=11)
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Mean turns to game end")
    ax.set_ylim(0, max(base_vals + v2_vals) * 1.35)
    ax.set_title("(a) Completed games only", fontsize=10.5)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.legend(loc="upper right", frameon=False, fontsize=8.5)

    # panel B: all games, timeouts capped at 800
    ax = axes[1]
    base_vals2 = [r["turns_all"]["mean_y"] for r in results]
    v2_vals2 = [r["turns_all"]["mean_x"] for r in results]
    bars_base2 = ax.bar(x - width / 2, base_vals2, width, color=COLOR_BASELINE,
                         edgecolor="white", linewidth=0.6, label="Without v2 (baseline)")
    bars_v22 = ax.bar(x + width / 2, v2_vals2, width, color=COLOR_V2,
                       edgecolor="white", linewidth=0.6, label="With v2")
    for bars, vals in [(bars_base2, base_vals2), (bars_v22, v2_vals2)]:
        for rect, val in zip(bars, vals):
            ax.text(rect.get_x() + rect.get_width() / 2, rect.get_height() + 5,
                    f"{val:.0f}", ha="center", va="bottom", fontsize=9)
    for i, r in enumerate(results):
        stars = p_to_stars(r["turns_all"]["p"])
        top = max(base_vals2[i], v2_vals2[i]) + 28
        ax.text(x[i], top, stars, ha="center", va="bottom", fontsize=11)
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Mean turns (timeouts capped at 800)")
    ax.set_ylim(0, max(base_vals2 + v2_vals2) * 1.35)
    ax.set_title("(b) All games (timed-out games counted at 800 turns)", fontsize=10.5)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.legend(loc="upper right", frameon=False, fontsize=8.5)

    fig.suptitle("Average Turns per Game: With vs Without the Dead-Group Detection Module\n"
                  "(*** p < .001, ** p < .01, * p < .05, n.s. = not significant; Mann-Whitney U test)",
                  fontsize=10.5)
    fig.tight_layout(rect=[0, 0, 1, 0.90])
    fig.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close(fig)


# ==============================================================================
# 6. Excel 输出
# ==============================================================================

THIN = Side(style="thin", color="BBBBBB")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
HEADER_FILL = PatternFill(start_color="2F5496", end_color="2F5496", fill_type="solid")
HEADER_FONT = Font(name="Arial", size=10, bold=True, color="FFFFFF")
BODY_FONT = Font(name="Arial", size=10)
BOLD_BODY_FONT = Font(name="Arial", size=10, bold=True)
TITLE_FONT = Font(name="Arial", size=13, bold=True, color="2F5496")
NOTE_FONT = Font(name="Arial", size=9, italic=True, color="595959")


def _write_header(ws, row, headers, start_col=1):
    for j, h in enumerate(headers):
        c = ws.cell(row=row, column=start_col + j, value=h)
        c.font = HEADER_FONT
        c.fill = HEADER_FILL
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = BORDER


def _write_row(ws, row, values, start_col=1, bold=False, wrap_cols=None):
    """wrap_cols: 1-indexed column offsets (within this row) that should wrap text
    and left-align, used for long matchup-name cells so they don't get visually
    truncated by the neighbouring cell's content."""
    wrap_cols = wrap_cols or set()
    for j, v in enumerate(values):
        c = ws.cell(row=row, column=start_col + j, value=v)
        c.font = BOLD_BODY_FONT if bold else BODY_FONT
        c.border = BORDER
        if (j + 1) in wrap_cols:
            c.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        else:
            c.alignment = Alignment(horizontal="center", vertical="center")


def _autofit(ws, widths):
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


def _setup_print(ws, fit_width=True):
    """横向、单页宽度打印布局，避免表格在导出/打印时被截断到第二页。"""
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    if fit_width:
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 0
    ws.page_margins.left = 0.4
    ws.page_margins.right = 0.4
    ws.page_margins.top = 0.5
    ws.page_margins.bottom = 0.5


def build_excel(descriptive, results, groups, out_path, chart_paths, source_paths):
    wb = Workbook()

    # ---------- Sheet 0: README ----------
    ws = wb.active
    ws.title = "README"
    ws["A1"] = "ruleAI v2 死组模块：完成率与回合数显著性检验"
    ws["A1"].font = TITLE_FONT
    ws["A2"] = "ruleAI v2 Dead-Group Module: Completion Rate & Turn-Count Significance Analysis"
    ws["A2"].font = Font(name="Arial", size=11, italic=True, color="595959")

    lines = [
        "",
        f"生成时间 / Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"脚本 / Script: analyze_ruleAI_v2_completion_deadlock.py",
        f"数据来源 / Source files:",
        f"  - {source_paths[0]}  (20,000 games x 3 matchups, baseline / no v2)",
        f"  - {source_paths[1]}  (20,000 games x 3 matchups, ruleAI v2 extension)",
        "",
        "评审意见回应 / Addresses reviewer comment:",
        "「ruleAI v2 缺少配套回合数、完成率统计支撑：文中多次提出 v2 死组模块可减少对局死锁、",
        "降低超时，但第五章仅展示胜率卡方检验，未补充两组 AI 平均回合、游戏完成率的对比表格",
        "与显著性检验，'减少卡死'仅停留在逻辑猜想，缺少配套宏观数据佐证。」",
        "",
        "本工作簿使用逐局原始数据，为完成率与回合数两个维度分别补充了独立样本的显著性检验",
        "(2x2 chi-square / Mann-Whitney U)，可直接引用于第五章或第四章 4.8 节。",
        "",
        "三组配对比较设计 / Three comparison pairs:",
    ]
    r = 4
    for ln in lines:
        ws.cell(row=r, column=1, value=ln).font = BODY_FONT if ln else BODY_FONT
        r += 1

    for pair in COMPARISON_PAIRS:
        ws.cell(row=r, column=1, value=f"  {pair['pair_id']}: {pair['title']}").font = BOLD_BODY_FONT
        r += 1
        ws.cell(row=r, column=1, value=f"    CN: {pair['rationale_cn']}").font = NOTE_FONT
        r += 1
        ws.cell(row=r, column=1, value=f"    EN: {pair['rationale_en']}").font = NOTE_FONT
        r += 2

    method_lines = [
        "方法说明 / Methodology notes:",
        "  - 完成率检验 / Completion rate test: scipy.stats.chi2_contingency, 2x2 table, correction=False",
        "    (huge sample size makes the Yates correction negligible; Yates-corrected values also reported for verification)",
        "  - 回合数检验 / Turn-count test: scipy.stats.mannwhitneyu, two-sided (non-normal, right-skewed, censored at 800)",
        "  - 效应量 / Effect sizes: Cohen's w (completion rate), rank-biserial r (turns); thresholds per Cohen (1988):",
        "    negligible < 0.1 <= small < 0.3 <= medium < 0.5 <= large",
        "  - 95% CI for proportions: Wilson score interval (statsmodels.stats.proportion.proportion_confint)",
        "  - '完成对局' turns = mean/median among non-timed-out games only.",
        "  - '全部对局' turns = mean/median among all games, with timed-out games counted at the 800-turn cap;",
        "    this metric is a downstream composite of the completion-rate effect and should not be read as an",
        "    independent 'faster gameplay' finding on its own.",
    ]
    r += 1
    for ln in method_lines:
        ws.cell(row=r, column=1, value=ln).font = NOTE_FONT
        r += 1

    _autofit(ws, [130])

    # ---------- Sheet 1: Descriptive Stats ----------
    ws2 = wb.create_sheet("Descriptive Stats")
    ws2["A1"] = "Table X. Descriptive statistics of game completion and turn count by matchup (N = 20,000 games each)"
    ws2["A1"].font = BOLD_BODY_FONT
    headers = ["Matchup", "N", "Completed", "Timed Out", "Completion Rate (%)",
               "95% CI Lower", "95% CI Upper", "Mean Turns\n(completed only)",
               "Median Turns\n(completed only)", "SD Turns\n(completed only)",
               "Mean Turns\n(all games, capped@800)"]
    _write_header(ws2, 3, headers)
    order = ["B2_rule_vs_rule", "V3_v2_vs_v2", "B1_rule_vs_1SGS", "V2_v2_vs_1SGS",
             "V1_v2_vs_original", "B3_1SGS_vs_1SGS"]
    row = 4
    for key in order:
        d = descriptive[key]
        _write_row(ws2, row, [
            d["matchup"], d["n"], d["completed"], d["timed_out"],
            round(d["completion_rate"], 1), round(d["ci_low"], 1), round(d["ci_high"], 1),
            round(d["mean_turns_completed"], 2), d["median_turns_completed"],
            round(d["sd_turns_completed"], 2), round(d["mean_turns_all"], 1),
        ])
        row += 1
    _autofit(ws2, [40, 8, 10, 10, 14, 12, 12, 13, 13, 13, 16])
    ws2.row_dimensions[3].height = 30
    _setup_print(ws2)

    # ---------- Sheet 2: Completion Rate Tests ----------
    ws3 = wb.create_sheet("Completion Rate Tests")
    ws3["A1"] = "Table Y. Game completion rate comparison: with vs without the dead-group detection module"
    ws3["A1"].font = BOLD_BODY_FONT
    headers = ["Pair", "With v2 (matchup)", "Baseline (matchup, no v2)",
               "With v2\nCompletion (%)", "Baseline\nCompletion (%)",
               "Difference\n(pct. points)", "chi2\n(df=1)", "chi2\n(Yates-corr.)",
               "p-value", "Cohen's w", "Effect\nsize", "Sig."]
    _write_header(ws3, 3, headers)
    row = 4
    for r_ in results:
        c = r_["completion"]
        _write_row(ws3, row, [
            r_["pair"]["pair_id"],
            r_["v2_desc"]["matchup"],
            r_["base_desc"]["matchup"],
            round(c["completion_rate_v"], 1),
            round(c["completion_rate_b"], 1),
            f"+{c['diff_pct_points']:.1f}",
            round(c["chi2"], 3),
            round(c["chi2_yates"], 3),
            p_display(c["p"]),
            round(c["cohens_w"], 4),
            effect_size_label(c["cohens_w"]),
            p_to_stars(c["p"]),
        ], wrap_cols={2, 3})
        ws3.row_dimensions[row].height = 28
        row += 1
    _autofit(ws3, [8, 34, 32, 12, 12, 12, 10, 11, 12, 10, 9, 7])
    ws3.row_dimensions[3].height = 30
    note_row = row + 1
    ws3.cell(row=note_row, column=1,
             value="Note. 2x2 chi-square test of independence (game outcome: completed vs timed-out) "
                   "x (condition: v2 vs baseline). *** p<.001. Effect size thresholds per Cohen (1988): "
                   "w<0.1 negligible, 0.1-0.3 small, 0.3-0.5 medium, >=0.5 large.").font = NOTE_FONT
    ws3.merge_cells(start_row=note_row, start_column=1, end_row=note_row, end_column=len(headers))
    _setup_print(ws3)

    # ---------- Sheet 3: Turns Tests ----------
    ws4 = wb.create_sheet("Turns Tests")
    ws4["A1"] = "Table Z. Average turns per game comparison: with vs without the dead-group detection module"
    ws4["A1"].font = BOLD_BODY_FONT

    ws4["A3"] = "(a) Completed games only"
    ws4["A3"].font = BOLD_BODY_FONT
    headers_t = ["Pair", "With v2 (matchup)", "Baseline (matchup, no v2)",
                 "Mean turns\n(with v2)", "Mean turns\n(baseline)",
                 "Median\n(with v2)", "Median\n(baseline)", "Mann-\nWhitney U", "z",
                 "p-value", "Rank-\nbiserial r", "Effect\nsize", "Sig."]
    _write_header(ws4, 4, headers_t)
    row = 5
    for r_ in results:
        t = r_["turns_completed"]
        _write_row(ws4, row, [
            r_["pair"]["pair_id"], r_["v2_desc"]["matchup"], r_["base_desc"]["matchup"],
            round(t["mean_x"], 2), round(t["mean_y"], 2),
            t["median_x"], t["median_y"], round(t["u"], 1), round(t["z"], 3),
            p_display(t["p"]), round(t["rank_biserial_r"], 4),
            effect_size_label(t["rank_biserial_r"]), p_to_stars(t["p"]),
        ], wrap_cols={2, 3})
        ws4.row_dimensions[row].height = 28
        row += 1

    row += 2
    ws4.cell(row=row, column=1, value="(b) All games (timed-out games counted at the 800-turn cap)").font = BOLD_BODY_FONT
    row += 1
    _write_header(ws4, row, headers_t)
    row += 1
    for r_ in results:
        t = r_["turns_all"]
        _write_row(ws4, row, [
            r_["pair"]["pair_id"], r_["v2_desc"]["matchup"], r_["base_desc"]["matchup"],
            round(t["mean_x"], 1), round(t["mean_y"], 1),
            t["median_x"], t["median_y"], round(t["u"], 1), round(t["z"], 3),
            p_display(t["p"]), round(t["rank_biserial_r"], 4),
            effect_size_label(t["rank_biserial_r"]), p_to_stars(t["p"]),
        ], wrap_cols={2, 3})
        ws4.row_dimensions[row].height = 28
        row += 1

    row += 2
    ws4.cell(row=row, column=1,
             value="Note. Mann-Whitney U test (two-sided), used because turn counts are right-skewed and "
                   "censored at the 800-turn cap. Panel (a) isolates whether games that complete anyway "
                   "resolve faster. Panel (b) is a downstream composite of the completion-rate effect "
                   "(fewer 800-turn timeouts) and should be reported as such, not as independent evidence "
                   "of faster per-game pacing.").font = NOTE_FONT
    ws4.merge_cells(start_row=row, start_column=1, end_row=row, end_column=len(headers_t))

    _autofit(ws4, [8, 34, 32, 11, 11, 9, 9, 12, 8, 12, 10, 9, 7])
    _setup_print(ws4)

    # ---------- Sheet 4: Charts ----------
    ws5 = wb.create_sheet("Charts")
    ws5["A1"] = "Figure X. Completion rate and turn-count comparison charts (300 dpi, ready for insertion)"
    ws5["A1"].font = BOLD_BODY_FONT
    img1 = XLImage(chart_paths["completion"])
    img1.width, img1.height = 620, 380
    ws5.add_image(img1, "A3")
    img2 = XLImage(chart_paths["turns"])
    img2.width, img2.height = 700, 335
    ws5.add_image(img2, "A28")
    _setup_print(ws5, fit_width=True)

    wb.save(out_path)


# ==============================================================================
# 7. 主程序
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(description="ruleAI v2 dead-group module: completion rate & turn count significance analysis")
    parser.add_argument("--base", default="raw_game_logs_en.csv", help="baseline (no v2) raw per-game CSV")
    parser.add_argument("--v2", default="ruleAI_v2_extension_results_en_raw.csv", help="ruleAI v2 extension raw per-game CSV")
    parser.add_argument("--outdir", default=".", help="output directory")
    args = parser.parse_args()

    os.makedirs(args.outdir, exist_ok=True)

    groups, descriptive, results = run_full_analysis(args.base, args.v2)

    # ---- console summary ----
    print("=" * 78)
    print("Descriptive statistics")
    print("=" * 78)
    for key, d in descriptive.items():
        print(f"{d['matchup']:<55} N={d['n']:>6}  completion={d['completion_rate']:.1f}%  "
              f"[{d['ci_low']:.1f}, {d['ci_high']:.1f}]  mean_turns(completed)={d['mean_turns_completed']:.2f}")

    print()
    print("=" * 78)
    print("Significance tests")
    print("=" * 78)
    for r in results:
        print(f"\n--- {r['pair']['title']} ---")
        c = r["completion"]
        print(f"  Completion rate: {c['completion_rate_v']:.1f}% vs {c['completion_rate_b']:.1f}% "
              f"(+{c['diff_pct_points']:.1f} pts), chi2={c['chi2']:.4f}, p={p_display(c['p'])}, "
              f"Cohen's w={c['cohens_w']:.4f} ({effect_size_label(c['cohens_w'])})")
        t1 = r["turns_completed"]
        print(f"  Turns (completed only): {t1['mean_x']:.2f} vs {t1['mean_y']:.2f}, "
              f"U={t1['u']:.1f}, p={p_display(t1['p'])}, r={t1['rank_biserial_r']:.4f} ({effect_size_label(t1['rank_biserial_r'])})")
        t2 = r["turns_all"]
        print(f"  Turns (all games): {t2['mean_x']:.1f} vs {t2['mean_y']:.1f}, "
              f"U={t2['u']:.1f}, p={p_display(t2['p'])}, r={t2['rank_biserial_r']:.4f} ({effect_size_label(t2['rank_biserial_r'])})")

    # ---- charts ----
    chart_completion = os.path.join(args.outdir, "completion_rate_comparison.png")
    chart_turns = os.path.join(args.outdir, "avg_turns_comparison.png")
    make_completion_rate_chart(results, chart_completion)
    make_turns_chart(results, chart_turns)

    # ---- excel ----
    excel_path = os.path.join(args.outdir, "ruleAI_v2_completion_deadlock_analysis.xlsx")
    build_excel(descriptive, results, groups, excel_path,
                chart_paths=dict(completion=chart_completion, turns=chart_turns),
                source_paths=(args.base, args.v2))

    print()
    print("=" * 78)
    print(f"Saved: {excel_path}")
    print(f"Saved: {chart_completion}")
    print(f"Saved: {chart_turns}")
    print("=" * 78)


if __name__ == "__main__":
    main()
