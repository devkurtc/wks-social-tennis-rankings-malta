# Research / Reference Material

External reference documents that informed RallyRank's design. Vendored into the repo so the source is auditable and so future contributors can see what specifications were adopted, modified, or deferred.

These files are **read-only**. Treat as historical reference, not as live specifications. The live spec is `PLAN.md` — if `PLAN.md` and a research doc disagree, `PLAN.md` wins.

## Contents

### `Doubles_Tennis_Ranking_System.docx`

**Source:** received 2026-04-25 from Kurt's tennis-trader friend (a tennis bookmaker / odds analyst).
**Subject:** complete mathematical model + implementation guide for an amateur club doubles tennis ranking system based on Modified Glicko-2.
**Length:** ~33 KB / ~25 pages, well-structured.
**Status:** influential — reviewed 2026-04-26; selected sections adopted into PLAN.md; rest deferred or out of scope.

#### Adopted into Phase 0 (PLAN.md updates 2026-04-26)

| Section in research doc | Adopted as | RallyRank reference |
|---|---|---|
| §4 — Universal Performance Score `S = games_won / total_games` | Replaces my earlier tanh weight-multiplier approach | PLAN.md §5.2 (Score margin paragraph); TASKS.md T-P0-006 |
| §11.4 — Forfeit handling: `S = 0.90 / 0.10` not `1.0 / 0.0` | Adopted verbatim | PLAN.md §5.2 (Forfeit handling paragraph); TASKS.md T-P0-006 |

#### Queued for Phase 1+ (PLAN.md §5.2.1)

| Section in research doc | Notes |
|---|---|
| §9.2 — Rating drift toward division mean for long absences | Layered onto OpenSkill's σ-drift; addresses "ghost rating" problem |
| §8.1, §8.2 — Per-division K-factor multipliers | Tunable; needs per-division calibration data |
| §8.3 — Tournament-type K multipliers | Requires new schema column `tournaments.tier` |
| §2.2 — Per-division starting ratings (the *pattern*, not the numbers) | Their numbers are Glicko-2 scale; ours need OpenSkill-scale calibration |
| §7 — Partner-weighted Δ formula | Open question for `rating-engine-expert` agent: does OpenSkill PL's native team apportionment do equivalent work? Investigation queued in T-P0-006 |

#### Adopted as the first challenger model spec (Phase 1)

§§5–9 of the research doc collectively define "Modified Glicko-2" — the first challenger model in the multi-model architecture (PLAN.md §5.7). See TASKS.md T-P1-009 for the implementation task referencing this doc.

#### Queued for Phase 2 (leaderboard UI)

| Section | Adopted as |
|---|---|
| §12 — Secondary display stats (Win%, Game Win%, Partner Synergy, Upset Rate, Peak Rating, Current Form, etc.) | TASKS.md T-P2-014 |
| §2.3 — RD-based "Provisional / Reliable" thresholds; §9.4 — minimum-activity gates | TASKS.md T-P2-015 |

#### Out of scope

| Section | Why skipped |
|---|---|
| §13.2 — Auto promotion / relegation flagging + thresholds | Club-management feature; PLAN.md §1 scopes RallyRank to ranking + pair recommendations, not division administration. Revisit only if a club explicitly requests. |

#### Decisions where we deliberately diverge

| Topic | Their position | Our position |
|---|---|---|
| Primary rating algorithm | Modified Glicko-2 | OpenSkill (Plackett-Luce) — see PLAN.md §5.2 rationale. Their concerns (sparse data, native uncertainty, automatic time decay) are all addressed by OpenSkill, which additionally has native team support. Modified Glicko-2 runs as the first challenger (T-P1-009); empirical predictive scoring (PLAN.md §5.7 model_scoreboard) decides which is actually better. |
| Rating period | One tournament = one period | One calendar month = one period. Matches our continuous-update goal better; tournaments are not regular enough in cadence for monthly to lose much fidelity. |
| Scope | Single-club internal tool, manual data entry | Multi-club, agentic ingestion, public web app. Their architecture sections don't transfer; their math sections do. |
