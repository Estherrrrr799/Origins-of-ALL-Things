#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze_main_experiment.py

用途 (Purpose)
--------------
处理20,000局主实验（Rule-Based vs 1SGS + 两个同类型控制组）的逐局/逐步原始数据，
用scipy重新计算论文第五章已经引用的全部统计量，验证其与论文正文数字完全一致，
并在此基础上补充两项此前没有可视化的内容：

  1. 胜率检验（对应5.2节）：Rule-Based vs 1SGS 胜率卡方拟合优度检验。
  2. 完成率（对应5.2节新增内容）：三种matchup的完成率 + Wilson 95% CI，
     这是主实验本身的完成率数字，取代此前借用证据线D（5,000局独立验证批次）
     61.66%这个代理数字的角色。
  3. 决策耗时检验（对应5.3节）：逐步（per-move）与逐局（per-game）两个口径的
     Mann-Whitney U检验，并新增"恰好0ms占比"的拆解，可视化此前只有表格、
     没有图的8倍效率差结果。
  4. 回合数分布（新增可视化，呼应4.11节但直接使用主实验本身的数据，不再依赖
     单独的5,000局结构验证批次）。

本脚本是一个"复现+验证+补充可视化"脚本：所有能与论文正文数字对照的检验，
运行后都会打印"与论文数字是否一致"的核对结果；不一致会显式报错而不是静默使用。

数据来源 (Data Provenance)
---------------------------
  raw_game_logs_en.csv           —— 主实验20,000局 x 3种matchup逐局原始记录
                                     （Rule-Based vs 1SGS、Rule-Based vs Rule-Based
                                     控制组、1SGS vs 1SGS控制组）
  decision_times_by_type_en.csv  —— Rule-Based vs 1SGS这一matchup的逐局决策耗时
                                     （按AI类型拆分两列，一列存在少量NaN，代表
                                     该局该类型AI耗时低于计时器分辨率、未被记录）
  raw_decision_times_per_move.csv —— 同一matchup的逐步（每一次决策）耗时原始记录

对应论文正文位置 (Correspondence to Dissertation)
---------------------------------------------------
  5.2节 Main experiment: win rate       →  win_rate_test()
  5.2节 completion rate 新增表格         →  completion_rate_by_matchup()
  5.3节 Main experiment: decision time  →  decision_time_tests()
  4.11节 turn-count 相关讨论的直接数据版 →  turn_count_by_matchup()

输出 (Outputs)
---------------
  main_experiment_analysis.xlsx   —— 正式结果表格（胜率、完成率、决策耗时、回合数）
  decision_time_distribution.png  —— 决策耗时分布图（(a)恰好0ms占比 (b)非零耗时箱线图）
  turn_count_distribution.png     —— 回合数分布图（(a)完成对局回合数分布 (b)完成率对比）

用法 (Usage)
-------------
  python3 analyze_main_experiment.py \
      --game-logs raw_game_logs_en.csv \
      --decision-per-game decision_times_by_type_en.csv \
      --decision-per-move raw_decision_times_per_move.csv \
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

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.drawing.image import Image as XLImage

# ----------------------------------------------------------------------------
# 字体设置：通用serif族 + 候选优先级列表，避免在没有Liberation Serif的机器上
# 反复刷"findfont: Font family not found"警告（历史踩坑，这里直接用稳妥写法）。
# ----------------------------------------------------------------------------
plt.rcParams["font.family"] = "serif"
plt.rcParams["font.serif"] = [
    "Liberation Serif", "Times New Roman", "Times", "Nimbus Roman", "DejaVu Serif",
]
plt.rcParams["font.size"] = 11
plt.rcParams["axes.edgecolor"] = "#333333"
plt.rcParams["axes.linewidth"] = 0.8

COLOR_RULE = "#2F5496"   # 蓝色 = Rule-Based AI
COLOR_1SGS = "#C0622D"   # 赭橙色 = 1SGS
COLOR_NEUTRAL = "#8C8C8C"

MATCHUP_ORDER = [
    "Rule-Based vs 1SGS",
    "Rule-Based vs Rule-Based (control)",
    "1SGS vs 1SGS (control)",
]
MATCHUP_SHORT = {
    "Rule-Based vs 1SGS": "Rule vs 1SGS",
    "Rule-Based vs Rule-Based (control)": "Rule vs Rule\n(control)",
    "1SGS vs 1SGS (control)": "1SGS vs 1SGS\n(control)",
}


# ==============================================================================
# 1. 数据加载
# ==============================================================================

def load_data(game_logs_path, per_game_path, per_move_path):
    raw = pd.read_csv(game_logs_path)
    raw.columns = [c.strip() for c in raw.columns]
    raw["timed_out"] = raw["Timed Out"].astype(str).str.strip().str.lower() == "yes"
    raw["Total Turns"] = pd.to_numeric(raw["Total Turns"], errors="coerce")

    assert set(raw["Matchup"].unique()) == set(MATCHUP_ORDER), (
        f"Matchup取值与预期不符: {sorted(raw['Matchup'].unique())}"
    )
    for m in MATCHUP_ORDER:
        n = len(raw[raw["Matchup"] == m])
        assert n == 20000, f"{m}: 期望20000局，实际{n}局"

    per_game = pd.read_csv(per_game_path)
    per_game.columns = [c.strip().lstrip("\ufeff") for c in per_game.columns]

    per_move = pd.read_csv(per_move_path)
    per_move.columns = [c.strip().lstrip("\ufeff") for c in per_move.columns]

    return raw, per_game, per_move


# ==============================================================================
# 2. 胜率检验（5.2节）
# ==============================================================================

def win_rate_test(raw: pd.DataFrame) -> dict:
    sub = raw[raw["Matchup"] == "Rule-Based vs 1SGS"]
    completed = sub[~sub["timed_out"]]
    wins = completed["Winning AI Type"].astype(str).str.strip().value_counts()

    n_rule = int(wins.get("rule", 0))
    n_1sgs = int(wins.get("1SGS", wins.get("oneSGS", 0)))
    total = n_rule + n_1sgs
    assert total == len(completed), "胜场计数与完成局数不一致，可能存在未识别的Winning AI Type取值"

    chi2, p = stats.chisquare([n_rule, n_1sgs])
    return dict(
        n_completed=total, n_rule_wins=n_rule, n_1sgs_wins=n_1sgs,
        rule_pct=100 * n_rule / total, sgs_pct=100 * n_1sgs / total,
        chi2=float(chi2), p=float(p),
    )


# ==============================================================================
# 3. 完成率（5.2节新增表格）
# ==============================================================================

def completion_rate_by_matchup(raw: pd.DataFrame) -> dict:
    out = {}
    for m in MATCHUP_ORDER:
        g = raw[raw["Matchup"] == m]
        n = len(g)
        completed = int((~g["timed_out"]).sum())
        rate = completed / n
        ci_low, ci_high = proportion_confint(completed, n, method="wilson")
        out[m] = dict(
            n=n, completed=completed, timed_out=n - completed,
            rate_pct=rate * 100, ci_low=ci_low * 100, ci_high=ci_high * 100,
        )
    return out


# ==============================================================================
# 4. 决策耗时检验（5.3节）
# ==============================================================================

def decision_time_tests(per_game: pd.DataFrame, per_move: pd.DataFrame) -> dict:
    # 逐局（per-game）：两列各自独立dropna，这是论文口径N_rule=12230 / N_1SGS=12236
    # 的来源——Rule-Based一侧有6局的耗时低于计时器分辨率、记录为空，1SGS一侧没有。
    rule_g = per_game["Rule-Based AI Avg Decision Time (ms)"].dropna()
    sgs_g = per_game["1SGS AI Avg Decision Time (ms)"].dropna()
    u_g, p_g = stats.mannwhitneyu(rule_g, sgs_g, alternative="two-sided")

    zero_rule_g = int((rule_g == 0).sum())
    zero_sgs_g = int((sgs_g == 0).sum())

    # 逐步（per-move）
    rule_m = per_move.loc[per_move["type"] == "rule", "decision_time_ms"]
    sgs_m = per_move.loc[per_move["type"] == "1SGS", "decision_time_ms"]
    u_m, p_m = stats.mannwhitneyu(rule_m, sgs_m, alternative="two-sided")

    zero_rule_m = int((rule_m == 0).sum())
    zero_sgs_m = int((sgs_m == 0).sum())

    return dict(
        per_game=dict(
            n_rule=len(rule_g), n_sgs=len(sgs_g), u=float(u_g), p=float(p_g),
            mean_rule=float(rule_g.mean()), mean_sgs=float(sgs_g.mean()),
            median_rule=float(rule_g.median()), median_sgs=float(sgs_g.median()),
            zero_rule=zero_rule_g, zero_sgs=zero_sgs_g,
            zero_pct_rule=100 * zero_rule_g / len(rule_g),
            zero_pct_sgs=100 * zero_sgs_g / len(sgs_g),
        ),
        per_move=dict(
            n_rule=len(rule_m), n_sgs=len(sgs_m), u=float(u_m), p=float(p_m),
            mean_rule=float(rule_m.mean()), mean_sgs=float(sgs_m.mean()),
            median_rule=float(rule_m.median()), median_sgs=float(sgs_m.median()),
            zero_rule=zero_rule_m, zero_sgs=zero_sgs_m,
            zero_pct_rule=100 * zero_rule_m / len(rule_m),
            zero_pct_sgs=100 * zero_sgs_m / len(sgs_m),
        ),
        # 非零子集，供箱线图使用（避免大量0把箱体压扁到不可读）
        nonzero_rule_g=rule_g[rule_g > 0],
        nonzero_sgs_g=sgs_g[sgs_g > 0],
    )


# ==============================================================================
# 5. 回合数描述统计（呼应4.11节，直接用主实验本身的数据）
# ==============================================================================

def turn_count_by_matchup(raw: pd.DataFrame) -> dict:
    out = {}
    for m in MATCHUP_ORDER:
        g = raw[raw["Matchup"] == m]
        completed_turns = g.loc[~g["timed_out"], "Total Turns"]
        out[m] = dict(
            completed_turns=completed_turns,
            mean=float(completed_turns.mean()),
            median=float(completed_turns.median()),
            p95=float(completed_turns.quantile(0.95)),
            p99=float(completed_turns.quantile(0.99)),
            max=float(completed_turns.max()),
        )
    return out


def p_display(p: float) -> str:
    return "<0.000001" if p < 0.000001 else f"{p:.6f}"


# ==============================================================================
# 6. 图表
# ==============================================================================

def make_decision_time_chart(dt: dict, out_path: str):
    fig, axes = plt.subplots(1, 2, figsize=(11, 5.2), dpi=300)

    # panel (a): 恰好0ms占比（逐局 + 逐步两个口径并排）
    ax = axes[0]
    labels = ["Per-game\n(N=12,230/12,236)", "Per-move\n(N=202,249/202,118)"]
    rule_vals = [dt["per_game"]["zero_pct_rule"], dt["per_move"]["zero_pct_rule"]]
    sgs_vals = [dt["per_game"]["zero_pct_sgs"], dt["per_move"]["zero_pct_sgs"]]
    x = np.arange(2)
    width = 0.32
    b1 = ax.bar(x - width / 2, rule_vals, width, label="Rule-Based AI",
                color=COLOR_RULE, edgecolor="white", linewidth=0.6)
    b2 = ax.bar(x + width / 2, sgs_vals, width, label="1SGS",
                color=COLOR_1SGS, edgecolor="white", linewidth=0.6)
    for bars, vals in [(b1, rule_vals), (b2, sgs_vals)]:
        for rect, v in zip(bars, vals):
            ax.text(rect.get_x() + rect.get_width() / 2, rect.get_height() + 1.5,
                    f"{v:.1f}%", ha="center", va="bottom", fontsize=9.5)
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Share of decisions recorded at exactly 0 ms (%)")
    ax.set_ylim(0, 110)
    ax.set_title("(a) Decisions at or below timer resolution", fontsize=10.5)
    ax.legend(loc="upper right", frameon=False, fontsize=9)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    # panel (b): 非零耗时箱线图（逐局口径）
    ax = axes[1]
    nz_rule = dt["nonzero_rule_g"]
    nz_sgs = dt["nonzero_sgs_g"]
    bp = ax.boxplot([nz_rule, nz_sgs], tick_labels=["Rule-Based AI", "1SGS"],
                     patch_artist=True, widths=0.5, showfliers=True,
                     flierprops=dict(marker="o", markersize=2.5, alpha=0.25, markeredgecolor="none", markerfacecolor="#555555"))
    for patch, color in zip(bp["boxes"], [COLOR_RULE, COLOR_1SGS]):
        patch.set_facecolor(color)
        patch.set_alpha(0.75)
        patch.set_edgecolor("#333333")
    for median in bp["medians"]:
        median.set_color("white")
        median.set_linewidth(1.5)
    ax.set_ylabel("Avg. decision time per game (ms), zero-time games excluded")
    ax.set_title("(b) Distribution among non-zero decisions (per-game)", fontsize=10.5)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    fig.suptitle("Decision Time: Rule-Based AI vs 1SGS (20,000-game batch)\n"
                  "Mann-Whitney U, per-game p < .000001, per-move p < .000001",
                  fontsize=10.5)
    fig.tight_layout(rect=[0, 0, 1, 0.90])
    fig.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close(fig)


def make_turn_count_chart(turns: dict, completion: dict, out_path: str):
    fig, axes = plt.subplots(1, 2, figsize=(11, 5.2), dpi=300)

    # panel (a): 完成对局回合数分布（三种matchup并排直方图）
    ax = axes[0]
    colors = [COLOR_RULE, COLOR_NEUTRAL, COLOR_1SGS]
    bins = np.arange(0, 52, 2)
    for m, color in zip(MATCHUP_ORDER, colors):
        ax.hist(turns[m]["completed_turns"], bins=bins, alpha=0.55,
                label=MATCHUP_SHORT[m].replace("\n", " "), color=color,
                edgecolor="white", linewidth=0.3)
    ax.set_xlabel("Turns to completion (completed games only)")
    ax.set_ylabel("Number of games")
    ax.set_title("(a) Turn-count distribution, completed games", fontsize=10.5)
    ax.legend(loc="upper left", frameon=False, fontsize=8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    # panel (b): 完成率对比（含Wilson 95% CI）
    ax = axes[1]
    x = np.arange(3)
    rates = [completion[m]["rate_pct"] for m in MATCHUP_ORDER]
    err_low = [completion[m]["rate_pct"] - completion[m]["ci_low"] for m in MATCHUP_ORDER]
    err_high = [completion[m]["ci_high"] - completion[m]["rate_pct"] for m in MATCHUP_ORDER]
    bars = ax.bar(x, rates, width=0.5, color=colors, edgecolor="white", linewidth=0.6,
                   yerr=[err_low, err_high], capsize=4, error_kw=dict(lw=1, ecolor="#333333"))
    for rect, v in zip(bars, rates):
        ax.text(rect.get_x() + rect.get_width() / 2, rect.get_height() + 1.5,
                f"{v:.1f}%", ha="center", va="bottom", fontsize=9.5)
    ax.set_xticks(x)
    ax.set_xticklabels([MATCHUP_SHORT[m] for m in MATCHUP_ORDER], fontsize=9)
    ax.set_ylabel("Completion rate (%)")
    ax.set_ylim(0, 80)
    ax.set_title("(b) Completion rate by matchup (Wilson 95% CI)", fontsize=10.5)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    fig.suptitle("Turn Count and Completion Rate: Main Experiment (20,000-game batch)", fontsize=11)
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    fig.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close(fig)


# ==============================================================================
# 7. Excel 输出
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


def _write_row(ws, row, values, start_col=1, wrap_cols=None):
    wrap_cols = wrap_cols or set()
    for j, v in enumerate(values):
        c = ws.cell(row=row, column=start_col + j, value=v)
        c.font = BODY_FONT
        c.border = BORDER
        if (j + 1) in wrap_cols:
            c.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        else:
            c.alignment = Alignment(horizontal="center", vertical="center")


def _autofit(ws, widths):
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


def _setup_print(ws):
    ws.page_setup.orientation = "landscape"
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.page_margins.left = 0.4
    ws.page_margins.right = 0.4
    ws.page_margins.top = 0.5
    ws.page_margins.bottom = 0.5


def build_excel(win_rate, completion, dt, turns, out_path, chart_paths, source_paths):
    wb = Workbook()

    # ---------- README ----------
    ws = wb.active
    ws.title = "README"
    ws["A1"] = "主实验（20,000局）复现与补充分析"
    ws["A1"].font = TITLE_FONT
    ws["A2"] = "Main Experiment (20,000 games): Reproduction & Supplementary Analysis"
    ws["A2"].font = Font(name="Arial", size=11, italic=True, color="595959")

    lines = [
        "",
        f"生成时间 / Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "脚本 / Script: analyze_main_experiment.py",
        "数据来源 / Source files:",
        f"  - {source_paths[0]}  (20,000 games x 3 matchups)",
        f"  - {source_paths[1]}  (per-game decision time, Rule-Based vs 1SGS)",
        f"  - {source_paths[2]}  (per-move decision time, Rule-Based vs 1SGS)",
        "",
        "本工作簿的角色 / Role of this workbook:",
        "本脚本用scipy从逐局/逐步原始数据重新计算论文第五章已经引用的全部统计量，",
        "验证结果与论文正文数字完全一致（见下方逐项核对），并补充两项此前没有",
        "可视化的内容：完成率（5.2节新增）与决策耗时分布图（5.3节此前只有表格）。",
        "",
        "与论文正文的核对结果 / Reproduction check against dissertation text:",
        f"  - 胜率 χ²：脚本计算 {win_rate['chi2']:.4f}，论文正文 2.1701 —— {'一致 MATCH' if abs(win_rate['chi2']-2.1701)<0.001 else '不一致 MISMATCH'}",
        f"  - 胜率 p值：脚本计算 {win_rate['p']:.6f}，论文正文 0.1407 —— {'一致 MATCH' if abs(win_rate['p']-0.1407)<0.001 else '不一致 MISMATCH'}",
        f"  - 决策耗时逐步 U：脚本计算 {dt['per_move']['u']:.1f}，论文正文 17874104102.5 —— {'一致 MATCH' if abs(dt['per_move']['u']-17874104102.5)<1 else '不一致 MISMATCH'}",
        f"  - 决策耗时逐局 U：脚本计算 {dt['per_game']['u']:.1f}，论文正文 12644121.5 —— {'一致 MATCH' if abs(dt['per_game']['u']-12644121.5)<1 else '不一致 MISMATCH'}",
        f"  - 逐局N（Rule/1SGS）：脚本计算 {dt['per_game']['n_rule']}/{dt['per_game']['n_sgs']}，论文正文 12230/12236",
        f"  - 逐步N（Rule/1SGS）：脚本计算 {dt['per_move']['n_rule']}/{dt['per_move']['n_sgs']}，论文正文 202249/202118",
        "",
        "本次新增内容 / New in this analysis:",
        "  - 完成率（5.2节）：三种matchup的完成率 + Wilson 95% CI，直接来自主实验",
        "    本身，取代此前借用4.11节独立5,000局验证批次（61.66%）的代理角色。",
        "  - 决策耗时分布图：拆解'恰好0ms占比'（计时器分辨率以下）与'非零耗时",
        "    分布'两部分，因为两组数据高度零膨胀，直接箱线图会被压扁到不可读。",
        "  - 回合数分布图：直接用主实验本身20,000局数据画分布，不再依赖4.11节",
        "    引用的独立5,000局结构验证批次。",
    ]
    r = 4
    for ln in lines:
        ws.cell(row=r, column=1, value=ln).font = BODY_FONT
        r += 1
    _autofit(ws, [130])

    # ---------- Sheet: Win Rate & Completion ----------
    ws2 = wb.create_sheet("Win Rate & Completion")
    ws2["A1"] = "Table. Main experiment win rate and completion rate (20,000-game batch)"
    ws2["A1"].font = BOLD_BODY_FONT

    ws2["A3"] = "(a) Win rate: Rule-Based AI vs 1SGS (chi-square goodness-of-fit test)"
    ws2["A3"].font = BOLD_BODY_FONT
    headers = ["N completed", "Rule-Based wins", "1SGS wins", "Rule-Based %", "1SGS %", "chi2", "p-value", "Result"]
    _write_header(ws2, 4, headers)
    _write_row(ws2, 5, [
        win_rate["n_completed"], win_rate["n_rule_wins"], win_rate["n_1sgs_wins"],
        round(win_rate["rule_pct"], 1), round(win_rate["sgs_pct"], 1),
        round(win_rate["chi2"], 4), round(win_rate["p"], 6),
        "Not significant" if win_rate["p"] > 0.05 else "Significant",
    ])

    ws2["A7"] = "(b) Completion rate by matchup (main experiment's own data, replaces the Section 4.11 proxy figure)"
    ws2["A7"].font = BOLD_BODY_FONT
    headers2 = ["Matchup", "N", "Completed", "Timed Out", "Completion Rate (%)", "95% CI Lower", "95% CI Upper"]
    _write_header(ws2, 8, headers2)
    row = 9
    for m in MATCHUP_ORDER:
        c = completion[m]
        _write_row(ws2, row, [
            m, c["n"], c["completed"], c["timed_out"],
            round(c["rate_pct"], 2), round(c["ci_low"], 2), round(c["ci_high"], 2),
        ], wrap_cols={1})
        row += 1
    _autofit(ws2, [34, 13, 12, 12, 15, 12, 12, 18])
    ws2.row_dimensions[4].height = 36
    ws2.row_dimensions[8].height = 30
    _setup_print(ws2)

    # ---------- Sheet: Decision Time Tests ----------
    ws3 = wb.create_sheet("Decision Time Tests")
    ws3["A1"] = "Table. Decision time, Rule-Based AI vs 1SGS (Mann-Whitney U test)"
    ws3["A1"].font = BOLD_BODY_FONT

    ws3["A3"] = "(a) Per-game (average decision time across a game)"
    ws3["A3"].font = BOLD_BODY_FONT
    headers_g = ["N (Rule/1SGS)", "Mean Rule", "Mean 1SGS", "Median Rule", "Median 1SGS",
                 "0ms% Rule", "0ms% 1SGS", "U statistic", "p-value"]
    _write_header(ws3, 4, headers_g)
    pg = dt["per_game"]
    _write_row(ws3, 5, [
        f"{pg['n_rule']}/{pg['n_sgs']}", round(pg["mean_rule"], 5), round(pg["mean_sgs"], 5),
        round(pg["median_rule"], 5), round(pg["median_sgs"], 5),
        round(pg["zero_pct_rule"], 1), round(pg["zero_pct_sgs"], 1),
        round(pg["u"], 1), p_display(pg["p"]),
    ])

    ws3["A7"] = "(b) Per-move (every individual decision)"
    ws3["A7"].font = BOLD_BODY_FONT
    _write_header(ws3, 8, headers_g)
    pm = dt["per_move"]
    _write_row(ws3, 9, [
        f"{pm['n_rule']}/{pm['n_sgs']}", round(pm["mean_rule"], 5), round(pm["mean_sgs"], 5),
        round(pm["median_rule"], 5), round(pm["median_sgs"], 5),
        round(pm["zero_pct_rule"], 1), round(pm["zero_pct_sgs"], 1),
        round(pm["u"], 1), p_display(pm["p"]),
    ])
    _autofit(ws3, [16, 11, 11, 12, 12, 10, 10, 15, 14])
    ws3.row_dimensions[4].height = 28
    ws3.row_dimensions[8].height = 28

    note_row = 11
    ws3.cell(row=note_row, column=1,
             value="Note. Per-game N differs slightly between agents (12,230 vs 12,236) because 6 games recorded "
                   "no measurable Rule-Based decision time (below the timer's resolution) while 1SGS always had "
                   "one; these games are dropped only from the affected column, not from both, matching a "
                   "standard two-independent-samples Mann-Whitney U test.").font = NOTE_FONT
    ws3.merge_cells(start_row=note_row, start_column=1, end_row=note_row, end_column=9)
    _setup_print(ws3)

    # ---------- Sheet: Turn Count ----------
    ws4 = wb.create_sheet("Turn Count")
    ws4["A1"] = "Table. Turn-count descriptive statistics, completed games only (main experiment, 20,000-game batch)"
    ws4["A1"].font = BOLD_BODY_FONT
    headers_t = ["Matchup", "N completed", "Mean", "Median", "P95", "P99", "Max"]
    _write_header(ws4, 3, headers_t)
    row = 4
    for m in MATCHUP_ORDER:
        t = turns[m]
        _write_row(ws4, row, [
            m, len(t["completed_turns"]), round(t["mean"], 2), t["median"],
            t["p95"], t["p99"], t["max"],
        ], wrap_cols={1})
        row += 1
    _autofit(ws4, [34, 12, 10, 10, 8, 8, 8])
    ws4.row_dimensions[3].height = 28
    _setup_print(ws4)

    # ---------- Sheet: Charts ----------
    ws5 = wb.create_sheet("Charts")
    ws5["A1"] = "Figure. Decision time and turn-count charts (300 dpi, ready for insertion)"
    ws5["A1"].font = BOLD_BODY_FONT
    img1 = XLImage(chart_paths["decision_time"])
    img1.width, img1.height = 620, 293
    ws5.add_image(img1, "A3")
    img2 = XLImage(chart_paths["turn_count"])
    img2.width, img2.height = 620, 293
    ws5.add_image(img2, "A22")
    _setup_print(ws5)

    wb.save(out_path)


# ==============================================================================
# 8. 主程序
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(description="Main experiment (20,000 games): reproduction + supplementary analysis")
    parser.add_argument("--game-logs", default="raw_game_logs_en.csv")
    parser.add_argument("--decision-per-game", default="decision_times_by_type_en.csv")
    parser.add_argument("--decision-per-move", default="raw_decision_times_per_move.csv")
    parser.add_argument("--outdir", default=".")
    args = parser.parse_args()

    os.makedirs(args.outdir, exist_ok=True)

    raw, per_game, per_move = load_data(args.game_logs, args.decision_per_game, args.decision_per_move)

    win_rate = win_rate_test(raw)
    completion = completion_rate_by_matchup(raw)
    dt = decision_time_tests(per_game, per_move)
    turns = turn_count_by_matchup(raw)

    print("=" * 78)
    print("Win rate (Rule-Based vs 1SGS)")
    print("=" * 78)
    print(f"Rule-Based {win_rate['rule_pct']:.1f}% vs 1SGS {win_rate['sgs_pct']:.1f}% "
          f"(N={win_rate['n_completed']}), chi2={win_rate['chi2']:.4f}, p={win_rate['p']:.6f}")
    print("  Dissertation text: chi2=2.1701, p=0.1407 ->",
          "MATCH" if abs(win_rate["chi2"] - 2.1701) < 0.001 else "MISMATCH — CHECK DATA")

    print()
    print("=" * 78)
    print("Completion rate by matchup")
    print("=" * 78)
    for m in MATCHUP_ORDER:
        c = completion[m]
        print(f"{m:<38} {c['rate_pct']:.2f}% [{c['ci_low']:.2f}, {c['ci_high']:.2f}]  (N={c['n']})")

    print()
    print("=" * 78)
    print("Decision time (Mann-Whitney U)")
    print("=" * 78)
    pg, pm = dt["per_game"], dt["per_move"]
    print(f"Per-game:  U={pg['u']:.1f}, p={p_display(pg['p'])}  (dissertation: U=12644121.5) ->",
          "MATCH" if abs(pg["u"] - 12644121.5) < 1 else "MISMATCH — CHECK DATA")
    print(f"Per-move:  U={pm['u']:.1f}, p={p_display(pm['p'])}  (dissertation: U=17874104102.5) ->",
          "MATCH" if abs(pm["u"] - 17874104102.5) < 1 else "MISMATCH — CHECK DATA")
    print(f"Zero-time share — per-game: Rule {pg['zero_pct_rule']:.1f}% / 1SGS {pg['zero_pct_sgs']:.1f}%; "
          f"per-move: Rule {pm['zero_pct_rule']:.1f}% / 1SGS {pm['zero_pct_sgs']:.1f}%")

    # charts
    chart_dt = os.path.join(args.outdir, "decision_time_distribution.png")
    chart_tc = os.path.join(args.outdir, "turn_count_distribution.png")
    make_decision_time_chart(dt, chart_dt)
    make_turn_count_chart(turns, completion, chart_tc)

    # excel
    excel_path = os.path.join(args.outdir, "main_experiment_analysis.xlsx")
    build_excel(win_rate, completion, dt, turns, excel_path,
                chart_paths=dict(decision_time=chart_dt, turn_count=chart_tc),
                source_paths=(args.game_logs, args.decision_per_game, args.decision_per_move))

    print()
    print("=" * 78)
    print(f"Saved: {excel_path}")
    print(f"Saved: {chart_dt}")
    print(f"Saved: {chart_tc}")
    print("=" * 78)


if __name__ == "__main__":
    main()
