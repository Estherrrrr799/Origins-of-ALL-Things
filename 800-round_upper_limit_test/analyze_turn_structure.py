#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze_turn_structure.py
=============================================================================
800回合上限合理性验证 —— 统计分析与绘图

读取 engine_turn_structure_check.js 产出的 data/turn_structure_raw.csv
（每局一行，覆盖 rule_vs_1SGS / rule_vs_rule / 1SGS_vs_1SGS / rule_vs_random /
1SGS_vs_random / random_vs_random 六种matchup，各5000局），计算：

  1. 各matchup有效（未超时）对局的 totalTurns 分位数（P50/P90/P95/P99/max）
  2. 各matchup超时对局的 lastActiveTurn 分位数（验证"最后一次真实决策"
     发生在远小于800的回合）
  3. 各matchup摸牌堆耗尽回合（drawPileExhaustedAtTurn）
  4. 超时对局结束时手牌剩余数之和（验证是否为"手牌清零仍未获胜"的确定性
     僵局，而非死锁但仍有牌可打的模糊状态）
  5. 空转比例：(800 - lastActiveTurn) / 800，量化800回合里有多大比例是
     纯粹的无决策空转

输出：
  output/tables/table_turn_structure_summary.csv / .tex
  output/figures/turn_structure_distribution.png

用法：
    python3 analyze_turn_structure.py
=============================================================================
"""

import os
import sys

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(SCRIPT_DIR, "data", "turn_structure_raw.csv")
TABLE_DIR = os.path.join(SCRIPT_DIR, "output", "tables")
FIG_DIR = os.path.join(SCRIPT_DIR, "output", "figures")
os.makedirs(TABLE_DIR, exist_ok=True)
os.makedirs(FIG_DIR, exist_ok=True)

MAX_TURNS = 800

MATCHUP_ORDER = [
    "rule_vs_1SGS", "rule_vs_rule", "1SGS_vs_1SGS",
    "rule_vs_random", "1SGS_vs_random", "random_vs_random",
]
MATCHUP_LABELS = {
    "rule_vs_1SGS": "Rule-Based vs 1SGS",
    "rule_vs_rule": "Rule-Based vs Rule-Based",
    "1SGS_vs_1SGS": "1SGS vs 1SGS",
    "rule_vs_random": "Rule-Based vs Random",
    "1SGS_vs_random": "1SGS vs Random",
    "random_vs_random": "Random vs Random",
}


def pct(arr, p):
    """经验分位数（与线上 JS 版本一致，用排序后取索引，不做插值）。"""
    if len(arr) == 0:
        return np.nan
    s = np.sort(arr)
    idx = min(int(len(s) * p), len(s) - 1)
    return s[idx]


def dataframe_to_booktabs_latex(df, caption, label):
    n_cols = len(df.columns)
    col_spec = "l" + "r" * (n_cols - 1)
    lines = []
    lines.append("\\begin{table}[htbp]")
    lines.append("\\centering")
    lines.append(f"\\caption{{{caption}}}")
    lines.append(f"\\label{{{label}}}")
    lines.append(f"\\begin{{tabular}}{{{col_spec}}}")
    lines.append("\\toprule")
    lines.append(" & ".join(str(c) for c in df.columns) + " \\\\")
    lines.append("\\midrule")
    for _, row in df.iterrows():
        cells = [f"{v:.2f}" if isinstance(v, float) else str(v) for v in row]
        lines.append(" & ".join(cells) + " \\\\")
    lines.append("\\bottomrule")
    lines.append("\\end{tabular}")
    lines.append("\\end{table}")
    return "\n".join(lines)


def save_table(df, name, caption, label):
    csv_path = os.path.join(TABLE_DIR, f"{name}.csv")
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    tex_path = os.path.join(TABLE_DIR, f"{name}.tex")
    with open(tex_path, "w", encoding="utf-8") as f:
        f.write(dataframe_to_booktabs_latex(df, caption, label))


def main():
    if not os.path.exists(DATA_PATH):
        raise FileNotFoundError(
            f"未找到 {DATA_PATH}，请先运行 engine_turn_structure_check.js 生成原始数据。"
        )

    df = pd.read_csv(DATA_PATH)
    df["timed_out"] = df["timed_out"].astype(bool)

    summary_rows = []
    for key in MATCHUP_ORDER:
        sub = df[df["matchup"] == key]
        if sub.empty:
            continue
        valid = sub[~sub["timed_out"]]
        timed_out = sub[sub["timed_out"]]

        n_total = len(sub)
        n_valid = len(valid)
        n_timed_out = len(timed_out)
        completion_rate = n_valid / n_total * 100 if n_total else np.nan

        valid_turns = valid["total_turns"].values
        row = {
            "Matchup": MATCHUP_LABELS[key],
            "N": n_total,
            "Valid Games": n_valid,
            "Timed-Out Games": n_timed_out,
            "Completion Rate (%)": round(completion_rate, 2),
            "Valid Turns P50": pct(valid_turns, 0.50) if n_valid else np.nan,
            "Valid Turns P95": pct(valid_turns, 0.95) if n_valid else np.nan,
            "Valid Turns P99": pct(valid_turns, 0.99) if n_valid else np.nan,
            "Valid Turns Max": int(valid_turns.max()) if n_valid else np.nan,
        }

        if n_timed_out:
            la = timed_out["last_active_turn"].values
            idle = timed_out["idle_turns"].values
            hands_end = timed_out["hands_at_end_sum"].values
            row.update({
                "Timed-Out lastActiveTurn P50": pct(la, 0.50),
                "Timed-Out lastActiveTurn P95": pct(la, 0.95),
                "Timed-Out lastActiveTurn Max": int(la.max()),
                "Mean Idle Turns (800 - lastActiveTurn)": round(float(np.mean(idle)), 1),
                "Idle Turn Fraction of Cap (%)": round(float(np.mean(idle)) / MAX_TURNS * 100, 1),
                "Pct Timed-Out Games Ending with 0 Cards Left (%)": round(
                    float((hands_end == 0).mean() * 100), 2
                ),
            })
        else:
            row.update({
                "Timed-Out lastActiveTurn P50": "N/A",
                "Timed-Out lastActiveTurn P95": "N/A",
                "Timed-Out lastActiveTurn Max": "N/A",
                "Mean Idle Turns (800 - lastActiveTurn)": "N/A",
                "Idle Turn Fraction of Cap (%)": "N/A",
                "Pct Timed-Out Games Ending with 0 Cards Left (%)": "N/A",
            })

        draw_exhaust = sub["draw_pile_exhausted_turn"].dropna().values
        row["Draw Pile Exhausted Turn (mean)"] = round(float(np.mean(draw_exhaust)), 1) if len(draw_exhaust) else "N/A"

        summary_rows.append(row)

    summary_df = pd.DataFrame(summary_rows)
    save_table(
        summary_df, "table_turn_structure_summary",
        caption="Empirical validation of the 800-turn cap: valid-game turn distribution, "
                "timed-out-game last-decision timing, and idle-turn fraction, by matchup "
                "(5{,}000 simulated games per matchup)",
        label="tab:turn_cap_validation",
    )

    print("=" * 100)
    print(summary_df.to_string(index=False))
    print("=" * 100)

    fig_paths = plot_turn_structure(df)
    print(f"\n图片已保存: {fig_paths[0]}")
    print(f"图片已保存: {fig_paths[1]}")
    print(f"表格已保存至: {TABLE_DIR}")


def plot_turn_structure(df):
    # 主图：完整 0-800 尺度，视觉上直观展示"活动全部挤在左侧、右侧巨大空白"
    fig1 = _plot_grid(df, xlim=(0, 820), show_cap_line=True,
                       suptitle="Where games actually end: valid-game completion turns vs. timed-out games' last real decision\n"
                                 "(all activity is concentrated far below the 800-turn cap; the gap to 800 is pure idle looping)")
    out_path1 = os.path.join(FIG_DIR, "turn_structure_distribution.png")
    fig1.savefig(out_path1, dpi=300, bbox_inches="tight")
    plt.close(fig1)

    # 副图：放大到 0-120 回合区间，看清有效局/超时局分布的具体形状
    fig2 = _plot_grid(df, xlim=(0, 120), show_cap_line=False,
                       suptitle="Zoomed view (0-120 turns): same data as above, x-axis truncated to show distribution shape")
    out_path2 = os.path.join(FIG_DIR, "turn_structure_distribution_zoomed.png")
    fig2.savefig(out_path2, dpi=300, bbox_inches="tight")
    plt.close(fig2)

    return out_path1, out_path2


def _plot_grid(df, xlim, show_cap_line, suptitle):
    fig, axes = plt.subplots(2, 3, figsize=(16, 9))
    axes = axes.flatten()

    for ax, key in zip(axes, MATCHUP_ORDER):
        sub = df[df["matchup"] == key]
        valid = sub[~sub["timed_out"]]
        timed_out = sub[sub["timed_out"]]

        if len(valid):
            ax.hist(valid["total_turns"], bins=30, color="#5bc78a", alpha=0.85,
                     label=f"Valid games (N={len(valid)})", edgecolor="#2a5a3a", linewidth=0.3)
        if len(timed_out):
            ax.hist(timed_out["last_active_turn"], bins=30, color="#e0954a", alpha=0.75,
                     label=f"Timed-out games'\nlast active turn (N={len(timed_out)})",
                     edgecolor="#8a5a2a", linewidth=0.3)

        if show_cap_line:
            ax.axvline(MAX_TURNS, color="#c04040", linestyle="--", linewidth=1.2, label="800-turn cap")
        ax.set_title(MATCHUP_LABELS[key], fontsize=11, fontweight="bold")
        ax.set_xlabel("Turn number", fontsize=9)
        ax.set_ylabel("Game count", fontsize=9)
        ax.set_xlim(*xlim)
        ax.tick_params(labelsize=8)
        ax.legend(fontsize=7, loc="upper right")

    fig.suptitle(suptitle, fontsize=12, y=1.02)
    fig.tight_layout()
    return fig


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"运行出错: {e}", file=sys.stderr)
        sys.exit(1)
