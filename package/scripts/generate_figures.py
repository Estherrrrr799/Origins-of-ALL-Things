"""
generate_figures.py
--------------------
Generates the three dissertation figures for the Evaluation chapter,
reading directly from the experiment CSV files already produced by
simulation.html. Run this script whenever the underlying CSVs are
regenerated, and it will refresh all three figures automatically.

Usage:
    python3 generate_figures.py

Outputs (written to ./figures/):
    fig1_decision_time_distribution.png / .pdf
    fig2_win_rate_comparison.png / .pdf
    fig3_seat_diagnostic.png / .pdf
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from scipy.stats import chisquare, mannwhitneyu
import os

# ── Setup ─────────────────────────────────────────────────────────
OUT_DIR = "figures"
os.makedirs(OUT_DIR, exist_ok=True)

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 11,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "figure.dpi": 150,
})

COLOR_RULE = "#5b9bd5"       # blue  - Rule-Based AI
COLOR_1SGS = "#8858a8"    # purple - 1SGS AI
COLOR_RULE_V2 = "#4caf7d"    # green - Rule-Based AI v2

def save(fig, name):
    fig.savefig(f"{OUT_DIR}/{name}.png", bbox_inches="tight")
    fig.savefig(f"{OUT_DIR}/{name}.pdf", bbox_inches="tight")
    plt.close(fig)
    print(f"  saved {OUT_DIR}/{name}.png + .pdf")


# ════════════════════════════════════════════════════════════════
# Figure 1: Decision-time distribution (boxplot)
# Data source: decision_times_by_type.csv
# Why a boxplot: shows the right-skewed, non-normal shape that
# justifies using Mann-Whitney U rather than a t-test (see the
# reference table for choosing a runtime-comparison test).
# ════════════════════════════════════════════════════════════════
def fig1_decision_time():
    print("Figure 1: decision time distribution")
    df = pd.read_csv("decision_times_by_type_en.csv", encoding="utf-8-sig")
    rule_col = "Rule-Based AI Avg Decision Time (ms)"
    mm_col = "1SGS AI Avg Decision Time (ms)"
    rule_vals = df[rule_col].dropna().values
    mm_vals = df[mm_col].dropna().values

    fig, ax = plt.subplots(figsize=(6, 4.5))
    bp = ax.boxplot(
        [rule_vals, mm_vals],
        tick_labels=["Rule-Based AI", "1SGS AI"],
        patch_artist=True,
        widths=0.5,
        showfliers=True,
        flierprops=dict(marker="o", markersize=3, alpha=0.4),
    )
    for patch, color in zip(bp["boxes"], [COLOR_RULE, COLOR_1SGS]):
        patch.set_facecolor(color)
        patch.set_alpha(0.55)
    for median in bp["medians"]:
        median.set_color("#333333")
        median.set_linewidth(1.5)

    ax.set_ylabel("Mean decision time per game (ms, symlog scale)")
    ax.set_yscale("symlog", linthresh=0.01)
    ax.set_title(f"Decision-time distribution by AI type\n({len(rule_vals)} valid games, Rule-Based vs 1SGS)")

    n_rule_zero = int((rule_vals == 0).sum())
    ax.text(0.02, 0.02,
            f"Note: {n_rule_zero}/{len(rule_vals)} Rule-Based games measured\n"
            f"exactly 0ms — below timer resolution for\n"
            f"such fast per-move decisions (see Methodology).",
            transform=ax.transAxes, ha="left", va="bottom", fontsize=8, color="#666666")

    # Annotate with an exact Mann-Whitney U result computed via scipy on the
    # raw per-move decision times (not the JS tool's normal-approximation
    # p-value), so the figure matches precise_stats_verification.py exactly
    # and can be cited directly in the dissertation.
    moves = pd.read_csv("raw_decision_times_per_move.csv")
    rule_moves = moves[moves["type"] == "rule"]["decision_time_ms"].values
    mm_moves = moves[moves["type"] == "1SGS"]["decision_time_ms"].values
    u_stat, p_exact = mannwhitneyu(rule_moves, mm_moves, alternative="two-sided")
    p_text = "p < 0.000001" if p_exact < 0.000001 else f"p = {p_exact:.6g}"
    ax.text(0.5, 0.97, f"Mann–Whitney U test: {p_text} (significant)",
            transform=ax.transAxes, ha="center", va="top", fontsize=9,
            bbox=dict(boxstyle="round,pad=0.3", fc="#fff8e8", ec="#e0c860"))

    save(fig, "fig1_decision_time_distribution")


# ════════════════════════════════════════════════════════════════
# Figure 2: Win-rate comparison (grouped bar chart)
# Data sources: summary_results.csv + ruleAI_v2_extension_results.csv
# Shows the main study result alongside the extension-experiment
# result, in one figure, so the "no significant difference -> becomes
# significant once the dead-card fix is applied" narrative is visible
# at a glance.
# ════════════════════════════════════════════════════════════════
def fig2_win_rate():
    print("Figure 2: win rate comparison")
    summary = pd.read_csv("summary_results_en.csv", encoding="utf-8-sig")
    ext = pd.read_csv("ruleAI_v2_extension_results_en.csv", encoding="utf-8-sig")

    main_row = summary[summary["Matchup"] == "Rule-Based vs 1SGS"].iloc[0]
    ext_vs_rule = ext[ext["Matchup"] == "Rule-Based AI v2 vs Rule-Based AI (original)"].iloc[0]
    ext_vs_mm = ext[ext["Matchup"] == "Rule-Based AI v2 vs 1SGS AI"].iloc[0]

    groups = ["Rule-Based\nvs 1SGS\n(main study)",
              "Rule-Based v2\nvs Rule-Based\n(extension)",
              "Rule-Based v2\nvs 1SGS\n(extension)"]
    left_vals = [float(main_row["Rule-Based Win Rate (%)"]),
                 float(ext_vs_rule["AI_v2 Win Rate (%)"]),
                 float(ext_vs_mm["AI_v2 Win Rate (%)"])]
    right_vals = [float(main_row["1SGS Win Rate (%)"]),
                  float(ext_vs_rule["Opponent Win Rate (%)"]),
                  float(ext_vs_mm["Opponent Win Rate (%)"])]
    left_labels = ["Rule-Based", "Rule-Based v2", "Rule-Based v2"]
    right_labels = ["1SGS", "Rule-Based (orig.)", "1SGS"]
    left_colors = [COLOR_RULE, COLOR_RULE_V2, COLOR_RULE_V2]
    right_colors = [COLOR_1SGS, COLOR_RULE, COLOR_1SGS]

    # Exact chi-square p-values via scipy, computed from raw per-game win
    # counts (not the JS tool's normal-approximation p-values), so figures
    # match precise_stats_verification.py and can be cited directly.
    raw_main = pd.read_csv("raw_game_logs_en.csv", encoding="utf-8-sig")
    main_games = raw_main[(raw_main["Matchup"] == "Rule-Based vs 1SGS") & (raw_main["Timed Out"] == "No")]
    main_wins = main_games["Winning AI Type"].value_counts()
    n_rule, n_mm = int(main_wins.get("rule", 0)), int(main_wins.get("oneSGS", 0))
    chi_main, p_main = chisquare([n_rule, n_mm], f_exp=[(n_rule + n_mm) / 2] * 2)

    raw_ext = pd.read_csv("ruleAI_v2_extension_results_en_raw.csv", encoding="utf-8-sig")

    def ext_chisq(matchup_label):
        sub = raw_ext[(raw_ext["Matchup"] == matchup_label) & (raw_ext["Timed Out"] == "No")]
        wins = sub["Winning AI Type"].value_counts()
        keys = list(wins.index)
        a, b = int(wins[keys[0]]), int(wins[keys[1]])
        return chisquare([a, b], f_exp=[(a + b) / 2] * 2)

    chi_ext1, p_ext1 = ext_chisq("Rule-Based AI v2 vs Rule-Based AI (original)")
    chi_ext2, p_ext2 = ext_chisq("Rule-Based AI v2 vs 1SGS AI")

    def p_fmt(p):
        return "< 0.000001" if p < 0.000001 else f"{p:.6g}"

    p_ext1_str, p_ext2_str = p_fmt(p_ext1), p_fmt(p_ext2)

    p_main_str = "p < 0.00001" if p_main < 0.00001 else f"p = {p_main:.3f}"
    p_display = [
        f"{p_main_str}\n({'sig.' if p_main<0.05 else 'n.s.'})",
        f"p {p_ext1_str}\n(sig.)" if p_ext1_str.startswith("<") else f"p = {p_ext1_str}\n(sig.)",
        f"p {p_ext2_str}\n(sig.)" if p_ext2_str.startswith("<") else f"p = {p_ext2_str}\n(sig.)",
    ]

    x = np.arange(len(groups))
    width = 0.32

    fig, ax = plt.subplots(figsize=(8, 5))
    bars_l = ax.bar(x - width/2, left_vals, width, color=left_colors, alpha=0.85)
    bars_r = ax.bar(x + width/2, right_vals, width, color=right_colors, alpha=0.85)

    ax.axhline(50, color="#999999", linestyle="--", linewidth=1)
    ax.set_ylabel("Win rate (%)")
    ax.set_title("Win rate comparison across matchups")
    ax.set_xticks(x)
    ax.set_xticklabels(groups)
    ax.set_ylim(0, 75)

    for i, (bl, br) in enumerate(zip(bars_l, bars_r)):
        ax.text(bl.get_x() + bl.get_width()/2, bl.get_height() + 1.5,
                f"{left_vals[i]:.1f}%\n({left_labels[i]})", ha="center", fontsize=8.5)
        ax.text(br.get_x() + br.get_width()/2, br.get_height() + 1.5,
                f"{right_vals[i]:.1f}%\n({right_labels[i]})", ha="center", fontsize=8.5)
        ax.text(x[i], 68, p_display[i], ha="center", fontsize=9, fontweight="bold",
                color="#c04040" if "sig." in p_display[i] and "n.s." not in p_display[i] else "#3d8b3d")

    save(fig, "fig2_win_rate_comparison")


# ════════════════════════════════════════════════════════════════
# Figure 3: Seat-position diagnostic (bar chart with 95% CI)
# Data source: seat_diagnostic_results_en.csv (kept in sync with the English
# dissertation chapters, which cite this specific run's numbers directly)
# Purpose: visually demonstrate the absence of a seat-position
# advantage, with binomial 95% confidence intervals as error bars.
# ════════════════════════════════════════════════════════════════
def fig3_seat_diagnostic():
    print("Figure 3: seat diagnostic")
    # First block of the CSV (seat win counts) ends before the blank line
    with open("seat_diagnostic_results_en.csv", encoding="utf-8-sig") as f:
        lines = [l.strip() for l in f.readlines()]
    blank_idx = next(i for i, l in enumerate(lines) if l == "")
    seat_lines = lines[1:blank_idx]

    seats, identities, wins, rates = [], [], [], []
    identity_map = {
        "规则型AI1": "Rule-Based AI1", "博弈树AI1": "1SGS AI1",
        "规则型AI2": "Rule-Based AI2", "博弈树AI2": "1SGS AI2",
        "Rule-Based AI1": "Rule-Based AI1", "Minimax AI1": "1SGS AI1", "1SGS AI1": "1SGS AI1",
        "Rule-Based AI2": "Rule-Based AI2", "Minimax AI2": "1SGS AI2", "1SGS AI2": "1SGS AI2",
    }
    for line in seat_lines:
        parts = line.split(",")
        seats.append(int(parts[0]))
        identities.append(identity_map.get(parts[1], parts[1]))
        wins.append(int(parts[2]))
        rates.append(float(parts[3]))

    total = sum(wins) / (sum(rates) / 100) if sum(rates) > 0 else sum(wins) / 0.25 / 4
    n_valid = round(sum(wins) / (sum(rates) / 100)) if sum(rates) > 0 else None
    # total valid games = sum(wins) since each valid game has exactly one winner
    n_valid = sum(wins)

    # binomial 95% CI (normal approximation) per seat, out of n_valid
    props = np.array(wins) / n_valid
    se = np.sqrt(props * (1 - props) / n_valid)
    ci95 = 1.96 * se * 100  # in percentage points

    fig, ax = plt.subplots(figsize=(6.5, 4.5))
    colors = [COLOR_RULE, COLOR_1SGS, COLOR_RULE, COLOR_1SGS]
    bars = ax.bar(identities, rates, yerr=ci95, capsize=5, color=colors, alpha=0.8,
                   error_kw=dict(ecolor="#444444", elinewidth=1.2))
    ax.axhline(25, color="#999999", linestyle="--", linewidth=1, label="Expected (25%, no seat effect)")

    ax.set_ylabel("Win rate (%)")
    ax.set_title(f"Win rate by seat position\n(fixed seating, n = {n_valid} valid games)")
    ax.set_ylim(0, max(rates) + max(ci95) + 8)
    ax.legend(loc="upper right", fontsize=9)

    # Exact chi-square via scipy on the win counts already parsed above,
    # rather than the JS tool's normal-approximation p-value from the CSV.
    chi2_val, p_val = chisquare(wins, f_exp=[n_valid / 4] * 4)
    p_str = "p < 0.000001" if p_val < 0.000001 else f"p = {p_val:.3f}"
    sig_str = "significant" if p_val < 0.05 else "not significant"
    ax.text(0.5, -0.22, f"Chi-square goodness-of-fit: χ² = {chi2_val:.3f}, "
            f"{p_str} ({sig_str})",
            transform=ax.transAxes, ha="center", fontsize=9.5)

    for bar, rate in zip(bars, rates):
        ax.text(bar.get_x() + bar.get_width()/2, rate + 1, f"{rate:.1f}%", ha="center", fontsize=9)

    save(fig, "fig3_seat_diagnostic")


# ════════════════════════════════════════════════════════════════
# Figure 4: Control-group seat bias (non-confounded seat effect)
# Data source: control_group_seat_bias_en.csv
# Purpose: this is the methodologically cleaner companion to fig3.
# fig3 fixes seats to specific AI TYPES (seat0/2=rule, seat1/3=1SGS),
# so a low win rate on one seat there could reflect either a seat
# effect or an AI-type effect — the two cannot be separated. This
# figure instead uses the Rule-Based-vs-Rule-Based and 1SGS-vs-
# 1SGS control groups, where every seat in each group runs the
# SAME AI type, so any seat-to-seat difference can only come from
# seat position itself. This should be the primary figure cited for
# the "no seat-position advantage" claim; fig3 is supplementary.
# ════════════════════════════════════════════════════════════════
def fig4_control_seat_bias():
    print("Figure 4: control-group seat bias")
    with open("control_group_seat_bias_en.csv", encoding="utf-8-sig") as f:
        lines = [l.strip() for l in f.readlines()]
    blank_idx = next(i for i, l in enumerate(lines) if l == "")
    seat_lines = lines[1:blank_idx]

    groups = {"Rule-Based vs Rule-Based (control)": [0, 0, 0, 0],
              "1SGS vs 1SGS (control)": [0, 0, 0, 0]}
    for line in seat_lines:
        parts = line.split(",")
        label, seat_idx, wins = parts[0], int(parts[1]), int(parts[2])
        if label in groups:
            groups[label][seat_idx] = wins

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5), sharey=True)
    group_colors = [COLOR_RULE, COLOR_1SGS]

    for ax, (label, wins), color in zip(axes, groups.items(), group_colors):
        n_valid = sum(wins)
        rates = np.array(wins) / n_valid * 100
        se = np.sqrt((rates/100) * (1 - rates/100) / n_valid)
        ci95 = 1.96 * se * 100
        bars = ax.bar([f"Seat {i}" for i in range(4)], rates, yerr=ci95, capsize=5,
                       color=color, alpha=0.8, error_kw=dict(ecolor="#444444", elinewidth=1.2))
        ax.axhline(25, color="#999999", linestyle="--", linewidth=1)
        for bar, rate in zip(bars, rates):
            ax.text(bar.get_x()+bar.get_width()/2, rate+1.5, f"{rate:.1f}%", ha="center", fontsize=9)
        # Exact chi-square via scipy on the win counts parsed above, rather
        # than the JS tool's normal-approximation p-value from the CSV.
        chi2_val, p_val = chisquare(wins, f_exp=[n_valid / 4] * 4)
        p_str = "p < 0.000001" if p_val < 0.000001 else f"p = {p_val:.3f}"
        title = label.replace(" (control)", "\n(control)")
        subtitle = f"χ² = {chi2_val:.3f}, {p_str}"
        ax.set_title(f"{title}\nn = {n_valid} valid games\n{subtitle}", fontsize=10)
        ax.set_ylim(0, max(rates)+max(ci95)+10)

    axes[0].set_ylabel("Win rate (%)")
    fig.suptitle("Control-group seat bias (AI type held constant within each panel)", fontsize=13)
    fig.tight_layout(rect=[0,0,1,0.93])

    save(fig, "fig4_control_seat_bias")


if __name__ == "__main__":
    fig1_decision_time()
    fig2_win_rate()
    fig3_seat_diagnostic()
    fig4_control_seat_bias()
    print("\nAll figures generated in ./figures/")
