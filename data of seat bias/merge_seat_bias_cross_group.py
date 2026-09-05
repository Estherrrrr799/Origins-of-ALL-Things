#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
merge_seat_bias_cross_group.py
=============================================================================
座位偏置四组横向汇总 —— 合并脚本（方案A）

用途
----
你有两个相互独立、各自跑各自脚本的文件夹：
    20000×3_random_AI_seat_test/    -> random_seat_bias_analysis.py 的产出
    20000×3seat_test_final/         -> seat_bias_confirmatory_analysis.py 的产出

本脚本【不重新计算任何统计量，不碰任何原始CSV】，只读取这两个文件夹里
已经算好的 output/tables/*.csv（"Pooled"那一行），拼出一张四组横向汇总表：
    Random vs Random / Mixed diagnostic (four-seat overall) /
    Rule-Based vs Rule-Based (control) / 1SGS vs 1SGS (control)

这样做的好处：两个文件夹继续保持独立、互不干扰；本脚本任何时候重新跑，
拿到的都是"当时两边脚本已经跑出的最新结果"，不存在硬编码数字、不存在
"改了一边忘了改另一边"的风险——因为它每次都是现读现拼。

前提
----
运行前，请确保下面两个文件夹分别已经成功跑过一次自己的分析脚本，
output/tables/ 下有对应的 CSV：
    20000×3_random_AI_seat_test/output/tables/table1_seat_winrate_by_batch.csv
    20000×3_random_AI_seat_test/output/tables/table2_chi2_goodness_of_fit_by_batch.csv
    20000×3seat_test_final/output/tables/table1_seat_winrate_by_run_and_pooled.csv

用法
----
把本脚本放在两个"20000×3..."文件夹的上一级目录（即 final_submite/ 下，
和它们平级），直接运行：
    python3 merge_seat_bias_cross_group.py

如果你的文件夹名字和下面 RANDOM_FOLDER / CONFIRMATORY_FOLDER 不一致
（比如按建议改名了），改这两个常量即可，不用改其余代码。

输出
----
./merged_output/tables/table_four_group_cross_comparison.csv / .tex
./merged_output/figures/four_group_cross_comparison.png
=============================================================================
"""

import os
import sys

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ─────────────────────────────────────────────────────────────────────────
# 路径配置 —— 如果你重命名了文件夹，只需要改这两行
# ─────────────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RANDOM_FOLDER = "20000×3_random_AI_seat_test"
CONFIRMATORY_FOLDER = "20000×3seat_test_final"

RANDOM_DIR = os.path.join(SCRIPT_DIR, RANDOM_FOLDER, "output", "tables")
CONFIRM_DIR = os.path.join(SCRIPT_DIR, CONFIRMATORY_FOLDER, "output", "tables")

OUT_DIR = os.path.join(SCRIPT_DIR, "merged_output")
TABLE_DIR = os.path.join(OUT_DIR, "tables")
FIG_DIR = os.path.join(OUT_DIR, "figures")
for d in (TABLE_DIR, FIG_DIR):
    os.makedirs(d, exist_ok=True)


def require_file(path, hint):
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"找不到文件: {path}\n"
            f"提示: {hint}\n"
            f"请先确认该文件夹下的脚本已经成功跑过一次，output/tables/ 里有对应CSV。"
        )
    return path


def format_p(p):
    return "<0.000001" if p < 0.000001 else f"{p:.6f}"


# ─────────────────────────────────────────────────────────────────────────
# 1. 读取 Random vs Random 的 Pooled 结果
#    来自 random_seat_bias_analysis.py 产出的两张表：
#      table1_seat_winrate_by_batch.csv   -> 四座位胜率（算最大偏移/极差用）
#      table2_chi2_goodness_of_fit_by_batch.csv -> chi2/p/Cohen's w
# ─────────────────────────────────────────────────────────────────────────
def load_random_pooled():
    t1_path = require_file(
        os.path.join(RANDOM_DIR, "table1_seat_winrate_by_batch.csv"),
        f"应由 random_seat_bias_analysis.py 在 {RANDOM_FOLDER}/output/tables/ 下生成",
    )
    t2_path = require_file(
        os.path.join(RANDOM_DIR, "table2_chi2_goodness_of_fit_by_batch.csv"),
        f"应由 random_seat_bias_analysis.py 在 {RANDOM_FOLDER}/output/tables/ 下生成",
    )

    t1 = pd.read_csv(t1_path, encoding="utf-8-sig")
    t2 = pd.read_csv(t2_path, encoding="utf-8-sig")

    pooled_rates_row = t1[(t1["Batch"] == "Pooled")]
    if pooled_rates_row.empty:
        raise ValueError(f"{t1_path} 里没有找到 Batch=='Pooled' 的行，文件格式是否变了？")
    rates = pooled_rates_row.sort_values("Seat")["Win Rate (%)"].tolist()
    n_from_t1 = int(pooled_rates_row["N (valid games)"].iloc[0])

    pooled_stats_row = t2[t2["Batch"] == "Pooled"]
    if pooled_stats_row.empty:
        raise ValueError(f"{t2_path} 里没有找到 Batch=='Pooled' 的行，文件格式是否变了？")
    row = pooled_stats_row.iloc[0]

    n_runs = len(t2) - 1  # 除去 Pooled 这一行，其余都是单独batch

    return {
        "name": "Random vs Random",
        "n": n_from_t1,
        "rates": rates,
        "chi2": float(row["chi2"]),
        "df": int(row["df"]),
        "p": float(row["p"]) if row["p"] != "<0.000001" else 1e-7,
        "w": float(row["Cohen's w"]),
        "n_runs": n_runs,
        "source_files": [os.path.relpath(t1_path, SCRIPT_DIR), os.path.relpath(t2_path, SCRIPT_DIR)],
    }


# ─────────────────────────────────────────────────────────────────────────
# 2. 读取 Mixed diagnostic / Rule-Based control / 1SGS control 的 Pooled 结果
#    来自 seat_bias_confirmatory_analysis.py 产出的:
#      table1_seat_winrate_by_run_and_pooled.csv
# ─────────────────────────────────────────────────────────────────────────
def load_confirmatory_pooled():
    t1_path = require_file(
        os.path.join(CONFIRM_DIR, "table1_seat_winrate_by_run_and_pooled.csv"),
        f"应由 seat_bias_confirmatory_analysis.py 在 {CONFIRMATORY_FOLDER}/output/tables/ 下生成",
    )
    t1 = pd.read_csv(t1_path, encoding="utf-8-sig")

    pooled = t1[t1["Run"] == "Pooled"]
    if pooled.empty:
        raise ValueError(f"{t1_path} 里没有找到 Run=='Pooled' 的行，文件格式是否变了？")

    results = []
    for _, row in pooled.iterrows():
        rates = [row[f"Seat {i} Win Rate (%)"] for i in range(4)]
        n_runs = len(t1[(t1["Test"] == row["Test"]) & (t1["Run"] != "Pooled")])
        p_raw = row["p"]
        p_val = 1e-7 if isinstance(p_raw, str) and p_raw.startswith("<") else float(p_raw)
        results.append({
            "name": row["Test"],
            "n": int(row["N"]),
            "rates": rates,
            "chi2": float(row["chi2"]),
            "df": int(row["df"]),
            "p": p_val,
            "w": float(row["Cohen's w"]),
            "n_runs": n_runs,
            "source_files": [os.path.relpath(t1_path, SCRIPT_DIR)],
        })
    return results


# ─────────────────────────────────────────────────────────────────────────
# 3. 拼四组汇总表
# ─────────────────────────────────────────────────────────────────────────
def build_cross_group_table(groups):
    rows = []
    for g in groups:
        max_dev = max(abs(r - 25.0) for r in g["rates"])
        spread = max(g["rates"]) - min(g["rates"])
        rows.append({
            "Group": g["name"],
            "N (pooled)": g["n"],
            "N Runs Pooled": g["n_runs"],
            "Seat 0 Rate (%)": round(g["rates"][0], 2),
            "Seat 1 Rate (%)": round(g["rates"][1], 2),
            "Seat 2 Rate (%)": round(g["rates"][2], 2),
            "Seat 3 Rate (%)": round(g["rates"][3], 2),
            "chi2": round(g["chi2"], 4),
            "df": g["df"],
            "p (exact)": format_p(g["p"]),
            "Cohen's w": round(g["w"], 4),
            "Max |Deviation from 25%| (pp)": round(max_dev, 2),
            "Spread Max-Min (pp)": round(spread, 2),
            "Source File(s)": "; ".join(g["source_files"]),
        })
    return pd.DataFrame(rows)


def _escape_latex(v):
    s = str(v)
    for old, new in [("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"),
                      ("$", r"\$"), ("#", r"\#"), ("_", r"\_"), ("{", r"\{"), ("}", r"\}")]:
        s = s.replace(old, new)
    return s


def dataframe_to_booktabs_latex(df, caption, label):
    # Source File(s) 列太长，LaTeX 表里不放，只在 CSV 里保留做溯源
    df_tex = df.drop(columns=["Source File(s)"])
    n_cols = len(df_tex.columns)
    col_spec = "l" + "r" * (n_cols - 1)
    lines = ["\\begin{table}[htbp]", "\\centering", f"\\caption{{{caption}}}",
             f"\\label{{{label}}}", f"\\begin{{tabular}}{{{col_spec}}}", "\\toprule",
             " & ".join(_escape_latex(c) for c in df_tex.columns) + " \\\\", "\\midrule"]
    for _, row in df_tex.iterrows():
        cells = [f"{v:.2f}" if isinstance(v, float) else _escape_latex(v) for v in row]
        lines.append(" & ".join(cells) + " \\\\")
    lines += ["\\bottomrule", "\\end{tabular}", "\\end{table}"]
    return "\n".join(lines)


def save_table(df, name, caption, label):
    df.to_csv(os.path.join(TABLE_DIR, f"{name}.csv"), index=False, encoding="utf-8-sig")
    with open(os.path.join(TABLE_DIR, f"{name}.tex"), "w", encoding="utf-8") as f:
        f.write(dataframe_to_booktabs_latex(df, caption, label))


# ─────────────────────────────────────────────────────────────────────────
# 4. 可视化：四组效应量(Cohen's w)对比条形图
# ─────────────────────────────────────────────────────────────────────────
def plot_cross_group(df):
    fig, ax = plt.subplots(figsize=(9, 5))
    colors = ["#4f81bd" if p != "<0.000001" and float(p) >= 0.05 else "#c0504d"
              for p in df["p (exact)"]]
    bars = ax.bar(df["Group"], df["Cohen's w"], color=colors, edgecolor="#2a3a4a")
    ax.axhline(0.1, color="grey", linestyle="--", linewidth=1, label="Cohen's convention: w=0.1 (small effect)")
    ax.set_ylabel("Effect size (Cohen's w)")
    ax.set_title("Seat-position effect size across four independent experiment groups\n"
                 "(red = significant at α=0.05; all effect sizes are well below the 'small effect' threshold)")
    for bar, w in zip(bars, df["Cohen's w"]):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.001,
                 f"{w:.4f}", ha="center", va="bottom", fontsize=9)
    plt.setp(ax.get_xticklabels(), rotation=15, ha="right", fontsize=9)
    ax.legend(fontsize=9)
    ax.set_ylim(0, max(0.11, df["Cohen's w"].max() + 0.02))
    plt.tight_layout()
    out_path = os.path.join(FIG_DIR, "four_group_cross_comparison.png")
    plt.savefig(out_path, dpi=300)
    plt.close()
    return out_path


def main():
    print(f"从 {RANDOM_FOLDER}/output/tables/ 读取 Random vs Random 的 Pooled 结果...")
    random_group = load_random_pooled()
    print(f"  N={random_group['n']}, chi2={random_group['chi2']:.4f}, "
          f"p={format_p(random_group['p'])}, w={random_group['w']:.4f}")
    print(f"  来源: {random_group['source_files']}\n")

    print(f"从 {CONFIRMATORY_FOLDER}/output/tables/ 读取另外三组的 Pooled 结果...")
    confirmatory_groups = load_confirmatory_pooled()
    for g in confirmatory_groups:
        print(f"  [{g['name']}] N={g['n']}, chi2={g['chi2']:.4f}, "
              f"p={format_p(g['p'])}, w={g['w']:.4f}")
    print()

    all_groups = [random_group] + confirmatory_groups
    df = build_cross_group_table(all_groups)

    save_table(
        df, "table_four_group_cross_comparison",
        caption="Cross-group comparison of seat-position effect size: Random vs Random, "
                "the mixed four-seat diagnostic, and the Rule-Based / 1SGS internal controls "
                "(each pooled across 3 independent 20{,}000-game batches). Values are read "
                "directly from each experiment's own already-computed output tables; see "
                "Source File(s) column in the CSV for exact provenance.",
        label="tab:seat_four_group_cross",
    )

    print("=" * 100)
    print(df.drop(columns=["Source File(s)"]).to_string(index=False))
    print("=" * 100)

    fig_path = plot_cross_group(df)
    print(f"\n图片已保存: {fig_path}")
    print(f"表格已保存至: {TABLE_DIR}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"运行出错: {e}", file=sys.stderr)
        sys.exit(1)
