"""
precise_stats_verification.py
------------------------------
Independently re-runs every Mann-Whitney U test and chi-square
goodness-of-fit test used in the dissertation, using scipy.stats
instead of the hand-written normal-approximation functions inside
simulation.html. This exists specifically to replace the tool's
approximated p-values with exact values computed by real statistical
software, per supervisor feedback.

Reads directly from the raw CSV files already produced by the
simulation tool. Produces one console report and one CSV summary.

Usage:
    python3 precise_stats_verification.py

Requires the following files to be present in the same directory:
    raw_game_logs_en.csv
    raw_decision_times_per_move.csv
    decision_times_by_type_en.csv
    seat_diagnostic_results_en.csv
    control_group_seat_bias_en.csv
    ruleAI_v2_extension_results_en_raw.csv

Output:
    precision_verification.csv
"""

import pandas as pd
from scipy.stats import mannwhitneyu, chisquare
from collections import Counter
import csv

results = []  # each entry: [test_name, exact_statistic, exact_p]


def log(name, stat_label, stat_val, p_val):
    print(f"{name}")
    print(f"  {stat_label} = {stat_val:.4f}   p = {p_val:.6e}\n")
    results.append([name, f"{stat_val:.4f}", f"{p_val:.6e}"])


# ════════════════════════════════════════════════════════════════
# 1. Main experiment: Rule-Based vs 1SGS, win rate
#    (chi-square goodness-of-fit)
# ════════════════════════════════════════════════════════════════
print("=" * 70)
print("1. MAIN EXPERIMENT — WIN RATE (chi-square goodness-of-fit)")
print("=" * 70)

df_raw = pd.read_csv("raw_game_logs_en.csv", encoding="utf-8-sig")
main = df_raw[df_raw["Matchup"] == "Rule-Based vs 1SGS"]
valid_main = main[main["Timed Out"] == "No"]
wins = Counter(valid_main["Winning AI Type"])
n_rule, n_mm = wins["rule"], wins["oneSGS"]
chi2, p = chisquare([n_rule, n_mm], f_exp=[(n_rule + n_mm) / 2] * 2)
log("Rule-Based vs 1SGS win rate", "chi2", chi2, p)


# ════════════════════════════════════════════════════════════════
# 2. Decision time, per-move (Mann-Whitney U)
#    This is the headline statistic cited in Chapter 5 (z=-18.07 in
#    the tool's approximation). Raw per-move times were re-exported
#    to raw_decision_times_per_move.csv specifically for this check,
#    since the original per-move array was never saved to file.
# ════════════════════════════════════════════════════════════════
print("=" * 70)
print("2. DECISION TIME — per move (Mann-Whitney U)")
print("=" * 70)

df_moves = pd.read_csv("raw_decision_times_per_move.csv")
rule_moves = df_moves[df_moves["type"] == "rule"]["decision_time_ms"].values
mm_moves = df_moves[df_moves["type"] == "1SGS"]["decision_time_ms"].values
u_stat, p = mannwhitneyu(rule_moves, mm_moves, alternative="two-sided")
log(f"Decision time per move (N_rule={len(rule_moves)}, N_1SGS={len(mm_moves)})",
    "U", u_stat, p)


# ════════════════════════════════════════════════════════════════
# 3. Decision time, per game average (robustness check against
#    within-game clustering of moves)
# ════════════════════════════════════════════════════════════════
print("=" * 70)
print("3. DECISION TIME — per game average, robustness check")
print("=" * 70)

df_games = pd.read_csv("decision_times_by_type_en.csv", encoding="utf-8-sig")
rule_col = "Rule-Based AI Avg Decision Time (ms)"
mm_col = "1SGS AI Avg Decision Time (ms)"
rule_games = df_games[rule_col].dropna().values
mm_games = df_games[mm_col].dropna().values
u_stat, p = mannwhitneyu(rule_games, mm_games, alternative="two-sided")
log(f"Decision time per game (N_rule={len(rule_games)}, N_1SGS={len(mm_games)})",
    "U", u_stat, p)


# ════════════════════════════════════════════════════════════════
# 4. Seat diagnostic: four-seat win rate (chi-square goodness-of-fit)
# ════════════════════════════════════════════════════════════════
print("=" * 70)
print("4. SEAT DIAGNOSTIC — four-seat win rate (chi-square)")
print("=" * 70)

df_seat = pd.read_csv("seat_diagnostic_results_en.csv", encoding="utf-8-sig", nrows=4)
seat_wins = df_seat["Wins"].tolist()
chi2, p = chisquare(seat_wins, f_exp=[sum(seat_wins) / 4] * 4)
log("Four-seat overall goodness-of-fit", "chi2", chi2, p)

chi2, p = chisquare([seat_wins[0], seat_wins[2]], f_exp=[(seat_wins[0] + seat_wins[2]) / 2] * 2)
log("Rule-Based AI1 (seat0) vs Rule-Based AI2 (seat2)", "chi2", chi2, p)

chi2, p = chisquare([seat_wins[1], seat_wins[3]], f_exp=[(seat_wins[1] + seat_wins[3]) / 2] * 2)
log("1SGS AI1 (seat1) vs 1SGS AI2 (seat3)", "chi2", chi2, p)


# ════════════════════════════════════════════════════════════════
# 4.5. Control-group seat bias (non-confounded version): win rate by
#      seat within the Rule-Based vs Rule-Based and 1SGS vs 1SGS
#      control groups, where every seat runs the SAME AI type. Unlike
#      section 4 above (which mixes AI type with seat, so a low-win
#      seat could reflect either factor), this isolates seat position
#      cleanly since AI type is held constant within each group.
# ════════════════════════════════════════════════════════════════
print("=" * 70)
print("4.5. CONTROL-GROUP SEAT BIAS — non-confounded seat effect (chi-square)")
print("=" * 70)

with open("control_group_seat_bias_en.csv", encoding="utf-8-sig") as f:
    lines = [l.strip() for l in f.readlines()]
blank_idx = next(i for i, l in enumerate(lines) if l == "")
seat_lines = lines[1:blank_idx]

control_wins = {"Rule-Based vs Rule-Based (control)": [0, 0, 0, 0],
                "1SGS vs 1SGS (control)": [0, 0, 0, 0]}
for line in seat_lines:
    parts = line.split(",")
    matchup_label, seat_idx, wins = parts[0], int(parts[1]), int(parts[2])
    if matchup_label in control_wins:
        control_wins[matchup_label][seat_idx] = wins

for label, wins in control_wins.items():
    chi2, p = chisquare(wins, f_exp=[sum(wins) / 4] * 4)
    log(f"Control seat bias: {label}", "chi2", chi2, p)


# ════════════════════════════════════════════════════════════════
# 5. Extension experiment: ruleAI_v2 win rate (chi-square)
# ════════════════════════════════════════════════════════════════
print("=" * 70)
print("5. EXTENSION EXPERIMENT — ruleAI_v2 win rate (chi-square)")
print("=" * 70)

df_ext = pd.read_csv("ruleAI_v2_extension_results_en_raw.csv", encoding="utf-8-sig")
for matchup in ["Rule-Based AI v2 vs Rule-Based AI (original)", "Rule-Based AI v2 vs 1SGS AI"]:
    sub = df_ext[df_ext["Matchup"] == matchup]
    valid = sub[sub["Timed Out"] == "No"]
    wins = Counter(valid["Winning AI Type"])
    keys = list(wins.keys())
    n1, n2 = wins[keys[0]], wins[keys[1]]
    chi2, p = chisquare([n1, n2], f_exp=[(n1 + n2) / 2] * 2)
    log(matchup, "chi2", chi2, p)


# ════════════════════════════════════════════════════════════════
# 6. Cross-matchup pace consistency: turns and absorb/evolve count
#    (Mann-Whitney U, pairwise across the three matchup types)
# ════════════════════════════════════════════════════════════════
print("=" * 70)
print("6. PACE CONSISTENCY — turns and absorb/evolve count (Mann-Whitney U)")
print("=" * 70)

matchup_labels = {
    "rule_vs_1SGS": "Rule-Based vs 1SGS",
    "rule_vs_rule": "Rule-Based vs Rule-Based (control)",
    "1SGS_vs_1SGS": "1SGS vs 1SGS (control)",
}
data = {}
for key, label in matchup_labels.items():
    sub = df_raw[df_raw["Matchup"] == label]
    data[key] = sub[sub["Timed Out"] == "No"]

pairs = [("rule_vs_1SGS", "rule_vs_rule"),
         ("rule_vs_1SGS", "1SGS_vs_1SGS"),
         ("rule_vs_rule", "1SGS_vs_1SGS")]

for k1, k2 in pairs:
    u_stat, p = mannwhitneyu(data[k1]["Total Turns"], data[k2]["Total Turns"], alternative="two-sided")
    log(f"Turns: {k1} vs {k2}", "U", u_stat, p)

for k1, k2 in pairs:
    u_stat, p = mannwhitneyu(data[k1]["Absorption/Evolution Count"], data[k2]["Absorption/Evolution Count"],
                              alternative="two-sided")
    log(f"AbsorbEvo: {k1} vs {k2}", "U", u_stat, p)


# ════════════════════════════════════════════════════════════════
# Write summary CSV
# ════════════════════════════════════════════════════════════════
with open("precision_verification.csv", "w", newline="", encoding="utf-8-sig") as f:
    writer = csv.writer(f)
    writer.writerow(["Test", "Exact statistic (scipy)", "Exact p-value (scipy)"])
    writer.writerows(results)

print("=" * 70)
print(f"Done. {len(results)} tests verified. Summary written to precision_verification.csv")
print("=" * 70)
