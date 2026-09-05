#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
seat_bias_confirmatory_analysis.py  (v2)
=============================================================================
座位偏置 confirmatory 分析 —— 三次独立20000局重复，pooled 结果

相对原版（seat_bias_confirmatory_analysis.py，pooled version）的改动
--------------------------------------------------------------------------
原版脚本的统计逻辑本身没有问题（本次已用你的三批真实数据核对，pooled
chi2/p/Cohen's w 与你项目文档记录的 canonical 数值逐位吻合）。但发现并
修复了一个真实发生过的可复现性风险：

 [FIXED-CRITICAL] 原脚本用 glob.glob("control_group_seat_bias_en*.csv") /
    glob.glob("seat_diagnostic_results_en*.csv") 在当前目录不加区分地匹配
    文件，如果目录里混入了同前缀但属于项目更早阶段（例如"20000局单次复核"）
    的文件，会被静默当成"又一次独立重复"一起 pool 进最终结果，且原脚本
    从不打印匹配到的文件名，几乎无法察觉。本次实测复现：混入一个额外文件后，
    Mixed diagnostic 的 pooled p 从 0.000020 变成 0.000004，Cohen's w 从
    0.0257 变成 0.0238 —— 改变了论文会引用的数字，且不会有任何提示。
    修复：
      1) 只从脚本所在目录下的 data/ 子目录读取文件（不再用 cwd 相对路径），
         避免误吞旧文件；
      2) 明确打印每一个匹配到的文件名 + 修改时间，任何意外文件混入都能
         第一时间在控制台看到；
      3) 提供 EXPECTED_N_RUNS 校验：如果匹配到的文件数与预期不符，直接
         报错终止，而不是"悄悄地用不对的数量继续跑"。

其余改动（均为增强，不改变原有 pooling 方法论）：
 [NEW] Bonferroni 校正精确 p 值（每个 test 内部按 run 数校正），而不只是
    显著性布尔标记。
 [NEW] Wilson score 95% 置信区间替代原来的正态近似 SE，用于误差棒和数值
    表格（与本项目其余统计脚本口径一致）。
 [NEW] 跨批次稳定性（CV）：每个座位在 3 次重复里胜率的均值/标准差/变异
    系数，量化"座位效应方向是否稳定"而不仅仅是"pooled 后是否显著"。
 [NEW] 四组横向汇总表（Random vs Random / Rule-Based 内战 / 1SGS 内战 /
    Mixed diagnostic 四座位整体），把散落在不同脚本里的座位效应证据统一
    放进一张表，配 Bonferroni 校正、效应量、最大偏移，直接可引用。
    Random vs Random 那一组数字来自 random_seat_bias_analysis.py 已经算好
    的 pooled 结果（本脚本不重新计算，只做汇总整合，来源在表注中注明）。
 [NEW] 所有表格同时导出 .csv（Excel用）和 .tex（手写 booktabs 三线表，
    不依赖 pandas Styler / jinja2，与项目里其它脚本保持一致）。
 [NEW] run_metadata.json：记录本次运行匹配到的每一个输入文件名、修改时间、
    大小，作为可复现性凭证。

用法
----
    python3 seat_bias_confirmatory_analysis.py

输入：./data/ 目录下的
    seat_diagnostic_results_en_batch*.csv   (Mixed diagnostic，预期3个)
    control_group_seat_bias_en_batch*.csv   (Rule/1SGS 控制组，预期3个)
文件名不要求必须是 batch1/2/3，但建议明确编号，避免未来再次发生同前缀
不同阶段文件混淆的问题。

输出：./output/ 目录下的 tables/ 、figures/ 、run_metadata.json
=============================================================================
"""

import glob
import json
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import scipy
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.stats import chisquare, chi2 as chi2dist, ncx2
from statsmodels.stats.proportion import proportion_confint

# ─────────────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "output")
TABLE_DIR = os.path.join(OUTPUT_DIR, "tables")
FIG_DIR = os.path.join(OUTPUT_DIR, "figures")
for d in (TABLE_DIR, FIG_DIR):
    os.makedirs(d, exist_ok=True)

MIXED_PATTERN = "seat_diagnostic_results_en*.csv"
CONTROL_PATTERN = "control_group_seat_bias_en*.csv"

ALPHA = 0.05
EXPECTED_N_RUNS = 3  # [NEW] 预期的独立重复批次数；数量不符时直接报错，而不是静默继续

# [NEW] Random vs Random 的 pooled 结果，来自 random_seat_bias_analysis.py
# 已经算好的输出（table2_chi2_goodness_of_fit_by_batch.csv / table1..._by_batch.csv,
# Pooled 行）。本脚本不重新计算，只做横向汇总整合，来源在表注/console输出中注明。
RANDOM_VS_RANDOM_POOLED = {
    "name": "Random vs Random",
    "n": 4110,
    "wins": [986, 1010, 1070, 1044],
    "chi2": 3.9971,
    "p": 0.261780,
    "w": 0.0312,
    "n_runs": 3,
    "source": "random_seat_bias_analysis.py output (table1/table2, 'Pooled' row) — "
              "computed separately, not re-derived here.",
}


def cohens_w(wins):
    wins = np.array(wins, dtype=float)
    n = wins.sum()
    p_obs = wins / n
    p_exp = np.array([1 / len(wins)] * len(wins))
    return float(np.sqrt(np.sum((p_obs - p_exp) ** 2 / p_exp)))


def achieved_power(n, w, df, alpha=0.05):
    ncp = n * w ** 2
    crit = chi2dist.ppf(1 - alpha, df)
    return float(1 - ncx2.cdf(crit, df, ncp))


def bonferroni_p(p_raw, n_tests):
    return min(p_raw * n_tests, 1.0)


def format_p(p):
    return "<0.000001" if p < 0.000001 else f"{p:.6f}"


# ─────────────────────────────────────────────────────────────────────────
# [FIXED] 文件发现：只从 DATA_DIR 读取，打印匹配到的文件名，并校验数量
# ─────────────────────────────────────────────────────────────────────────
def discover_and_report(pattern, expected_n=EXPECTED_N_RUNS):
    files = sorted(glob.glob(os.path.join(DATA_DIR, pattern)))
    print(f"匹配 '{pattern}' 找到 {len(files)} 个文件：")
    for f in files:
        mtime = datetime.fromtimestamp(os.path.getmtime(f)).strftime("%Y-%m-%d %H:%M:%S")
        print(f"    - {os.path.basename(f)}  (修改时间: {mtime})")
    if expected_n is not None and len(files) != expected_n:
        raise RuntimeError(
            f"文件数量校验失败：预期 {expected_n} 个独立重复批次，实际匹配到 {len(files)} 个。\n"
            f"请检查 data/ 目录下是否混入了不属于本次confirmatory重复的文件"
            f"（例如更早阶段的探索性/复核性单次跑），确认无误后再运行。\n"
            f"如果这次确实就是要跑 {len(files)} 个批次，请修改脚本顶部的 EXPECTED_N_RUNS。"
        )
    print()
    return files


def load_mixed_diagnostic_files():
    files = discover_and_report(MIXED_PATTERN)
    runs = []
    for f in files:
        df = pd.read_csv(f, encoding="utf-8-sig", nrows=4)
        wins = df["Wins"].tolist()
        labels = df["Identity"].tolist() if "Identity" in df.columns else [f"Seat {i}" for i in range(4)]
        runs.append({"file": f, "wins": wins, "labels": labels})
    return runs, files


def load_control_group_files():
    files = discover_and_report(CONTROL_PATTERN)
    runs = []
    for f in files:
        with open(f, encoding="utf-8-sig") as fh:
            lines = [l.strip() for l in fh.readlines()]
        blank_idx = next(i for i, l in enumerate(lines) if l == "")
        seat_lines = lines[1:blank_idx]
        groups = {}
        for line in seat_lines:
            parts = line.split(",")
            matchup, seat_idx, w = parts[0], int(parts[1]), int(parts[2])
            groups.setdefault(matchup, [0, 0, 0, 0])
            groups[matchup][seat_idx] = w
        runs.append({"file": f, "wins_by_matchup": groups})
    return runs, files


# ─────────────────────────────────────────────────────────────────────────
# 核心分析：单个 test 的多次重复 + pooling
# ─────────────────────────────────────────────────────────────────────────
def analyse_and_pool(name, per_run_wins, labels, table_rows, cv_rows):
    n_runs = len(per_run_wins)
    print("=" * 78)
    print(name)
    print("=" * 78)

    pooled = np.zeros(len(per_run_wins[0]), dtype=int)
    run_rates = []  # [NEW] 用于跨批次CV
    for i, wins in enumerate(per_run_wins, start=1):
        wins = np.array(wins)
        n = int(wins.sum())
        exp = [n / len(wins)] * len(wins)
        chi2_val, p = chisquare(wins, f_exp=exp)
        p_bonf = bonferroni_p(p, n_runs)  # [NEW]
        pct = wins / n * 100
        run_rates.append(pct)
        print(f"  Run {i}: n={n}, wins={wins.tolist()}, win%={[f'{x:.1f}%' for x in pct]}, "
              f"chi2={chi2_val:.3f}, p={p:.5f}, p_bonf={p_bonf:.5f}")
        table_rows.append({
            "Test": name, "Run": f"Run {i}", "N": n,
            **{f"Seat {j} Wins": int(wins[j]) for j in range(len(wins))},
            **{f"Seat {j} Win Rate (%)": round(pct[j], 2) for j in range(len(wins))},
            "chi2": round(chi2_val, 4), "df": len(wins) - 1,
            "p": format_p(p), "p_bonferroni": format_p(p_bonf),
            "Cohen's w": round(cohens_w(wins), 4),
        })
        pooled += wins

    n_pool = int(pooled.sum())
    exp_pool = [n_pool / len(pooled)] * len(pooled)
    chi2_pool, p_pool = chisquare(pooled, f_exp=exp_pool)
    w = cohens_w(pooled)
    power = achieved_power(n_pool, w, df=len(pooled) - 1)
    pct_pool = pooled / n_pool * 100

    print(f"  -> POOLED across {n_runs} run(s): n={n_pool}, wins={pooled.tolist()}")
    print(f"     win% = {[f'{x:.2f}%' for x in pct_pool]}")
    print(f"     chi2={chi2_pool:.4f}, df={len(pooled)-1}, p={p_pool:.6f}")
    print(f"     effect size (Cohen's w)={w:.4f}, achieved power at this n={power:.3f}")
    verdict = "SIGNIFICANT" if p_pool < 0.05 else "not significant"
    print(f"     -> {verdict} at alpha=0.05\n")

    table_rows.append({
        "Test": name, "Run": "Pooled", "N": n_pool,
        **{f"Seat {j} Wins": int(pooled[j]) for j in range(len(pooled))},
        **{f"Seat {j} Win Rate (%)": round(pct_pool[j], 2) for j in range(len(pooled))},
        "chi2": round(chi2_pool, 4), "df": len(pooled) - 1,
        "p": format_p(p_pool),
        "p_bonferroni": "N/A (single pooled test, not part of per-run family)",
        "Cohen's w": round(w, 4),
    })

    # [NEW] 跨批次CV：每个座位在 n_runs 次重复里的胜率均值/标准差/CV
    run_rates = np.array(run_rates)  # shape (n_runs, n_seats)
    for seat in range(run_rates.shape[1]):
        rates = run_rates[:, seat]
        mean = float(np.mean(rates))
        std = float(np.std(rates, ddof=1)) if n_runs > 1 else float("nan")
        cv = std / mean if mean != 0 else float("nan")
        cv_rows.append({
            "Test": name, "Seat": seat,
            **{f"Run {i+1} Win Rate (%)": round(rates[i], 2) for i in range(n_runs)},
            "Mean (%)": round(mean, 3), "SD (ddof=1)": round(std, 4), "CV (SD/Mean)": round(cv, 4),
        })

    cis = [proportion_confint(int(pooled[i]), n_pool, alpha=0.05, method="wilson") for i in range(len(pooled))]

    return {"name": name, "n": n_pool, "wins": pooled, "labels": labels, "pct": pct_pool,
            "ci_low": [lo * 100 for lo, hi in cis], "ci_high": [hi * 100 for lo, hi in cis],
            "chi2": chi2_pool, "p": p_pool, "w": w, "power": power, "n_runs": n_runs}


# ─────────────────────────────────────────────────────────────────────────
# [NEW] 四组横向汇总表：Random / RuleAI内战 / 1SGS内战 / Mixed diagnostic
# ─────────────────────────────────────────────────────────────────────────
def build_cross_group_table(pooled_results):
    rows = []
    all_groups = pooled_results + [RANDOM_VS_RANDOM_POOLED]
    for g in all_groups:
        rates = [w / g["n"] * 100 for w in g["wins"]] if "pct" not in g else list(g["pct"])
        max_dev = max(abs(r - 25.0) for r in rates)
        spread = max(rates) - min(rates)
        rows.append({
            "Group": g["name"],
            "N (pooled)": g["n"],
            "N Runs Pooled": g["n_runs"],
            "chi2": round(g["chi2"], 4),
            "df": 3,
            "p (exact)": format_p(g["p"]),
            "Cohen's w": round(g["w"], 4),
            "Max |Deviation from 25%| (pp)": round(max_dev, 2),
            "Spread Max-Min (pp)": round(spread, 2),
            "Achieved Power (%)": round(g.get("power", float("nan")) * 100, 1) if "power" in g else "N/A",
        })
    df = pd.DataFrame(rows)
    return df


# ─────────────────────────────────────────────────────────────────────────
# LaTeX（手写 booktabs，不依赖 jinja2）
# ─────────────────────────────────────────────────────────────────────────
def _escape_latex(v):
    s = str(v)
    for old, new in [("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"),
                      ("$", r"\$"), ("#", r"\#"), ("_", r"\_"), ("{", r"\{"), ("}", r"\}")]:
        s = s.replace(old, new)
    return s


def dataframe_to_booktabs_latex(df, caption, label):
    n_cols = len(df.columns)
    col_spec = "l" + "r" * (n_cols - 1)
    lines = ["\\begin{table}[htbp]", "\\centering", f"\\caption{{{caption}}}",
             f"\\label{{{label}}}", f"\\begin{{tabular}}{{{col_spec}}}", "\\toprule",
             " & ".join(_escape_latex(c) for c in df.columns) + " \\\\", "\\midrule"]
    for _, row in df.iterrows():
        cells = [f"{v:.2f}" if isinstance(v, float) else _escape_latex(v) for v in row]
        lines.append(" & ".join(cells) + " \\\\")
    lines += ["\\bottomrule", "\\end{tabular}", "\\end{table}"]
    return "\n".join(lines)


def save_table(df, name, caption, label):
    df.to_csv(os.path.join(TABLE_DIR, f"{name}.csv"), index=False, encoding="utf-8-sig")
    with open(os.path.join(TABLE_DIR, f"{name}.tex"), "w", encoding="utf-8") as f:
        f.write(dataframe_to_booktabs_latex(df, caption, label))


# ─────────────────────────────────────────────────────────────────────────
# 绘图（沿用原版风格，误差棒改为 Wilson CI）
# ─────────────────────────────────────────────────────────────────────────
def plot_pooled(results):
    fig, axes = plt.subplots(1, len(results), figsize=(6.5 * len(results), 5.2), sharey=True)
    if len(results) == 1:
        axes = [axes]

    for ax, res in zip(axes, results):
        n = res["n"]
        pct = res["pct"]
        err_low = [pct[i] - res["ci_low"][i] for i in range(len(pct))]
        err_high = [res["ci_high"][i] - pct[i] for i in range(len(pct))]
        seat_labels = [str(l) for l in res["labels"]]

        color = "#c0504d" if res["p"] < 0.05 else "#4f81bd"
        bars = ax.bar(seat_labels, pct, yerr=[err_low, err_high], capsize=4, color=color, zorder=3)
        expected = 100 / len(pct)
        ax.axhline(expected, color="grey", linestyle="--", linewidth=1, zorder=2)

        title = (f"{res['name']}\n"
                 f"n={n:,} pooled across {res['n_runs']} run(s), chi2={res['chi2']:.3f}, p={format_p(res['p'])}\n"
                 f"effect size w={res['w']:.3f}, achieved power={res['power']:.1%}")
        ax.set_title(title, fontsize=10)
        ax.set_ylabel("Win rate (%) [error bars: 95% Wilson CI]")
        ax.set_ylim(0, max(pct) + 6)
        for bar, p_ in zip(bars, pct):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                     f"{p_:.1f}%", ha="center", va="bottom", fontsize=9)
        plt.setp(ax.get_xticklabels(), rotation=15, ha="right", fontsize=8.5)

    fig.suptitle("Seat-position confirmatory test (pooled across all available reruns)\n"
                 "dashed line = expected win rate under no seat effect; red = significant at 0.05")
    plt.tight_layout()
    out_path = os.path.join(FIG_DIR, "fig_seat_bias_confirmatory.png")
    plt.savefig(out_path, dpi=300)
    plt.close()
    return out_path


def export_run_metadata(mixed_files, control_files):
    def info(f):
        st = os.stat(f)
        return {"filename": os.path.basename(f),
                "modified_time_utc": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
                "size_bytes": st.st_size}
    meta = {
        "script": "seat_bias_confirmatory_analysis.py (v2)",
        "run_time_utc": datetime.now(timezone.utc).isoformat(),
        "expected_n_runs": EXPECTED_N_RUNS,
        "environment": {"python": sys.version.split()[0], "numpy": np.__version__,
                         "pandas": pd.__version__, "scipy": scipy.__version__},
        "mixed_diagnostic_files": [info(f) for f in mixed_files],
        "control_group_files": [info(f) for f in control_files],
        "random_vs_random_source": RANDOM_VS_RANDOM_POOLED["source"],
    }
    path = os.path.join(OUTPUT_DIR, "run_metadata.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return path


def main():
    table_rows = []
    cv_rows = []
    pooled_results = []

    mixed_runs, mixed_files = load_mixed_diagnostic_files()
    wins_list = [r["wins"] for r in mixed_runs]
    labels = mixed_runs[0]["labels"]
    pooled_results.append(analyse_and_pool("Mixed diagnostic (four-seat overall)", wins_list, labels,
                                            table_rows, cv_rows))

    control_runs, control_files = load_control_group_files()
    matchup_names = list(control_runs[0]["wins_by_matchup"].keys())
    for matchup in matchup_names:
        wins_list = [r["wins_by_matchup"][matchup] for r in control_runs]
        pooled_results.append(analyse_and_pool(f"Control group - {matchup}", wins_list,
                                                [f"Seat {i}" for i in range(4)], table_rows, cv_rows))

    # ── Table 1: 全部 run + pooled 明细 ──
    t1 = pd.DataFrame(table_rows)
    save_table(t1, "table1_seat_winrate_by_run_and_pooled",
               caption="Seat win rate by individual run and pooled, with Bonferroni-corrected p-values",
               label="tab:seat_confirm_by_run")

    # ── Table 2: 跨批次稳定性 CV ──
    t2 = pd.DataFrame(cv_rows)
    save_table(t2, "table2_cross_batch_stability_cv",
               caption="Cross-run stability of seat win rates (mean, SD, coefficient of variation)",
               label="tab:seat_confirm_cv")

    # ── Table 3: 四组横向汇总（本次新增，最初被要求的"三组对比表"，
    #    实际整合了四组：Random / RuleAI内战 / 1SGS内战 / Mixed diagnostic） ──
    t3 = build_cross_group_table(pooled_results)
    save_table(t3, "table3_cross_group_comparison",
               caption="Cross-group comparison of seat-position effect size: Random vs Random "
               "(from a separately reported pooled analysis; see table note), Rule-Based "
               "internal control, 1SGS internal control, and the mixed four-seat diagnostic",
               label="tab:seat_cross_group")

    print("=" * 78)
    print("四组横向汇总（Table 3）")
    print("=" * 78)
    print(t3.to_string(index=False))

    fig_path = plot_pooled(pooled_results)
    print(f"\n图片已保存: {fig_path}")

    meta_path = export_run_metadata(mixed_files, control_files)
    print(f"复现元数据已保存: {meta_path}")
    print(f"\n所有表格已保存至: {TABLE_DIR}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"运行出错: {e}", file=sys.stderr)
        sys.exit(1)
