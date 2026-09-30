"""
seat_bias_confirmatory_analysis.py  (pooled version)
------------------------------------------------------
Analyses several independent, equally-designed large runs (e.g. three
reruns of 20,000 attempted games each) by pooling their raw win counts
into one combined test, rather than combining p-values (Fisher's
method). Pooling counts directly is the right move here because the
runs are the same experimental design repeated for sample size, not
independent studies being synthesised -- summing three 20,000-game
runs is mathematically identical to one 60,000-game run.

Each individual run is still reported (raw counts + its own chi2/p),
so you can eyeball whether the seat-1/seat-2-elevated pattern found in
the first confirmatory run repeats run to run. But the number that
actually gets reported as the result is the pooled one.

Usage:
    python3 seat_bias_confirmatory_analysis.py

Expects any number of files (1 or more) matching these patterns in the
same directory:
    seat_diagnostic_results_en*.csv       -- mixed diagnostic reruns
    control_group_seat_bias_en*.csv       -- AI-type-controlled reruns

Output:
    seat_bias_confirmatory_summary.csv
    fig_seat_bias_confirmatory.png   (pooled result only)
"""

import glob
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.stats import chisquare, chi2 as chi2dist, ncx2

MIXED_PATTERN = "seat_diagnostic_results_en*.csv"
CONTROL_PATTERN = "control_group_seat_bias_en*.csv"

OUTPUT_ROWS = []


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


def load_mixed_diagnostic_files():
    files = sorted(glob.glob(MIXED_PATTERN))
    runs = []
    for f in files:
        df = pd.read_csv(f, encoding="utf-8-sig", nrows=4)
        wins = df["Wins"].tolist()
        labels = df["Identity"].tolist() if "Identity" in df.columns else [f"Seat {i}" for i in range(4)]
        runs.append({"file": f, "wins": wins, "labels": labels})
    return runs


def load_control_group_files():
    files = sorted(glob.glob(CONTROL_PATTERN))
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
    return runs


def analyse_and_pool(name, per_run_wins, labels):
    """Print each individual run (for a stability sanity-check), then
    pool the raw counts into one final test -- this is what gets
    reported."""
    print("=" * 78)
    print(name)
    print("=" * 78)

    pooled = np.zeros(len(per_run_wins[0]), dtype=int)
    for i, wins in enumerate(per_run_wins, start=1):
        wins = np.array(wins)
        n = int(wins.sum())
        exp = [n / len(wins)] * len(wins)
        chi2_val, p = chisquare(wins, f_exp=exp)
        pct = wins / n * 100
        print(f"  Run {i}: n={n}, wins={wins.tolist()}, win%={[f'{x:.1f}%' for x in pct]}, "
              f"chi2={chi2_val:.3f}, p={p:.5f}")
        pooled += wins
        OUTPUT_ROWS.append([name, f"run_{i}", n, ";".join(map(str, wins.tolist())),
                             f"{chi2_val:.4f}", f"{p:.6f}", "", ""])

    n_pool = int(pooled.sum())
    exp_pool = [n_pool / len(pooled)] * len(pooled)
    chi2_pool, p_pool = chisquare(pooled, f_exp=exp_pool)
    w = cohens_w(pooled)
    power = achieved_power(n_pool, w, df=len(pooled) - 1)
    pct_pool = pooled / n_pool * 100

    print(f"  -> POOLED across {len(per_run_wins)} run(s): n={n_pool}, wins={pooled.tolist()}")
    print(f"     win% = {[f'{x:.2f}%' for x in pct_pool]}")
    print(f"     chi2={chi2_pool:.4f}, df={len(pooled)-1}, p={p_pool:.6f}")
    print(f"     effect size (Cohen's w)={w:.4f}, achieved power at this n={power:.3f}")
    verdict = "SIGNIFICANT" if p_pool < 0.05 else "not significant"
    print(f"     -> {verdict} at alpha=0.05\n")

    OUTPUT_ROWS.append([name, "POOLED", n_pool, ";".join(map(str, pooled.tolist())),
                         f"{chi2_pool:.4f}", f"{p_pool:.6f}", f"{w:.4f}", f"{power:.4f}"])

    return {"name": name, "n": n_pool, "wins": pooled, "labels": labels, "pct": pct_pool,
            "chi2": chi2_pool, "p": p_pool, "w": w, "power": power,
            "n_runs": len(per_run_wins)}


def plot_pooled(results):
    """Only the pooled/final result gets plotted -- individual runs are
    in the CSV for reference, not worth a figure each."""
    fig, axes = plt.subplots(1, len(results), figsize=(6.5 * len(results), 5.2), sharey=True)
    if len(results) == 1:
        axes = [axes]

    for ax, res in zip(axes, results):
        n = res["n"]
        pct = res["pct"]
        se = np.sqrt(pct * (100 - pct) / n)
        seat_labels = [str(l) for l in res["labels"]]

        color = "#c0504d" if res["p"] < 0.05 else "#4f81bd"
        bars = ax.bar(seat_labels, pct, yerr=1.96 * se, capsize=4, color=color, zorder=3)
        expected = 100 / len(pct)
        ax.axhline(expected, color="grey", linestyle="--", linewidth=1, zorder=2)

        title = (f"{res['name']}\n"
                 f"n={n:,} pooled across {res['n_runs']} run(s), chi2={res['chi2']:.3f}, p={res['p']:.4f}\n"
                 f"effect size w={res['w']:.3f}, achieved power={res['power']:.1%}")
        ax.set_title(title, fontsize=10)
        ax.set_ylabel("Win rate (%)")
        ax.set_ylim(0, max(pct) + 6)
        for bar, p_ in zip(bars, pct):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                     f"{p_:.1f}%", ha="center", va="bottom", fontsize=9)
        plt.setp(ax.get_xticklabels(), rotation=15, ha="right", fontsize=8.5)

    fig.suptitle("Seat-position confirmatory test (pooled across all available reruns)\n"
                 "dashed line = expected win rate under no seat effect; red = significant at 0.05")
    plt.tight_layout()
    plt.savefig("fig_seat_bias_confirmatory.png", dpi=300)
    plt.close()
    print("Saved fig_seat_bias_confirmatory.png")


def main():
    all_results = []

    mixed_runs = load_mixed_diagnostic_files()
    if mixed_runs:
        wins_list = [r["wins"] for r in mixed_runs]
        labels = mixed_runs[0]["labels"]
        res = analyse_and_pool("Mixed diagnostic (four-seat overall)", wins_list, labels)
        all_results.append(res)
    else:
        print(f"No files matched {MIXED_PATTERN}, skipping mixed diagnostic.")

    control_runs = load_control_group_files()
    if control_runs:
        matchup_names = list(control_runs[0]["wins_by_matchup"].keys())
        for matchup in matchup_names:
            wins_list = [r["wins_by_matchup"][matchup] for r in control_runs]
            res = analyse_and_pool(f"Control group - {matchup}", wins_list,
                                    [f"Seat {i}" for i in range(4)])
            all_results.append(res)
    else:
        print(f"No files matched {CONTROL_PATTERN}, skipping control group.")

    if not all_results:
        print("Nothing to analyse -- check that the CSV files are in this directory.")
        return

    out = pd.DataFrame(OUTPUT_ROWS, columns=["Test", "Run", "N games", "Wins by seat",
                                              "chi2", "p-value", "Effect size (Cohen's w)",
                                              "Achieved power"])
    out.to_csv("seat_bias_confirmatory_summary.csv", index=False)
    print("Summary written to seat_bias_confirmatory_summary.csv")

    plot_pooled(all_results)


if __name__ == "__main__":
    main()
