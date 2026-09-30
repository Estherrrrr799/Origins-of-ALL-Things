# Origins of All Things

## Project Overview

Origins of All Things is a four-player imperfect-information card game project, comprising an interactive game prototype, AI auto-play tools, and the accompanying experimental data, statistical analysis scripts, and result figures.

This document explains the purpose of each folder in the OneDrive directory, how to run the game, and how to read and reproduce the experimental materials.

## Folder Structure

```text
Origins of All Things/
├── README.md
├── Main game/
│   ├── card-game_en.html
│   ├── simulation_en.html
│   └── simulation_baseline_en.html
└── Analysis and results/
    ├── 2000_random_AI_test/
    ├── 20000×1test/
    ├── 2000data/
    ├── 800-round_upper_limit_test/
    ├── data of seat bias/
    └── package/
```

`Main game` holds the game and simulation pages; `Analysis and results` holds the experimental data, analysis code, and output results. File contents are kept as originally produced; only the structure above is used to organise them.

**Note: the data in `package/` belongs to a previously abandoned batch of experiments. It is retained only as a record of the working process, and is not used for the current experimental conclusions, data aggregation, or result reproduction.**

## 1. Game and Experiment Entry Points

`Main game/` contains three independent HTML pages:

| File | Purpose |
| --- | --- |
| `card-game_en.html` | Interactive game: one human player against three AI opponents, with a choice of Rule-Based, Rule-Based v2, or 1SGS strategy |
| `simulation_en.html` | Main experiment platform: batch comparison between Rule-Based and 1SGS, together with same-type control groups, seat diagnostics, and the v2 extension experiments |
| `simulation_baseline_en.html` | Random-baseline experiment: compares Rule-Based, 1SGS, and Random AI, and provides a fully random control group |

### How to Run

1. Download the required HTML file from OneDrive.
2. Open it locally in a browser.
3. On the game page, choose an AI strategy to start a match; on the experiment pages, set the number of games and run the experiment.
4. Once the experiment finishes, use the export button on the page to save the CSV data.

The pages load React, ReactDOM, and Babel from a CDN, so a network connection is required. The entry point is the downloaded local HTML file itself.

To serve it locally instead, run the following from inside the downloaded `Origins of All Things` folder:

```bash
python -m http.server 8000
```

Then open in a browser:

```text
http://localhost:8000/Main%20game/card-game_en.html
http://localhost:8000/Main%20game/simulation_en.html
http://localhost:8000/Main%20game/simulation_baseline_en.html
```

## 2. Game Rules and AI Strategy Overview

### Game Rules

- Four players take part, each starting with 9 cards.
- The deck contains 7 species, each with 3 variants, and 4 copies of each variant, for a total of 84 cards.
- The 48 cards remaining after dealing form the draw pile.
- Three cards of the same variant within a species form an Evolution set, for example `1 + 1 + 1`.
- Three cards of different variants within a species form an Absorption set, for example `1 + 2 + 3`.
- Players build these combinations by playing cards, drawing cards, and making use of the most recently played card.
- The win condition is an empty hand together with exactly three completed sets.

### AI Strategies

| Strategy | Implementation |
| --- | --- |
| Rule-Based AI | Decides absorption, discarding, and play according to preset priorities |
| Rule-Based AI v2 | Adds dead-group cleanup to the ordinary discard flow of the original rule-based strategy, for example splitting an unformable `1 + 2 + 2` into `1 + 2` |
| 1SGS / Greedy AI | Enumerates the current candidate actions and selects one by heuristic scoring, without expanding an opponent-response layer |
| Random AI | When an executable absorption opportunity exists, randomly selects among the legal pairings and discards; otherwise plays a random card |

In the code, `1SGS` specifically refers to a one-ply greedy heuristic search. Random AI also retains the priority handling of absorption opportunities, and does not sample uniformly across every legal action without condition.

## 3. Navigating the Experimental Materials

### `20000×1test/`: Main Experiment and v2 Extension Experiment

Holds the experimental materials for each matchup configuration at 20,000 games.

**The main experiment includes:**

- Rule-Based vs 1SGS: two Rule-Based AIs against two 1SGS AIs;
- Rule-Based vs Rule-Based: four original Rule-Based AIs, a same-type control group;
- 1SGS vs 1SGS: four 1SGS AIs, a same-type control group.

**The v2 extension experiment includes:**

- Rule-Based v2 vs Rule-Based: two v2 AIs against two original Rule-Based AIs;
- Rule-Based v2 vs 1SGS: two v2 AIs against two 1SGS AIs;
- Rule-Based v2 vs Rule-Based v2: four v2 AIs, a same-type control group.

The directory also holds per-game records, decision-time data, result summaries, statistical verification scripts, figures, and Excel analysis reports.

Main analysis scripts:

| Script | Purpose |
| --- | --- |
| `analyze_main_experiment.py` | Analyses win rate, completion rate, decision time, and turn count for the main experiment |
| `analyze_ruleAI_v2_completion_deadlock.py` | Compares completion rate and turn count between the v2 and baseline configurations |
| `precise_stats_verification.py` | Uses SciPy to re-verify the relevant statistical tests |
| `generate_figures.py` | Generates figures from the experimental data |

The main results are located in `figures/`, `main resule/`, and `rule_v2_result/`. `main resule` is the existing folder name.

### `2000data/`: 2,000-Game Experimental Materials

Holds the experimental data, together with the corresponding statistical verification and plotting files, for the smaller-scale runs.

This directory corresponds to a batch independent from `20000×1test/`. Even where file names are identical, they should be read and analysed separately, to avoid mixing statistics across batches.

### `2000_random_AI_test/`: Random-Baseline Experiment

Holds the experimental data and analysis results for the following three configurations:

- Rule-Based vs Random;
- 1SGS vs Random;
- Random vs Random.

Here, `baseline_stats_verification.py` analyses the raw records and produces the statistical report, the win-rate figure, and the completion-rate figure.

### `800-round_upper_limit_test/`: Turn-Cap and End-Structure Verification

Used to analyse the role of the 800-turn cap in the automated simulation, covering:

- the turn-count distribution of completed games;
- the point at which the draw pile is exhausted;
- the point of the last real decision in games that did not complete;
- the number of idle turns and the remaining hand sizes at the end.

Main files:

- `engine_turn_structure_check.js`: generates simulation data with added structural-monitoring fields.
- `analyze_turn_structure.py`: analyses that data and produces the tables and figures.
- `data/`: raw data.
- `output/`: analysis results.

### `data of seat bias/`: Seat-Bias Analysis

Contains two independent analyses together with an aggregation tool:

| Subdirectory or script | Purpose |
| --- | --- |
| `20000×3_random_AI_seat_test/` | Seat-distribution analysis for three batches of pure Random AI experiments |
| `20000×3seat_test_final/` | Seat-bias analysis for three batches covering the mixed-diagnostic and same-type control groups |
| `merge_seat_bias_cross_group.py` | Reads the tables produced by the analyses above and generates a cross-group summary |
| `merged_output/` | Cross-group summary tables and figures |

The `output/run_metadata.json` file inside each analysis directory records that run's input files and environment, for traceability.

### `package/`: Historical Record of an Abandoned Batch

This directory retains a previously abandoned data batch and its associated scripts, kept solely as a record of the working process.

**Do not merge this data with the other experiment directories, and do not use it as a basis for current results.**

## 4. Suggested Reading Order

1. Look at `Main game/card-game_en.html` to get a feel for the game mechanics and interaction.
2. Look at `Main game/simulation_en.html` to understand the experiment configuration and metrics.
3. Read the main experiment and extension experiment results in `Analysis and results/20000×1test/`.
4. Read `2000_random_AI_test/` to see how the strategies perform relative to the random baseline.
5. Read `data of seat bias/` and `800-round_upper_limit_test/` for the supplementary verification of seat effects and end-of-game mechanics.
6. Consult the raw CSVs and their corresponding analysis scripts as needed.

## 5. Reproducing the Existing Experimental Data

Download the folder to be analysed in full to a local machine, keeping the internal file names and relative positions unchanged.

### Environment Dependencies

The Python analysis scripts rely on the following third-party libraries:

```bash
python -m pip install numpy pandas scipy statsmodels matplotlib openpyxl pillow jinja2
```

Regenerating the turn-structure experiment data additionally requires Node.js.

There is currently no unified dependency lock file for this material. The environment information recorded in the existing metadata can be used as a reference, but it does not guarantee that every script has been verified under that exact environment.

### Main Experiment and v2 Analysis

Open a terminal in the local `Origins of All Things` root directory:

```bash
cd "Analysis and results/20000×1test"
python precise_stats_verification.py
python generate_figures.py
python analyze_main_experiment.py --outdir "main resule"
python analyze_ruleAI_v2_completion_deadlock.py --outdir "rule_v2_result"
```

By default, these scripts read the corresponding CSVs from the current working directory.

### Random-Baseline Analysis

Run from the local project root:

```bash
cd "Analysis and results/2000_random_AI_test"
python baseline_stats_verification.py
```

### Seat-Bias Analysis

Run the following in sequence from the local project root:

```bash
python "Analysis and results/data of seat bias/20000×3_random_AI_seat_test/random_seat_bias_analysis.py"
python "Analysis and results/data of seat bias/20000×3seat_test_final/seat_bias_confirmatory_analysis.py"
python "Analysis and results/data of seat bias/merge_seat_bias_cross_group.py"
```

### Turn-Structure Analysis

To analyse the existing data:

```bash
python "Analysis and results/800-round_upper_limit_test/analyze_turn_structure.py"
```

To regenerate the data first:

```bash
node "Analysis and results/800-round_upper_limit_test/engine_turn_structure_check.js"
python "Analysis and results/800-round_upper_limit_test/analyze_turn_structure.py"
```

By default, the generation script runs six matchup configurations, 5,000 games each.

**Running the analysis, or re-running the simulation, may overwrite the existing output in the corresponding directory. If the original deliverable materials need to be preserved, copy them first.**

## 6. Notes on Data Interpretation and Reproduction

### Metric Definitions

- **Completion rate**: the number of games that produced a winner, divided by the total number of simulated games.
- **Mixed-matchup win rate**: the number of wins for a given AI type, divided by the number of completed games; timed-out games are excluded from the denominator.
- **The 100% win rate of a same-type control group**: means that every winner belongs to the same AI type, not that the completion rate is 100%.
- **Turn count**: in the automated simulation, a turn is a single rotation for one seat, including an empty-hand skip. It is not a full round in which all four players each act once.
- **Timeout**: the game reached the 800-turn cap without producing a winner; it does not indicate that the program exceeded some real-world time limit.
- **Decision time**: records the execution time of the AI function itself, and excludes the full interface interaction and any animation time.

A mixed experiment is usually two AIs of one strategy against two AIs of another. It remains a four-player game in which each player competes individually, rather than a one-on-one match or a team match.

### Boundaries Between the Experiment and the Implementation

- The simulation uses `Math.random()` without a fixed seed. Existing CSVs can be re-analysed, but re-running the simulation will not reproduce the original batch game by game.
- Decision time is affected by hardware, browser, timer precision, and running load; a `0 ms` record does not mean the computation carried no cost.
- Formal statistics should be combined with the Python verification results, with the sample scope, test method, and per-game or per-move basis of analysis stated explicitly.
- The game page, the automated simulation page, and the structure-verification script each keep their own implementation of the rules, and these have not yet been unified into a shared engine.
- The human absorption workflow on the interactive page differs in timing from the set-extraction point used in the automated simulation, so the interactive game experience should be kept distinct from the automated experimental results.
- The 800-turn cap is an end-of-simulation control specific to the automated simulation; the interactive page does not apply the same unified cap.
- Different batches should be kept isolated from one another, and in particular the abandoned data in `package/` should not be folded into the current statistics.
