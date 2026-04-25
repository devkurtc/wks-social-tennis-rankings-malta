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

import math
import sqlite3
from datetime import date
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
    """Yield active doubles matches (not superseded), chronological by
    `played_on`, breaking ties by `match.id` (insertion order).
    """
    rows = db_conn.execute(
        """
        SELECT
            m.id, m.played_on, m.walkover,
            sa.player1_id, sa.player2_id, sa.games_won,
            sb.player1_id, sb.player2_id, sb.games_won
        FROM matches m
        JOIN match_sides sa ON sa.match_id = m.id AND sa.side = 'A'
        JOIN match_sides sb ON sb.match_id = m.id AND sb.side = 'B'
        WHERE m.superseded_by_run_id IS NULL
          AND m.match_type = 'doubles'
        ORDER BY m.played_on, m.id
        """
    ).fetchall()
    for row in rows:
        # Doubles requires both partners on each side; skip malformed rows
        # rather than crashing (parser shouldn't produce these but be defensive).
        if row[4] is None or row[7] is None:
            continue
        yield MatchRow(
            match_id=row[0],
            played_on=row[1],
            side_a_player1_id=row[3],
            side_a_player2_id=row[4],
            side_a_games=row[5],
            side_b_player1_id=row[6],
            side_b_player2_id=row[7],
            side_b_games=row[8],
            walkover=bool(row[2]),
        )


def _periods_between(date_from: str, date_to: str, period_days: int) -> int:
    """Number of full rating periods between two ISO dates (>= 0)."""
    if not date_from or not date_to or date_from >= date_to:
        return 0
    days = (date.fromisoformat(date_to) - date.fromisoformat(date_from)).days
    return max(0, days // period_days)


# ---- Main entry point ----


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
    involved (4 per doubles match) and one final `ratings` row per
    distinct player.

    Sigma drift: between matches, each player's σ is inflated based on
    how many rating periods elapsed since their last match (per
    PLAN.md §5.2 Time decay paragraph). For Phase 0 with one-tournament
    data, drift is effectively zero (all matches share `played_on`)
    but the logic is in place for multi-tournament Phase 1+ data.

    Incremental updates land in Phase 1; Phase 0 is full-recompute.
    """
    # Lazy import — openskill is a heavy dep, only needed when actually rating
    from openskill.models import PlackettLuce

    model = PlackettLuce(tau=tau)

    # Wipe prior state for this model_name (full recompute semantics)
    with db_conn:
        db_conn.execute("DELETE FROM rating_history WHERE model_name = ?", (model_name,))
        db_conn.execute("DELETE FROM ratings WHERE model_name = ?", (model_name,))

    # In-memory state during replay
    player_ratings: dict[int, object] = {}      # player_id → current Rating
    player_last_played: dict[int, str] = {}     # player_id → ISO date string
    player_n_matches: dict[int, int] = {}       # player_id → cumulative count

    n_matches = 0

    with db_conn:
        for m in _iter_active_matches(db_conn):
            player_ids = (
                m.side_a_player1_id, m.side_a_player2_id,
                m.side_b_player1_id, m.side_b_player2_id,
            )

            # Get-or-create rating, applying sigma drift on inactivity
            for pid in player_ids:
                if pid not in player_ratings:
                    player_ratings[pid] = model.rating()
                else:
                    last = player_last_played.get(pid)
                    periods = _periods_between(last, m.played_on, rating_period_days)
                    if periods > 0:
                        old = player_ratings[pid]
                        new_sigma = math.sqrt(old.sigma ** 2 + periods * (tau ** 2))
                        player_ratings[pid] = model.rating(mu=old.mu, sigma=new_sigma)

            team_a = [player_ratings[m.side_a_player1_id], player_ratings[m.side_a_player2_id]]
            team_b = [player_ratings[m.side_b_player1_id], player_ratings[m.side_b_player2_id]]

            # Universal games-won score (handles walkovers per PLAN.md §5.2)
            s_a = universal_score(m.side_a_games, m.side_b_games, walkover=m.walkover)
            s_b = 1.0 - s_a

            # OpenSkill rate: higher score = better outcome
            new_a, new_b = model.rate([team_a, team_b], scores=[s_a, s_b])

            player_ratings[m.side_a_player1_id] = new_a[0]
            player_ratings[m.side_a_player2_id] = new_a[1]
            player_ratings[m.side_b_player1_id] = new_b[0]
            player_ratings[m.side_b_player2_id] = new_b[1]

            # Append rating_history rows + bookkeeping
            for pid in player_ids:
                r = player_ratings[pid]
                player_last_played[pid] = m.played_on
                player_n_matches[pid] = player_n_matches.get(pid, 0) + 1
                db_conn.execute(
                    "INSERT INTO rating_history "
                    "(player_id, model_name, match_id, mu_after, sigma_after) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (pid, model_name, m.match_id, r.mu, r.sigma),
                )

            n_matches += 1

        # Persist final ratings for each player
        for pid, r in player_ratings.items():
            db_conn.execute(
                "INSERT INTO ratings "
                "(player_id, model_name, mu, sigma, n_matches, last_updated_at) "
                "VALUES (?, ?, ?, ?, ?, datetime('now'))",
                (pid, model_name, r.mu, r.sigma, player_n_matches.get(pid, 0)),
            )

    return n_matches
