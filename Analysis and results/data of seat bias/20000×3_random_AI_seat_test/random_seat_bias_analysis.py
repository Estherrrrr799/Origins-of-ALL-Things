#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
random_seat_bias_analysis.py  (v3)
=============================================================================
纯随机AI（Random vs Random）座位位置偏置（seat position bias） —— 精确统计分析脚本

本版本相对 v2 的改动
--------------------------------------------------
 1. [CHANGED] 只提取/分析"座位位置偏置"相关数据：从每批次的
    random_control_seat_bias_en*.csv（座位胜率）和 baseline_summary_en*.csv
    （Random vs Random 那一行的 Total Games / Timed-Out / Completion Rate）
    中，只取 "Random vs Random (sanity control)" 这个对照组，不涉及
    Rule-Based vs Random / 1SGS vs Random 的胜率或决策时长数据。
 2. [CHANGED] baseline_summary_en*.csv 现在是必需输入（不再是可选），
    Total Games / Timed-Out Games / Completion Rate 三个字段直接从中读取，
    不再输出 N/A（除非文件缺失或数量与批次数不匹配，此时仍会明确报错/标注，
    不会编造数值）。
 3. [CHANGED] 所有输出表格改为「整洁格式」（tidy / long format），
    字段命名遵循英文学术论文表格惯例（Seat, N, Win Rate (%), 95% CI,
    χ², df, p, Cohen's w 等），可直接在 Excel 中筛选/透视后插入论文，
    也更适合直接转 LaTeX（三线表）。
 4. [NEW] 每张表同时导出 .csv（Excel用）和 .tex（LaTeX 三线表，
    booktabs 风格，pandas.DataFrame.to_latex 生成）两种格式。
 5. 保留 v2 中已有的功能：scipy 精确 p 值、Wilson 95% CI、Cohen's w、
    Phi 系数、Bonferroni 精确校正 p 值、跨批次 CV、偏移量化、
    可视化图、可复现元数据 JSON。

用法
----
    python3 random_seat_bias_analysis.py

输入（放入 ./data/ 目录，每批次各一份，文件名需包含对应关键字）：
  - *random_control_seat_bias*.csv   （必需：座位胜率原始数据）
  - *baseline_summary*.csv           （必需：用于 Total Games/Timed-Out/
                                        Completion Rate；若缺失，这几个
                                        字段的表会被跳过并给出明确提示，
                                        不会用假设值填充）

输出（写入 ./output/）：
  figures/random_seat_bias_winrate.png
  tables/table1_seat_winrate_by_batch.csv / .tex
  tables/table2_chi2_goodness_of_fit_by_batch.csv / .tex
  tables/table3_seat0_vs_rest.csv / .tex
  tables/table4_cross_batch_stability_cv.csv / .tex
  tables/table5_completion_summary.csv / .tex
  run_metadata.json

依赖
----
    pip install scipy statsmodels matplotlib numpy pandas openpyxl --break-system-packages
=============================================================================
"""

import csv
import glob
import json
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import scipy
import statsmodels
import matplotlib
from scipy.stats import chisquare
from statsmodels.stats.proportion import proportion_confint

matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ─────────────────────────────────────────────────────────────────────────
# 路径与常量
# ─────────────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "output")
FIG_DIR = os.path.join(OUTPUT_DIR, "figures")
TABLE_DIR = os.path.join(OUTPUT_DIR, "tables")
for d in (OUTPUT_DIR, FIG_DIR, TABLE_DIR):
    os.makedirs(d, exist_ok=True)

ALPHA = 0.05
MATCHUP_LABEL = "Random vs Random (sanity control)"

SIM_PARAMS = {
    "deck_size": 84,
    "species_count": 7,
    "variants_per_species": 3,
    "copies_per_variant": 4,
    "cards_dealt_per_player": 9,
    "max_turns_cap": 800,
    "shuffle_algorithm": "Fisher-Yates",
    "random_seed": "NOT FIXED - engine uses Math.random() with no seed; "
                    "exact per-game reproduction is not possible by design. "
                    "Only statistical (multi-batch) replication is meaningful.",
}


# ─────────────────────────────────────────────────────────────────────────
# 1. 读取输入文件
# ─────────────────────────────────────────────────────────────────────────
def discover_files(pattern):
    return sorted(glob.glob(os.path.join(DATA_DIR, pattern)))


def load_seat_wins_csv(path):
    """从 random_control_seat_bias_en*.csv 中解析四座位胜场数。"""
    seat_wins = [None, None, None, None]
    with open(path, encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))

    in_seat_section = False
    for row in rows:
        if not row:
            continue
        if row[0] == "Matchup" and len(row) >= 4 and row[1] == "Seat":
            in_seat_section = True
            continue
        if row[0] == "Matchup" and len(row) >= 2 and row[1] == "chi2":
            in_seat_section = False
            continue
        if in_seat_section:
            seat_wins[int(row[1])] = int(row[2])

    if any(w is None for w in seat_wins):
        raise ValueError(f"未能从 {path} 中完整解析出四个座位的胜场数")
    return seat_wins


def load_baseline_summary_row(path, matchup_keyword=MATCHUP_LABEL):
    """从 baseline_summary_en*.csv 中只提取 Random vs Random 那一行。"""
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if matchup_keyword.lower() in row.get("Matchup", "").lower():
                return {
                    "total_games": int(row["Total Games"]),
                    "timed_out_games": int(row["Timed-Out Games"]),
                    "completion_rate": float(row["Completion Rate (%)"]),
                }
    return None


# ─────────────────────────────────────────────────────────────────────────
# 2. 统计计算
# ─────────────────────────────────────────────────────────────────────────
def cohens_w(chi2, n):
    return float(np.sqrt(chi2 / n)) if n > 0 else float("nan")


def analyze_seat_wins(seat_wins):
    n = sum(seat_wins)
    chi2, p = chisquare(seat_wins)
    w = cohens_w(chi2, n)
    rates = [wins / n * 100 for wins in seat_wins]
    cis = [proportion_confint(wins, n, alpha=0.05, method="wilson") for wins in seat_wins]
    ci_low = [lo * 100 for lo, hi in cis]
    ci_high = [hi * 100 for lo, hi in cis]
    deviations = [abs(r - 25.0) for r in rates]
    return {
        "seat_wins": seat_wins,
        "n": n,
        "rates": rates,
        "ci_low": ci_low,
        "ci_high": ci_high,
        "chi2": chi2,
        "df": len(seat_wins) - 1,
        "p": p,
        "cohens_w": w,
        "deviations_from_25": deviations,
        "max_deviation_from_25": max(deviations),
        "spread_max_minus_min": max(rates) - min(rates),
    }


def seat0_vs_rest_test(seat_wins, label):
    n = sum(seat_wins)
    seat0 = seat_wins[0]
    rest = n - seat0
    expected = [n / 4, n * 3 / 4]
    chi2, p = chisquare([seat0, rest], f_exp=expected)
    phi = cohens_w(chi2, n)
    return {
        "comparison": label,
        "n": n,
        "group_a_wins": seat0,
        "group_a_rate": seat0 / n * 100,
        "group_b_wins": rest,
        "group_b_rate": rest / n * 100,
        "chi2": chi2,
        "p": p,
        "phi_coefficient": phi,
    }


def bonferroni_p(p_raw, n_tests):
    return min(p_raw * n_tests, 1.0)


def cross_batch_stability(batch_results):
    n_batches = len(batch_results)
    rows = []
    for seat in range(4):
        rates = [r["rates"][seat] for r in batch_results]
        mean = float(np.mean(rates))
        std = float(np.std(rates, ddof=1)) if n_batches > 1 else float("nan")
        cv = std / mean if mean != 0 else float("nan")
        rows.append({"seat": seat, "rates_by_batch": rates, "mean": mean, "std": std, "cv": cv})
    return rows


def format_p(p):
    if p is None:
        return "N/A"
    return "<0.000001" if p < 0.000001 else f"{p:.6f}"


# ─────────────────────────────────────────────────────────────────────────
# 3. 主流程
# ─────────────────────────────────────────────────────────────────────────
def main():
    seat_files = discover_files("*random_control_seat_bias*.csv")
    summary_files = discover_files("*baseline_summary*.csv")

    if not seat_files:
        raise FileNotFoundError(f"在 {DATA_DIR} 未找到任何 random_control_seat_bias*.csv 文件。")

    print(f"座位胜率批次文件（{len(seat_files)} 个）：")
    for f in seat_files:
        print(f"  - {os.path.basename(f)}")

    have_summary = bool(summary_files) and len(summary_files) == len(seat_files)
    if summary_files and len(summary_files) != len(seat_files):
        print(
            f"\n警告：baseline_summary 文件数量（{len(summary_files)}）与座位胜率文件数量"
            f"（{len(seat_files)}）不一致，无法可靠一一对应，Total Games/Timed-Out/"
            f"Completion Rate 将不予输出。"
        )
    elif not summary_files:
        print(
            "\n未找到 baseline_summary*.csv，Total Games/Timed-Out/Completion Rate 表"
            "（Table 5）将不予生成。"
        )
    else:
        print(f"\nbaseline_summary 批次文件（{len(summary_files)} 个，用于 Total/Timed-Out/Completion）：")
        for f in summary_files:
            print(f"  - {os.path.basename(f)}")

    n_batches = len(seat_files)
    batch_results = []
    summary_rows = []
    for i, path in enumerate(seat_files):
        seat_wins = load_seat_wins_csv(path)
        r = analyze_seat_wins(seat_wins)
        r["batch"] = f"Batch {i + 1}"
        r["source_file"] = os.path.basename(path)
        batch_results.append(r)
        if have_summary:
            bs = load_baseline_summary_row(summary_files[i])
            summary_rows.append(bs)

    bonferroni_alpha = ALPHA / n_batches
    for r in batch_results:
        r["p_bonferroni"] = bonferroni_p(r["p"], n_batches)

    pooled_seat_wins = [sum(r["seat_wins"][s] for r in batch_results) for s in range(4)]
    pooled = analyze_seat_wins(pooled_seat_wins)
    pooled["batch"] = "Pooled"

    stability = cross_batch_stability(batch_results)
    seat0_pooled_test = seat0_vs_rest_test(pooled_seat_wins, "Seat 0 vs Seats 1-3 (pooled)")
    seat0_per_batch_tests = [
        seat0_vs_rest_test(r["seat_wins"], f"Seat 0 vs Seats 1-3 ({r['batch']})")
        for r in batch_results
    ]

    # ── 表格导出 ────────────────────────────────────────────────────
    t1 = build_table1_seat_winrate(batch_results, pooled)
    t2 = build_table2_chi2_by_batch(batch_results, pooled, n_batches, bonferroni_alpha)
    t3 = build_table3_seat0_vs_rest(seat0_per_batch_tests, seat0_pooled_test)
    t4 = build_table4_stability(stability)
    t5 = build_table5_completion(batch_results, summary_rows) if have_summary else None

    save_table(t1, "table1_seat_winrate_by_batch",
               caption="Random-vs-Random seat position win rate by batch (with 95% Wilson CI)",
               label="tab:random_seat_winrate")
    save_table(t2, "table2_chi2_goodness_of_fit_by_batch",
               caption="Chi-square goodness-of-fit test for seat position win rate (Random vs Random)",
               label="tab:random_seat_chi2")
    save_table(t3, "table3_seat0_vs_rest",
               caption="Seat 0 vs. Seats 1-3 (pooled comparison), two-category chi-square test",
               label="tab:seat0_vs_rest")
    save_table(t4, "table4_cross_batch_stability_cv",
               caption="Cross-batch stability of seat win rates (mean, SD, coefficient of variation)",
               label="tab:seat_cv")
    if t5 is not None:
        save_table(t5, "table5_completion_summary",
                   caption="Random-vs-Random completion rate summary (Total/Timed-Out/Completion Rate)",
                   label="tab:random_completion")

    # ── 控制台摘要 ──────────────────────────────────────────────────
    print("\n" + "=" * 78)
    print("摘要（精确值，scipy.stats.chisquare）")
    print("=" * 78)
    for r in batch_results:
        print(f"[{r['batch']}] N={r['n']}, rates={[round(x,1) for x in r['rates']]}, "
              f"chi2={r['chi2']:.4f}, p={format_p(r['p'])}, p_bonf={format_p(r['p_bonferroni'])}, "
              f"w={r['cohens_w']:.4f}")
    print(f"[Pooled] N={pooled['n']}, rates={[round(x,2) for x in pooled['rates']]}, "
          f"chi2={pooled['chi2']:.4f}, p={format_p(pooled['p'])}, w={pooled['cohens_w']:.4f}")
    print(f"Seat0 vs rest (pooled): chi2={seat0_pooled_test['chi2']:.4f}, "
          f"p={format_p(seat0_pooled_test['p'])}, phi={seat0_pooled_test['phi_coefficient']:.4f}")
    for s in stability:
        print(f"Seat{s['seat']} CV = {s['cv']:.4f} (mean={s['mean']:.2f}%, std={s['std']:.3f})")
    if have_summary:
        for i, bs in enumerate(summary_rows):
            print(f"[Batch {i+1}] Total={bs['total_games']}, TimedOut={bs['timed_out_games']}, "
                  f"Completion={bs['completion_rate']}%")

    # ── 图 ──────────────────────────────────────────────────────────
    fig_path = plot_seat_bias(batch_results, pooled)
    print(f"\n图片已保存: {fig_path}")

    # ── 复现元数据 ──────────────────────────────────────────────────
    meta_path = export_run_metadata(seat_files, summary_files if have_summary else [])
    print(f"复现元数据已保存: {meta_path}")

    print(f"\n所有表格已保存至: {TABLE_DIR}")


# ─────────────────────────────────────────────────────────────────────────
# 4. 表格构建（tidy / long format，pandas DataFrame）
# ─────────────────────────────────────────────────────────────────────────
def build_table1_seat_winrate(batch_results, pooled):
    rows = []
    for r in batch_results + [pooled]:
        for seat in range(4):
            rows.append({
                "Batch": r["batch"],
                "N (valid games)": r["n"],
                "Seat": seat,
                "Wins": r["seat_wins"][seat],
                "Win Rate (%)": round(r["rates"][seat], 2),
                "95% CI Lower (%)": round(r["ci_low"][seat], 2),
                "95% CI Upper (%)": round(r["ci_high"][seat], 2),
                "Deviation from 25% (pp)": round(r["deviations_from_25"][seat], 2),
            })
    return pd.DataFrame(rows)


def build_table2_chi2_by_batch(batch_results, pooled, n_batches, bonferroni_alpha):
    rows = []
    for r in batch_results:
        rows.append({
            "Batch": r["batch"],
            "N": r["n"],
            "chi2": round(r["chi2"], 4),
            "df": r["df"],
            "p": format_p(r["p"]),
            "p_bonferroni": format_p(r["p_bonferroni"]),
            f"Sig. (alpha={ALPHA})": "Yes" if r["p"] < ALPHA else "No",
            f"Sig. after Bonferroni (alpha'={bonferroni_alpha:.4f})": "Yes" if r["p_bonferroni"] < ALPHA else "No",
            "Cohen's w": round(r["cohens_w"], 4),
            "Max |Deviation from 25%| (pp)": round(r["max_deviation_from_25"], 2),
            "Spread Max-Min (pp)": round(r["spread_max_minus_min"], 2),
        })
    rows.append({
        "Batch": "Pooled",
        "N": pooled["n"],
        "chi2": round(pooled["chi2"], 4),
        "df": pooled["df"],
        "p": format_p(pooled["p"]),
        "p_bonferroni": "N/A (single pooled test, not part of per-batch family)",
        f"Sig. (alpha={ALPHA})": "Yes" if pooled["p"] < ALPHA else "No",
        f"Sig. after Bonferroni (alpha'={bonferroni_alpha:.4f})": "N/A",
        "Cohen's w": round(pooled["cohens_w"], 4),
        "Max |Deviation from 25%| (pp)": round(pooled["max_deviation_from_25"], 2),
        "Spread Max-Min (pp)": round(pooled["spread_max_minus_min"], 2),
    })
    return pd.DataFrame(rows)


def build_table3_seat0_vs_rest(per_batch_tests, pooled_test):
    rows = []
    for t in per_batch_tests + [pooled_test]:
        rows.append({
            "Comparison": t["comparison"],
            "N": t["n"],
            "Seat 0 Wins": t["group_a_wins"],
            "Seat 0 Rate (%)": round(t["group_a_rate"], 2),
            "Seats 1-3 Wins": t["group_b_wins"],
            "Seats 1-3 Rate (%)": round(t["group_b_rate"], 2),
            "chi2": round(t["chi2"], 4),
            "p": format_p(t["p"]),
            "Phi coefficient": round(t["phi_coefficient"], 4),
        })
    return pd.DataFrame(rows)


def build_table4_stability(stability):
    rows = []
    n_batches = len(stability[0]["rates_by_batch"])
    for s in stability:
        row = {"Seat": s["seat"]}
        for i, rate in enumerate(s["rates_by_batch"]):
            row[f"Batch {i+1} Win Rate (%)"] = round(rate, 2)
        row["Mean (%)"] = round(s["mean"], 3)
        row["SD (ddof=1)"] = round(s["std"], 4)
        row["CV (SD/Mean)"] = round(s["cv"], 4)
        rows.append(row)
    return pd.DataFrame(rows)


def build_table5_completion(batch_results, summary_rows):
    rows = []
    total_sum, valid_sum, timedout_sum = 0, 0, 0
    for r, bs in zip(batch_results, summary_rows):
        rows.append({
            "Batch": r["batch"],
            "Total Games": bs["total_games"],
            "Valid (Completed) Games": r["n"],
            "Timed-Out Games": bs["timed_out_games"],
            "Completion Rate (%)": bs["completion_rate"],
        })
        total_sum += bs["total_games"]
        valid_sum += r["n"]
        timedout_sum += bs["timed_out_games"]
    rows.append({
        "Batch": "Pooled",
        "Total Games": total_sum,
        "Valid (Completed) Games": valid_sum,
        "Timed-Out Games": timedout_sum,
        "Completion Rate (%)": round(valid_sum / total_sum * 100, 2) if total_sum else "N/A",
    })
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────
# 5. 保存表格：CSV（Excel用） + LaTeX 三线表（booktabs）
#    [FIXED] 不再使用 pandas.DataFrame.to_latex(caption=..., label=...)。
#    该写法在较新版本 pandas 中会内部走 Styler 分支，需要额外安装 jinja2
#    依赖，否则报错 "Missing optional dependency 'Jinja2'"。这里改为手写
#    booktabs 风格的 LaTeX 表格，不依赖 pandas 的 to_latex/Styler，
#    只用 pandas 做数据整理，避免这个环境相关的报错。
# ─────────────────────────────────────────────────────────────────────────
def _escape_latex(val):
    """转义 LaTeX 特殊字符：& % $ # _ { } ~ ^ \\"""
    s = str(val)
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
        "_": r"\_", "{": r"\{", "}": r"\}",
        "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
    }
    for old, new in replacements.items():
        s = s.replace(old, new)
    return s


def dataframe_to_booktabs_latex(df, caption, label):
    """手写生成 booktabs 风格三线表 LaTeX 代码，不依赖 jinja2。"""
    n_cols = len(df.columns)
    col_spec = "l" + "r" * (n_cols - 1)  # 首列左对齐，其余右对齐（可按需调整）

    lines = []
    lines.append("\\begin{table}[htbp]")
    lines.append("\\centering")
    lines.append(f"\\caption{{{caption}}}")
    lines.append(f"\\label{{{label}}}")
    lines.append(f"\\begin{{tabular}}{{{col_spec}}}")
    lines.append("\\toprule")
    header = " & ".join(_escape_latex(c) for c in df.columns) + " \\\\"
    lines.append(header)
    lines.append("\\midrule")
    for _, row in df.iterrows():
        cells = []
        for v in row:
            if isinstance(v, float):
                cells.append(f"{v:.2f}")
            else:
                cells.append(_escape_latex(v))
        lines.append(" & ".join(cells) + " \\\\")
    lines.append("\\bottomrule")
    lines.append("\\end{tabular}")
    lines.append("\\end{table}")
    return "\n".join(lines)


def save_table(df, name, caption, label):
    csv_path = os.path.join(TABLE_DIR, f"{name}.csv")
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    tex_path = os.path.join(TABLE_DIR, f"{name}.tex")
    latex_body = dataframe_to_booktabs_latex(df, caption, label)
    with open(tex_path, "w", encoding="utf-8") as f:
        f.write(latex_body)


# ─────────────────────────────────────────────────────────────────────────
# 6. 可视化
# ─────────────────────────────────────────────────────────────────────────
def plot_seat_bias(batch_results, pooled):
    all_results = batch_results + [pooled]
    n_panels = len(all_results)

    fig, axes = plt.subplots(1, n_panels, figsize=(3.6 * n_panels, 4.2), sharey=True)
    if n_panels == 1:
        axes = [axes]

    seat_labels = ["Seat 0", "Seat 1", "Seat 2", "Seat 3"]
    bar_color = "#5bc78a"
    pooled_color = "#3a9d5f"
    expected_line_color = "#c04040"

    for ax, r in zip(axes, all_results):
        rates = r["rates"]
        err_low = [rates[i] - r["ci_low"][i] for i in range(4)]
        err_high = [r["ci_high"][i] - rates[i] for i in range(4)]
        is_pooled = r["batch"] == "Pooled"
        color = pooled_color if is_pooled else bar_color

        ax.bar(seat_labels, rates, color=color, edgecolor="#2a5a3a", linewidth=0.8,
               yerr=[err_low, err_high], capsize=4,
               error_kw={"ecolor": "#2a3a4a", "elinewidth": 1.2, "capthick": 1.2})
        ax.axhline(25, color=expected_line_color, linestyle="--", linewidth=1.2,
                   label="Expected (25%)" if ax is axes[0] else None)

        sig_mark = "*" if r["p"] < 0.05 else "n.s."
        title = f"{r['batch']}\n(N={r['n']})\nchi2={r['chi2']:.2f}, p={format_p(r['p'])} ({sig_mark})"
        ax.set_title(title, fontsize=9.5)
        ax.set_ylim(0, max(rates) + 8)
        ax.tick_params(axis="x", labelsize=9)
        ax.tick_params(axis="y", labelsize=9)
        if ax is axes[0]:
            ax.set_ylabel("Win Rate (%)", fontsize=10)

    fig.suptitle(
        "Random-vs-Random Seat Position Win Rate\n"
        "(error bars: 95% Wilson score CI; dashed line: theoretical uniform 25%)",
        fontsize=11, y=1.06,
    )
    handles, labels = axes[0].get_legend_handles_labels()
    if handles:
        fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.5, 1.0),
                   fontsize=9, frameon=False)

    fig.tight_layout()
    out_path = os.path.join(FIG_DIR, "random_seat_bias_winrate.png")
    fig.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    return out_path


# ─────────────────────────────────────────────────────────────────────────
# 7. 复现元数据
# ─────────────────────────────────────────────────────────────────────────
def export_run_metadata(seat_files, summary_files):
    def file_info(path):
        stat = os.stat(path)
        return {
            "filename": os.path.basename(path),
            "modified_time_utc": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            "size_bytes": stat.st_size,
        }

    metadata = {
        "script": "random_seat_bias_analysis.py (v3)",
        "script_run_time_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "Seat-position bias analysis for the Random-vs-Random (sanity control) "
                 "matchup only. Rule-Based-vs-Random / 1SGS-vs-Random win-rate and "
                 "decision-time data in the uploaded files were NOT analyzed here.",
        "environment": {
            "python": sys.version.split()[0],
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "scipy": scipy.__version__,
            "statsmodels": statsmodels.__version__,
            "matplotlib": matplotlib.__version__,
        },
        "simulation_parameters_from_source_code": SIM_PARAMS,
        "input_seat_bias_files": [file_info(f) for f in seat_files],
        "input_baseline_summary_files": [file_info(f) for f in summary_files],
        "known_data_gaps": [
            "No random seed exists to record - the simulation engine calls Math.random() "
            "with no fixed seed by design, so bit-exact game-by-game reproduction is not "
            "possible; only statistical (independent multi-batch) replication is meaningful.",
            "The games-per-matchup UI parameter (n) used at run time is not stored in any "
            "exported CSV; it is inferred here only via Total Games in baseline_summary_en.csv "
            "when that file is provided.",
        ],
    }

    out_path = os.path.join(OUTPUT_DIR, "run_metadata.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)
    return out_path


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"运行出错: {e}", file=sys.stderr)
        sys.exit(1)
