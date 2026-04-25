"""OpenSkill rating engine for Phase 0.

This module is the Phase 0 rating engine — single model (OpenSkill
Plackett-Luce) running over all loaded matches. Phase 1+ adds the
Modified Glicko-2 challenger (per PLAN.md §5.7 and `_RESEARCH_/...`).

Key references:
- PLAN.md §5.2 — algorithm choice; universal games-won score formula
  (S = games_won / total_games, replacing the earlier tanh weight);
  walkover handling (S = 0.90 / 0.10); time decay via OpenSkill `tau`
  (sigma drift per rating period)
- PLAN.md §5.7 — model-agnostic schema (`model_name` discriminator)
- _RESEARCH_/Doubles_Tennis_Ranking_System.docx §4 — original source
  for the universal-score formulation
- T-P0-006 — owning task

Status: scaffolding + universal_score() landed pre-T-P0-004; the
recompute_all() body is filled in by T-P0-006 once the parser has
loaded matches.
"""

from __future__ import annotations

import sqlite3
from typing import Iterator, NamedTuple

# ---- Constants (tunable in Phase 0; persisted in PLAN.md §5.2) ----

CHAMPION_MODEL = "openskill_pl"

# OpenSkill's `tau` controls per-rating-period sigma drift.
# Default 0.0833 ≈ 1/12 — picks up sigma growth equivalent to ~1 month
# per rating period when periods are calendar months.
DEFAULT_TAU = 0.0833

# Rating period length in days. Monthly is the PLAN.md §5.2 default.
DEFAULT_RATING_PERIOD_DAYS = 30


# ---- Pure helpers (no DB / no OpenSkill dependency — testable now) ----


def universal_score(
    games_won: int, opponent_games_won: int, walkover: bool = False
) -> float:
    """Return the actual-score `S` ∈ [0, 1] for one side of a match.

    Per PLAN.md §5.2 (revised after `_RESEARCH_/...` §4):
        S = games_won / (games_won + opponent_games_won)

    This single formula handles 2-set matches and 18-game format events
    without special-casing. Used directly as OpenSkill's actual-score input
    (NOT a weight multiplier).

    Walkover handling per PLAN.md §5.2:
        S_winner = 0.90, S_loser = 0.10
    A walkover is not a real match — using `1.0 / 0.0` would over-reward
    the recipient. The 0.90/0.10 split preserves a small rating effect
    without dominating.

    Edge case: if both sides won zero games (data error / 0-0 placeholder),
    return 0.5 — uninformative draw rather than a divide-by-zero.
    """
    if walkover:
        return 0.90 if games_won > opponent_games_won else 0.10
    total = games_won + opponent_games_won
    if total == 0:
        return 0.5
    return games_won / total


# ---- Data shapes for the rating loop (filled in by T-P0-006) ----


class MatchRow(NamedTuple):
    """A single match's data as needed by the rating engine."""

    match_id: int
    played_on: str  # ISO date
    side_a_player1_id: int
    side_a_player2_id: int
    side_a_games: int
    side_b_player1_id: int
    side_b_player2_id: int
    side_b_games: int
    walkover: bool


def _iter_active_matches(db_conn: sqlite3.Connection) -> Iterator[MatchRow]:
    """Yield active matches (not superseded), chronological by `played_on`,
    breaking ties by `match.id` (insertion order).

    Active = `superseded_by_run_id IS NULL`.
    Doubles only (Phase 0): `match_type = 'doubles'`.

    Implementation lands with T-P0-006.
    """
    raise NotImplementedError("T-P0-006 — implementation pending")


# ---- Main entry point (T-P0-006) ----


def recompute_all(
    db_conn: sqlite3.Connection,
    model_name: str = CHAMPION_MODEL,
    tau: float = DEFAULT_TAU,
    rating_period_days: int = DEFAULT_RATING_PERIOD_DAYS,
) -> int:
    """Recompute ratings for all active matches, chronologically. Returns
    the number of matches processed.

    Phase 0 = full recompute every time. Wipes existing `ratings` and
    `rating_history` rows for `model_name`, then replays all matches.
    Each match update writes one `rating_history` row per player
    involved (4 per doubles match).

    Incremental updates land in Phase 1 once the cost matters.

    Implementation lands with T-P0-006 — needs openskill installed
    (`pip install -r requirements-phase0.txt`).
    """
    raise NotImplementedError(
        "T-P0-006 — implementation pending. Needs `pip install openskill` and "
        "matches loaded by T-P0-004 to be runnable end-to-end."
    )
