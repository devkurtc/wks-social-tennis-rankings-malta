"""DF's Glicko-2 challenger rating engine for Phase 0.

Implements a doubles-adapted Glicko-2 model as the first challenger to
OpenSkill PL (per PLAN.md §5.7). Additive: reads the same `matches` table,
writes `ratings` and `rating_history` rows tagged `model_name = DF_MODEL`.
Does not touch any `openskill_pl` rows.

Key design choices vs the champion (openskill_pl):
- Rating scale: Glicko-2 (μ ≈ 1500, RD ≈ 30–350) vs OpenSkill PL (μ ≈ 25, σ ≈ 8).
- Uncertainty: RD (rating deviation) replaces OpenSkill σ. Both converge to a
  lower value with more matches; both grow during inactivity.
- Team handling: each player sees the opponent *team* as a single entity with
  the average of both opponents' ratings and a combined RD. The same g() / E()
  functions apply as in standard Glicko-2 1v1.
- Score margin: reuses `rating.universal_score()` (PLAN.md §5.2) as the Glicko-2
  actual outcome s ∈ [0, 1] — the same formula drives both models.
- No upset multiplier, no partner-weighted Δμ, no division K-multiplier:
  deliberately simpler than the champion so disagreements are informative
  (if both agree a player is strong, that's a more robust signal).
- RD drift on inactivity: per Glicko-2 spec, φ² grows by DEFAULT_VOLATILITY²
  per rating period during gaps between matches.

References:
  Glickman (2012) "Example of the Glicko-2 system"
    http://www.glicko.net/glicko/glicko2.pdf
  PLAN.md §5.2 — universal_score, walkover handling
  PLAN.md §5.7 — multi-model architecture this module plugs into
"""

from __future__ import annotations

import math
import sqlite3
from datetime import date
from typing import Iterator

from rating import (
    MatchRow,
    _iter_active_matches,
    _periods_between,
    _player_first_division,
    universal_score,
)

# ---- Constants ---------------------------------------------------------------

DF_MODEL = "df_glicko2_v1"

# Glicko-2 internal scale constant: r = 173.7178 * μ + 1500
_SCALE = 173.7178

# Starting rating per division. Tier ordering mirrors rating.DIVISION_STARTING_MU
# but on the Glicko-2 r-scale (≈1500 baseline).
# Why: players entering from a higher division have a stronger prior.
DIVISION_STARTING_R: dict[str, float] = {
    "Men A": 1800.0, "Men Div 1": 1800.0,
    "Men B": 1650.0, "Men Div 2": 1650.0,
    "Men C": 1500.0, "Men Div 3": 1500.0,
    "Men D": 1350.0, "Men Div 4": 1350.0,
    "Lad A": 1750.0, "Lad Div 1": 1750.0,
    "Lad B": 1600.0, "Lad Div 2": 1600.0,
    "Lad C": 1450.0, "Lad Div 3": 1450.0,
    "Lad D": 1300.0,
}

DEFAULT_R = 1500.0
DEFAULT_RD = 350.0    # maximum initial uncertainty (per Glicko-2 spec)
MIN_RD = 30.0         # floor: even high-volume players retain a little uncertainty
MAX_RD = 350.0        # ceiling (= DEFAULT_RD; RD never grows beyond starting value)

# Volatility σ (kept constant at Phase 0; full Illinois-algorithm update is Phase 1+).
# Per Glicko-2 spec the recommended starting value is 0.06.
DEFAULT_VOLATILITY = 0.06

# Rating periods for RD drift (same default as rating.py for consistency).
DEFAULT_RATING_PERIOD_DAYS = 30


# ---- Pure Glicko-2 helpers ---------------------------------------------------


def _g(phi: float) -> float:
    """Glicko-2 g-function: reduces weight of opponents with high uncertainty."""
    return 1.0 / math.sqrt(1.0 + 3.0 * phi ** 2 / math.pi ** 2)


def _E(mu: float, mu_j: float, phi_j: float) -> float:
    """Glicko-2 expected score E(s|μ, μ_j, φ_j) ∈ (0, 1)."""
    return 1.0 / (1.0 + math.exp(-_g(phi_j) * (mu - mu_j)))


def _to_internal(r: float, rd: float) -> tuple[float, float]:
    """Convert Glicko-2 external (r, RD) → internal (μ, φ)."""
    return (r - 1500.0) / _SCALE, rd / _SCALE


def _to_external(mu: float, phi: float) -> tuple[float, float]:
    """Convert Glicko-2 internal (μ, φ) → external (r, RD)."""
    return _SCALE * mu + 1500.0, _SCALE * phi


def glicko2_update(
    r: float,
    rd: float,
    r_opp: float,
    rd_opp: float,
    s: float,
    sigma_vol: float = DEFAULT_VOLATILITY,
) -> tuple[float, float]:
    """Apply a single-match Glicko-2 update.

    Args:
        r: current rating (external scale ≈ 1500).
        rd: current RD (external scale).
        r_opp: opponent rating (external scale).
        rd_opp: opponent RD (external scale).
        s: actual outcome ∈ [0, 1] from universal_score().
        sigma_vol: volatility (kept constant for Phase 0).

    Returns:
        (new_r, new_rd) on the external scale.
    """
    mu, phi = _to_internal(r, rd)
    mu_j, phi_j = _to_internal(r_opp, rd_opp)

    g_j = _g(phi_j)
    E_j = _E(mu, mu_j, phi_j)

    # Estimated variance v (single opponent → single term in the sum)
    v = 1.0 / (g_j ** 2 * E_j * (1.0 - E_j))

    # Estimated improvement Δ
    delta = v * g_j * (s - E_j)

    # Pre-period φ: inflate by volatility (RD drift for inactive periods
    # is applied separately before this call, so here σ_vol is the
    # per-match term only; at Phase 0 we keep σ_vol constant).
    phi_star = math.sqrt(phi ** 2 + sigma_vol ** 2)

    # New φ'
    phi_new = 1.0 / math.sqrt(1.0 / phi_star ** 2 + 1.0 / v)

    # New μ'
    mu_new = mu + phi_new ** 2 * g_j * (s - E_j)

    r_new, rd_new = _to_external(mu_new, phi_new)
    rd_new = max(MIN_RD, min(MAX_RD, rd_new))
    return r_new, rd_new


def _drift_rd(rd: float, periods: int, sigma_vol: float = DEFAULT_VOLATILITY) -> float:
    """Grow RD by Glicko-2 inactivity drift over `periods` rating periods.

    Per Glicko-2 spec: φ_* = sqrt(φ² + periods * σ²).
    RD is clamped to MAX_RD (cannot exceed the initial high-uncertainty value).
    """
    if periods <= 0:
        return rd
    _, phi = _to_internal(0.0, rd)
    phi_drifted = math.sqrt(phi ** 2 + periods * sigma_vol ** 2)
    rd_drifted = _SCALE * phi_drifted
    return min(MAX_RD, rd_drifted)


def _division_starting_r(division: str | None) -> float:
    """Starting r for a player whose first match was in this division."""
    from rating import normalize_division
    norm = normalize_division(division)
    if norm is None:
        return DEFAULT_R
    return DIVISION_STARTING_R.get(norm, DEFAULT_R)


def _team_aggregate(
    r1: float, rd1: float, r2: float, rd2: float
) -> tuple[float, float]:
    """Aggregate two players into a single team entity for Glicko-2 math.

    Team r  = arithmetic mean of partner ratings.
    Team RD = root-mean-square of partner RDs (propagates combined uncertainty).
    """
    r_team = (r1 + r2) / 2.0
    rd_team = math.sqrt((rd1 ** 2 + rd2 ** 2) / 2.0)
    return r_team, rd_team


# ---- Main entry point --------------------------------------------------------


def recompute_all(
    conn: sqlite3.Connection,
    model_name: str = DF_MODEL,
    rating_period_days: int = DEFAULT_RATING_PERIOD_DAYS,
) -> int:
    """Recompute Glicko-2 ratings for all active matches, chronologically.

    Full-recompute semantics (same as rating.recompute_all): wipes existing
    rows for `model_name`, replays all matches from scratch. Returns the
    number of matches processed.

    Writes to:
      rating_history(player_id, model_name, match_id, mu_after, sigma_after)
        where mu_after = Glicko-2 r, sigma_after = Glicko-2 RD.
      ratings(player_id, model_name, mu, sigma, n_matches, last_updated_at)
        same mapping.

    Does NOT touch any rows with a different model_name.
    """
    with conn:
        conn.execute("DELETE FROM rating_history WHERE model_name = ?", (model_name,))
        conn.execute("DELETE FROM ratings     WHERE model_name = ?", (model_name,))

    # In-memory state
    player_r: dict[int, float] = {}
    player_rd: dict[int, float] = {}
    player_last_played: dict[int, str] = {}
    player_n_matches: dict[int, int] = {}

    n_matches = 0

    with conn:
        for m in _iter_active_matches(conn):
            player_ids = (
                m.side_a_player1_id, m.side_a_player2_id,
                m.side_b_player1_id, m.side_b_player2_id,
            )

            # Initialise new players; drift RD for inactive players.
            for pid in player_ids:
                if pid not in player_r:
                    first_div = _player_first_division(conn, pid)
                    player_r[pid] = _division_starting_r(first_div)
                    player_rd[pid] = DEFAULT_RD
                else:
                    last = player_last_played.get(pid)
                    periods = _periods_between(last, m.played_on, rating_period_days)
                    if periods > 0:
                        player_rd[pid] = _drift_rd(player_rd[pid], periods)

            # Team aggregates
            r_a, rd_a = _team_aggregate(
                player_r[m.side_a_player1_id], player_rd[m.side_a_player1_id],
                player_r[m.side_a_player2_id], player_rd[m.side_a_player2_id],
            )
            r_b, rd_b = _team_aggregate(
                player_r[m.side_b_player1_id], player_rd[m.side_b_player1_id],
                player_r[m.side_b_player2_id], player_rd[m.side_b_player2_id],
            )

            s_a = universal_score(m.side_a_games, m.side_b_games, walkover=m.walkover)
            s_b = 1.0 - s_a

            # Update each player vs the opposing team aggregate
            updates: dict[int, tuple[float, float]] = {}
            for pid in (m.side_a_player1_id, m.side_a_player2_id):
                updates[pid] = glicko2_update(player_r[pid], player_rd[pid], r_b, rd_b, s_a)
            for pid in (m.side_b_player1_id, m.side_b_player2_id):
                updates[pid] = glicko2_update(player_r[pid], player_rd[pid], r_a, rd_a, s_b)

            for pid, (new_r, new_rd) in updates.items():
                player_r[pid] = new_r
                player_rd[pid] = new_rd
                player_last_played[pid] = m.played_on
                player_n_matches[pid] = player_n_matches.get(pid, 0) + 1
                conn.execute(
                    "INSERT INTO rating_history "
                    "(player_id, model_name, match_id, mu_after, sigma_after) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (pid, model_name, m.match_id, new_r, new_rd),
                )

            n_matches += 1

        for pid in player_r:
            conn.execute(
                "INSERT INTO ratings "
                "(player_id, model_name, mu, sigma, n_matches, last_updated_at) "
                "VALUES (?, ?, ?, ?, ?, datetime('now'))",
                (
                    pid, model_name,
                    player_r[pid], player_rd[pid],
                    player_n_matches.get(pid, 0),
                ),
            )

    return n_matches
