# Model evaluation — backtest of OpenSkill PL variants

**Date:** 2026-04-26
**Dataset:** 4,716 active doubles matches, 2017-04 → 2026-04
**Held-out cutoff:** `played_on >= 2025-07-01` → 888 prediction matches, 3,828 train matches
**Tooling:** `scripts/phase0/backtest.py` — model-agnostic harness, online-evaluation (state updates after each held-out prediction)

## Headline result

| Engine | log-loss | Brier | Accuracy | vs random |
|---|---:|---:|---:|---|
| `openskill_pl_vanilla` | 0.6526 | 0.2186 | 65.99% | baseline |
| `openskill_pl_decay365` | **0.6147** | 0.2134 | 64.98% | **−5.8% log-loss** |
| `openskill_pl_decay180` | 0.6354 | 0.2232 | 62.16% | TAU too aggressive |
| `openskill_pl_decay730` | 0.6199 | **0.2124** | **66.44%** | best Brier + accuracy |

(Random baseline: log-loss 0.6931, Brier 0.25, accuracy ~50%.)

Time-decay PL with τ in the 365–730 day range improves on vanilla PL across log-loss, Brier, and (for τ=730) accuracy. τ=180 days is too aggressive — the model loses too much information.

## Calibration (predicted decile → actual frequency)

The vanilla model is **systematically overconfident at both extremes**:

```
Vanilla PL                    | Decay τ=365                  | Decay τ=730
bin    n   pred  actual       | bin    n   pred  actual       | bin    n   pred  actual
[0.0)  136  0.05  0.1324      | [0.0)   50  0.05  0.0400 ✓    | [0.0)   83  0.05  0.0723 ✓
[0.1)   93  0.15  0.3548      | [0.1)   77  0.15  0.2338      | [0.1)   81  0.15  0.2963
[0.9)  114  0.95  0.8158      | [0.9)   38  0.95  0.8421      | [0.9)   82  0.95  0.8780 ✓
```

When vanilla predicts a 5% chance of winning, the player actually wins 13% of the time — the model is too sure of itself when it sees a "weak" opponent. Decay τ=365 fixes this exactly (predicted 5% → actual 4%).

This is the deeper finding behind Lonia's intuition: she penalises high-σ players less than μ-3σ does because **the model's confidence in those players' losses is empirically too high**. The decay variant addresses the root cause.

## Why decay helps

The vanilla model treats a 4-year-old win the same as last week's. Players whose form has changed (faded form: Cory Greenland; recent surge: any newer player) carry baggage from old data. Multiplying each match's update weight by `exp(-age_days/τ)`:

- A match from yesterday: weight ≈ 1.00 (full)
- A match from 6 months ago at τ=365: weight ≈ 0.61
- A match from 1 year ago at τ=365: weight ≈ 0.37
- A match from 4 years ago at τ=365: weight ≈ 0.018 (effectively dropped)

So Spring 2022 results barely move the needle today; recent results dominate.

## What this does NOT prove

- **Lonia's specific picks**: she may still be wrong on individual players (e.g. Bernardette Fenech, Stefan Holmin) where the model already had the right answer. Backtest log-loss is averaged across all matches; per-player calibration would be the next analysis.
- **Best τ universally**: τ=730 wins on accuracy/Brier, τ=365 wins on log-loss. The "right" τ depends on whether you optimise for predicted probability quality or for who-beats-whom. **Recommend τ=365** as the default — log-loss is the more diagnostic of overconfidence.
- **Other model families**: Glicko-2, TrueSkill, and TM-OpenSkill were not tested. The expert-agent recommendation was that on a doubles dataset of this shape, time-decayed PL gives the most signal per implementation hour. Adding Glicko-2 is plausible follow-up.

## Reproduction

```bash
python3 scripts/phase0/backtest.py --cutoff 2025-07-01 --engine openskill_pl_decay365
```

Per-match prediction CSVs are in `_ANALYSIS_/model_evaluation/<engine>.csv`.

## Recommended next actions

1. **Promote `openskill_pl_decay365` to a parallel production model.** Re-use the
   existing `model_name`-keyed `ratings` and `rating_history` tables; add it
   as a second column on the leaderboard and tournament pages so users can
   eyeball the difference before making it the default.
2. **Run the full season's per-player Lonia agreement under both models.**
   Spearman correlation of decay-model rankings vs Lonia's; expect higher ρ
   driven by the calibration improvement at the high-σ end.
3. **Defer Glicko-2 challenger** until after we know if (1) is a clear win.
   Adding a third model on a still-uncalibrated doubles dataset risks
   chasing noise.
4. **Future**: per-player calibration. For each rated player, plot
   predicted P(win) vs realised P(win) on their held-out matches. This
   tells us *which players* the model is overconfident about — a far
   sharper diagnostic than aggregate calibration.
