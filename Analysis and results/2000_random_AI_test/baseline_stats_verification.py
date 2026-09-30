"""
baseline_stats_verification.py

Random-baseline control-group statistical verification and visualization.
Reads the raw per-game CSV exported from simulation_baseline_en.html and
computes exact, citable statistics using scipy/statsmodels rather than the
JavaScript approximations built into the simulator, following the same
principle already applied to precise_stats_verification.py for the main
Rule-Based vs 1SGS experiment.

Methods used (and why):
  1. Exact two-sided binomial test (scipy.stats.binomtest) against p0=0.5
     for each strategic AI's win rate against Random. This is the primary
     test: it directly asks "is this win rate significantly different from
     chance?" without relying on a normal/chi-square approximation.
  2. Wilson score 95% confidence interval (statsmodels) for each win rate,
     for reporting as "92.0% (95% CI: xx.x-xx.x%)" in the dissertation text.
  3. Chi-square goodness-of-fit test (scipy.stats.chisquare) as a cross-check
     against the chi2/p values already printed by the JS simulator, to
     confirm the front-end approximation was reliable.
  4. Chi-square test of homogeneity (scipy.stats.chi2_contingency) across
     the three matchups' completion vs. timed-out counts, to test whether
     completion rate differs significantly between the mixed matchups
     (Rule/1SGS vs Random) and the pure-random control.

Outputs:
  - Printed results (safe to copy into the dissertation / a results table)
  - baseline_stats_report.txt (same content, saved to disk)
  - fig_baseline_winrate.png   (Figure A: win-rate comparison with 95% CI)
  - fig_baseline_completion.png (Figure B: completion-rate comparison)
"""

import pandas as pd
import numpy as np
from scipy import stats
from statsmodels.stats.proportion import proportion_confint
import matplotlib.pyplot as plt

RAW_CSV = "baseline_raw_game_logs_en.csv"
OUT_REPORT = "baseline_stats_report.txt"
FIG_WINRATE = "fig_baseline_winrate.png"
FIG_COMPLETION = "fig_baseline_completion.png"

# matchup label -> (strategic AI type key, strategic AI display label)
# "Random vs Random" has no strategic side; it is analysed only for
# completion rate (a win-rate/binomial test is meaningless when both
# sides are the same, no-strategy AI).
MATCHUPS = [
    ("Rule-Based vs Random (baseline)", "rule", "Rule-Based"),
    ("1SGS (Greedy) vs Random (baseline)", "oneSGS", "1SGS (Greedy)"),
    ("Random vs Random (sanity control)", None, "Random"),
]


def analyse(df):
    lines = []
    winrate_results = []   # for Figure A
    completion_results = []  # for Figure B
    contingency_rows = []  # for the homogeneity test

    lines.append("=" * 78)
    lines.append("RANDOM BASELINE CONTROL GROUP -- EXACT STATISTICAL VERIFICATION")
    lines.append("=" * 78)

    for label, ai_key, ai_label in MATCHUPS:
        sub = df[df["Matchup"] == label]
        total = len(sub)
        valid = sub[sub["Timed Out"] == "No"]
        n_valid = len(valid)
        timed_out = total - n_valid
        completion_rate = n_valid / total * 100

        contingency_rows.append([n_valid, timed_out])
        completion_results.append((ai_label if ai_key else "Random", label, completion_rate, n_valid, total))

        lines.append("")
        lines.append("-" * 78)
        lines.append(f"Matchup: {label}")
        lines.append(f"  Total games: {total}   Valid (completed) games: {n_valid}   "
                      f"Timed out: {timed_out}")
        lines.append(f"  Completion rate: {completion_rate:.1f}%")

        if ai_key is None:
            # Pure random-vs-random control: no meaningful "win rate" test
            # (all winners are the same AI type by construction). Report
            # completion rate only.
            lines.append("  No win-rate test performed: both sides use the identical "
                          "no-strategy Random AI, so a win-rate comparison is not "
                          "meaningful here. This matchup is reported only for its "
                          "completion rate, as a sanity check that games between two "
                          "non-strategic players rarely resolve within the turn cap.")
            continue

        wins_ai = int((valid["Winning AI Type"] == ai_key).sum())
        wins_random = int((valid["Winning AI Type"] == "random").sum())
        win_rate_ai = wins_ai / n_valid * 100
        win_rate_random = wins_random / n_valid * 100

        # 1. Exact two-sided binomial test against chance (p0 = 0.5)
        binom = stats.binomtest(wins_ai, n_valid, 0.5, alternative="two-sided")

        # 2. Wilson score 95% CI for the AI's win rate
        ci_low, ci_high = proportion_confint(wins_ai, n_valid, alpha=0.05, method="wilson")

        # 3. Chi-square goodness-of-fit cross-check (2 categories: AI wins vs Random wins)
        chi2, p_chi2 = stats.chisquare([wins_ai, wins_random])

        winrate_results.append({
            "label": ai_label, "n": n_valid,
            "win_rate_ai": win_rate_ai, "win_rate_random": win_rate_random,
            "ci_low": ci_low * 100, "ci_high": ci_high * 100,
        })

        lines.append(f"  {ai_label} wins: {wins_ai}   Random wins: {wins_random}   "
                      f"(of {n_valid} completed games)")
        lines.append(f"  {ai_label} win rate: {win_rate_ai:.1f}%   "
                      f"(95% Wilson CI: {ci_low*100:.1f}%-{ci_high*100:.1f}%)")
        lines.append(f"  Exact two-sided binomial test vs. chance (p0=0.5): "
                      f"p = {binom.pvalue:.3e}"
                      + (" (significantly different from chance)" if binom.pvalue < 0.05
                         else " (not significantly different from chance)"))
        lines.append(f"  Chi-square goodness-of-fit cross-check: "
                      f"chi2 = {chi2:.4f}, p = {p_chi2:.3e}")

    # 4. Chi-square test of homogeneity across the three matchups' completion rates
    lines.append("")
    lines.append("-" * 78)
    lines.append("Completion-rate homogeneity across the three matchups "
                  "(chi-square test of homogeneity, contingency table = "
                  "[completed, timed-out] x 3 matchups):")
    table = np.array(contingency_rows)  # shape (3, 2): rows=matchups, cols=[completed, timed_out]
    chi2_h, p_h, dof_h, expected_h = stats.chi2_contingency(table)
    lines.append(f"  chi2 = {chi2_h:.4f}, df = {dof_h}, p = {p_h:.3e}"
                 + (" (completion rate differs significantly across matchups)"
                    if p_h < 0.05 else " (no significant difference in completion rate)"))

    lines.append("")
    lines.append("=" * 78)
    report = "\n".join(lines)
    print(report)
    with open(OUT_REPORT, "w", encoding="utf-8") as f:
        f.write(report + "\n")

    return winrate_results, completion_results


def plot_winrate(winrate_results):
    """Figure A: win-rate comparison, AI vs Random, with 95% Wilson CI error
    bars on the AI bar, and a dashed reference line at 50% (chance level)."""
    labels = [r["label"] for r in winrate_results]
    ai_rates = [r["win_rate_ai"] for r in winrate_results]
    random_rates = [r["win_rate_random"] for r in winrate_results]
    ci_err = [
        [r["win_rate_ai"] - r["ci_low"] for r in winrate_results],
        [r["ci_high"] - r["win_rate_ai"] for r in winrate_results],
    ]

    x = np.arange(len(labels))
    width = 0.35

    fig, ax = plt.subplots(figsize=(7, 5))
    ax.bar(x - width/2, ai_rates, width, yerr=ci_err, capsize=5,
           color="#3a9d5f", label="Strategic AI win rate (95% CI)")
    ax.bar(x + width/2, random_rates, width,
           color="#c9a24a", label="Random AI win rate")
    ax.axhline(50, color="#c04040", linestyle="--", linewidth=1.2, label="Chance level (50%)")

    ax.set_ylabel("Win rate (%)")
    ax.set_title("Win rate against Random baseline, by AI type")
    ax.set_xticks(x)
    ax.set_xticklabels([f"{l} vs Random" for l in labels])
    ax.set_ylim(0, 105)
    ax.legend(loc="upper right", fontsize=9)
    for i, v in enumerate(ai_rates):
        ax.text(x[i] - width/2, v + 2, f"{v:.1f}%", ha="center", fontsize=9, fontweight="bold")
    for i, v in enumerate(random_rates):
        ax.text(x[i] + width/2, v + 2, f"{v:.1f}%", ha="center", fontsize=9)

    fig.tight_layout()
    fig.savefig(FIG_WINRATE, dpi=200)
    plt.close(fig)


def plot_completion(completion_results):
    """Figure B: completion-rate comparison across all three matchups."""
    labels = ["Rule-Based\nvs Random", "1SGS\nvs Random", "Random\nvs Random"]
    rates = [r[2] for r in completion_results]
    colors = ["#3a9d5f", "#4a7fc9", "#c9a24a"]

    fig, ax = plt.subplots(figsize=(6, 5))
    bars = ax.bar(labels, rates, color=colors)
    ax.set_ylabel("Completion rate (%)")
    ax.set_title("Game completion rate by matchup")
    ax.set_ylim(0, max(rates) + 15)
    for bar, v in zip(bars, rates):
        ax.text(bar.get_x() + bar.get_width()/2, v + 1.5, f"{v:.1f}%",
                ha="center", fontsize=9, fontweight="bold")

    fig.tight_layout()
    fig.savefig(FIG_COMPLETION, dpi=200)
    plt.close(fig)


def main():
    df = pd.read_csv(RAW_CSV)
    winrate_results, completion_results = analyse(df)
    plot_winrate(winrate_results)
    plot_completion(completion_results)
    print(f"\nSaved: {OUT_REPORT}, {FIG_WINRATE}, {FIG_COMPLETION}")


if __name__ == "__main__":
    main()
