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
import re
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

# OpenSkill's default starting μ. Used as a fallback when a player's
# division can't be determined.
DEFAULT_STARTING_MU = 25.0

# Per-division starting μ — encodes external knowledge that Div 1 players
# enter with stronger priors than Div 4 players. Spacing roughly mirrors
# the friend's research doc (Glicko 250-pt inter-division gap → ~3
# OpenSkill units). Values tunable; keys must match parser-emitted
# `matches.division` strings (after normalization via _normalize_division).
# Source: T-P0-011, _RESEARCH_/Doubles_Tennis_Ranking_System.docx §2.2
# Tier mapping per Kurt's domain knowledge: a "Men A" player (team-rubber
# slot) is the same tier as a "Men Div 1" player (division-tournament tier).
# Same for B↔Div 2, C↔Div 3, D↔Div 4. Same for Lad A/B/C↔Lad Div 1/2/3 +
# new Lad D bottom slot.
#
# All rating constants below are keyed by raw division name but values are
# IDENTICAL within a tier — so a player who plays mostly Men A and a player
# who plays mostly Men Div 1 are treated equivalently by the rating engine.
DIVISION_STARTING_MU: dict[str, float] = {
    # Tier 1 — Men A / Men Div 1
    "Men A": 33.0, "Men Div 1": 33.0,
    # Tier 2 — Men B / Men Div 2
    "Men B": 28.0, "Men Div 2": 28.0,
    # Tier 3 — Men C / Men Div 3
    "Men C": 23.0, "Men Div 3": 23.0,
    # Tier 4 — Men D / Men Div 4
    "Men D": 18.0, "Men Div 4": 18.0,
    # Ladies tiers
    "Lad A": 31.0, "Lad Div 1": 31.0,
    "Lad B": 26.0, "Lad Div 2": 26.0,
    "Lad C": 21.0, "Lad Div 3": 21.0,
    "Lad D": 16.0,  # no Lad Div 4 observed in current data
}

# Per-division μ ceilings — a player CANNOT rise above their division's
# ceiling, regardless of how dominant their wins are. This is the friend's
# research doc §8.1, §8.2 approach: Div 2 player capped below where Div 1
# starts. Strictly enforces cross-division ordering. None = no ceiling.
# v2 (2026-04-26): CAPS REMOVED. Math is honest — μ flows freely with results.
# Tier ordering is preserved by class-based DISPLAY sort (captain-assigned class
# label sorts above raw μ). See player_team_assignments + cmd_rank for the
# class-sort logic. The empty dicts here are kept for back-compat with
# `clip_mu_to_division` which now becomes a no-op when both are empty.
DIVISION_MU_CEILING: dict[str, float | None] = {}
DIVISION_MU_FLOOR: dict[str, float | None] = {}

# Per-division K-multiplier — scales how much a single match moves a
# player's rating. Higher-division matches count more (encoding "harder
# competition = more meaningful rating change").
# Source: T-P0-011, _RESEARCH_/Doubles_Tennis_Ranking_System.docx §8.1, §8.2
DIVISION_K: dict[str, float] = {
    # v2 (2026-04-26): kept moderate spread (1.00/0.85/0.70/0.55) instead of
    # aggressive 1.00/0.75/0.50/0.30 — Doubt #3 mitigation per Kurt's review.
    # Lower-tier matches still count substantially; we just downweight modestly.
    "Men A": 1.00, "Men Div 1": 1.00,
    "Men B": 0.85, "Men Div 2": 0.85,
    "Men C": 0.70, "Men Div 3": 0.70,
    "Men D": 0.55, "Men Div 4": 0.55,
    "Lad A": 1.00, "Lad Div 1": 1.00,
    "Lad B": 0.85, "Lad Div 2": 0.85,
    "Lad C": 0.70, "Lad Div 3": 0.70,
    "Lad D": 0.55,
}

# Game-volume K-multiplier baseline: a "typical" 2-set match has ~18
# games. Scaled K = total_games / 18 (clamped to [0.5, 1.5]).
# Source: T-P0-012, Kurt's T-P0-009 feedback Q2A
VOLUME_K_BASELINE = 18
VOLUME_K_MIN = 0.5
VOLUME_K_MAX = 1.5
WALKOVER_VOLUME_K = 0.5  # walkovers carry minimal signal regardless of recorded score

# Upset-amplification factor: when a match outcome diverges from expectation
# (favorite loses; underdog wins), AMPLIFY the rating change for ALL four
# players — losers drop more, winners rise more.
# K_upset = 1 + UPSET_ALPHA × |S_actual - E_predicted|
# Range: 1.0 (perfect prediction, no boost) to 1 + UPSET_ALPHA (total upset).
# UPSET_ALPHA = 1.0 means a 50%-magnitude upset gives 1.5× boost.
# Tunable per Kurt's "losing to worse should drop more" feedback.
# Symmetric: applies equally to upset winners and upset losers, preserving
# rating-system conservation (sum of all players' μ stays ~constant).
UPSET_ALPHA = 1.0


# ---- Pure helpers (no DB / no OpenSkill dependency — testable now) ----


# Canonicalize many division-name variants to one form.
# Real data observed includes:
#   "Men Division 1", "Men Division 1 " (trailing space)
#   "Men Division 3 - Group A", "Men Division 3 - Group B", "Men Division 3"
#   "Ladies Division 1", "Lad Div 2"
# Canonical form: "Men Div N" or "Lad Div N" (matches DIVISION_K /
# DIVISION_STARTING_MU keys).
_DIV_PATTERN = re.compile(
    r"^(?P<gender>Men|Ladies|Lad)\s+(?:Division|Div)\s+(?P<n>\d+)",
    re.IGNORECASE,
)


def normalize_division(raw: str | None) -> str | None:
    """Canonicalize a division label so DIVISION_K / DIVISION_STARTING_MU
    lookups work for any variant produced by the parser.

    Returns `"Men Div N"` or `"Lad Div N"` when the input matches the
    expected pattern. Unrecognized inputs pass through stripped (so
    unknown divisions still get the fallback K=1.0 / μ=25 behavior).
    None / empty inputs return None.
    """
    if raw is None:
        return None
    s = raw.strip()
    if not s:
        return None
    m = _DIV_PATTERN.match(s)
    if not m:
        return s
    gender = "Men" if m.group("gender").lower() == "men" else "Lad"
    return f"{gender} Div {m.group('n')}"


def division_k_multiplier(division: str | None) -> float:
    """K-multiplier for a match's division. Unknown divisions fall back to
    1.0 (no penalty) — better to count fully than to silently dampen.
    """
    norm = normalize_division(division)
    if norm is None:
        return 1.0
    return DIVISION_K.get(norm, 1.0)


# v2: mixed-doubles "Division N" matches don't carry tier info. Look up
# the player's gendered-primary tier and use that K instead of defaulting
# to 1.0. Returns the K, or None if no gendered primary exists.
def division_k_multiplier_for_match(
    db_conn: sqlite3.Connection,
    match_division: str | None,
    player_id: int,
) -> float:
    """Per-match K. For mixed-doubles ungendered 'Division N' matches, look up
    the player's gendered primary and use THAT tier's K. Otherwise use the
    match's own division.
    """
    norm = normalize_division(match_division)
    if norm and norm in DIVISION_K:
        return DIVISION_K[norm]

    # Match division isn't recognized → check if it's a mixed-doubles
    # "Division N" pattern (no gender prefix). If so, find the player's
    # most-common GENDERED division and use that.
    raw = (match_division or "").strip()
    if raw.lower().startswith("division") or raw.startswith("Mxd") or raw.startswith("MXD"):
        row = db_conn.execute(
            """
            SELECT m.division, COUNT(*) AS n
            FROM matches m
            JOIN match_sides ms ON ms.match_id = m.id
            WHERE (ms.player1_id = ? OR ms.player2_id = ?)
              AND m.superseded_by_run_id IS NULL
              AND m.division IS NOT NULL
              AND (m.division LIKE 'Men%' OR m.division LIKE 'Lad%' OR m.division LIKE 'Ladies%')
            GROUP BY m.division
            ORDER BY n DESC
            LIMIT 1
            """,
            (player_id, player_id),
        ).fetchone()
        if row:
            gendered = normalize_division(row[0])
            if gendered in DIVISION_K:
                return DIVISION_K[gendered]
    # Final fallback
    return 1.0


# v2: partner-weighted Δμ (per `_RESEARCH_/...` §7).
# Stronger partner moves more (gains/loses more); weaker partner moves less.
# Net team rating change is preserved.
PARTNER_WEIGHT_ENABLED = True


def apply_partner_weighting(
    p1_old_mu: float, p2_old_mu: float,
    p1_new_mu: float, p2_new_mu: float,
) -> tuple[float, float]:
    """Redistribute the team's net Δμ between partners by current-skill weight.

    Returns (new_mu_p1_weighted, new_mu_p2_weighted) — same team total Δμ as
    OpenSkill produced, but apportioned so the higher-rated partner moves more.

    Formula (per friend's research §7):
        team_total_delta = (p1_new - p1_old) + (p2_new - p2_old)
        weight_p1 = p1_old / (p1_old + p2_old)
        weight_p2 = p2_old / (p1_old + p2_old)
        delta_p1' = team_total_delta × weight_p1 × 2
        delta_p2' = team_total_delta × weight_p2 × 2
        (×2 because weights sum to 1; preserves team-total when averaged)

    If both partners have μ=0 (shouldn't happen but defensive), splits 50/50.
    """
    team_total_delta = (p1_new_mu - p1_old_mu) + (p2_new_mu - p2_old_mu)
    sum_mu = p1_old_mu + p2_old_mu
    if sum_mu <= 0:
        # Defensive: can't compute weight; return unchanged
        return p1_new_mu, p2_new_mu

    w1 = p1_old_mu / sum_mu
    w2 = p2_old_mu / sum_mu

    # ×2 distributes the total (not the half) per partner; sum back to total
    delta_p1_new = team_total_delta * w1 * 2 / (w1 + w2 + w1 + w2)
    delta_p2_new = team_total_delta * w2 * 2 / (w1 + w2 + w1 + w2)
    # That simplifies to: delta_p1_new = team_total_delta × w1
    #                     delta_p2_new = team_total_delta × w2
    # (verify: w1 + w2 = 1, so delta_p1_new + delta_p2_new = team_total_delta ✓)

    return p1_old_mu + delta_p1_new, p2_old_mu + delta_p2_new


def division_starting_mu(division: str | None) -> float:
    """Starting μ for a player whose first match was in this division.
    Falls back to DEFAULT_STARTING_MU if division is unknown."""
    norm = normalize_division(division)
    if norm is None:
        return DEFAULT_STARTING_MU
    return DIVISION_STARTING_MU.get(norm, DEFAULT_STARTING_MU)


def clip_mu_to_division(mu: float, division: str | None) -> float:
    """Clamp μ within the player's division floor/ceiling. Strictly
    enforces cross-division ordering: a Div 2 player cannot exceed M1's
    starting μ; a Div 1 player cannot drop below M2's starting μ.

    Friend's research doc §8.1, §8.2 approach. None means no constraint
    on that side.
    """
    norm = normalize_division(division)
    if norm is None:
        return mu
    ceiling = DIVISION_MU_CEILING.get(norm)
    floor = DIVISION_MU_FLOOR.get(norm)
    if ceiling is not None and mu > ceiling:
        return ceiling
    if floor is not None and mu < floor:
        return floor
    return mu


def volume_k_multiplier(total_games: int, walkover: bool = False) -> float:
    """K-multiplier from total games played in a match.

    More rallies = more signal: a 26-game match (close 7-6 7-6) reveals
    more about each player's skill than a 12-game blowout (6-0 6-0).

    Walkovers always return WALKOVER_VOLUME_K — the recorded score is
    artificial and shouldn't drive a strong update.

    Otherwise: K = total_games / VOLUME_K_BASELINE, clamped to
    [VOLUME_K_MIN, VOLUME_K_MAX].
    """
    if walkover:
        return WALKOVER_VOLUME_K
    if total_games <= 0:
        return VOLUME_K_MIN  # defensive — shouldn't happen
    raw = total_games / VOLUME_K_BASELINE
    return max(VOLUME_K_MIN, min(VOLUME_K_MAX, raw))


def upset_k_multiplier(s_actual: float, e_expected: float, alpha: float | None = None) -> float:
    """K-multiplier from how surprising the outcome was.

    Returns `1 + alpha * |s_actual - e_expected|`. Higher when the actual
    score diverges from the model's prediction (an upset); 1.0 when the
    prediction was exact.

    Symmetric: a favored team that lost (s_actual << e_expected) and the
    underdog that won (s_actual >> e_expected) both see the same boost.
    Applied to ALL 4 players in the match so rating-system conservation
    holds (sum of μ changes ≈ 0 within each match).

    `alpha=None` (default) reads the current `UPSET_ALPHA` global at call
    time so tests can monkey-patch it. Pass an explicit float to override.
    Module default UPSET_ALPHA=1.0 means a 50%-gap upset gives 1.5× boost;
    total upset (e.g. E=0.9, S=0.1) gives 1.8× boost.
    """
    if alpha is None:
        alpha = UPSET_ALPHA
    surprise = abs(s_actual - e_expected)
    return 1.0 + alpha * surprise


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
    division: str | None
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
            m.id, m.played_on, m.walkover, m.division,
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
        if row[5] is None or row[8] is None:
            continue
        yield MatchRow(
            match_id=row[0],
            played_on=row[1],
            division=row[3],
            side_a_player1_id=row[4],
            side_a_player2_id=row[5],
            side_a_games=row[6],
            side_b_player1_id=row[7],
            side_b_player2_id=row[8],
            side_b_games=row[9],
            walkover=bool(row[2]),
        )


def _player_first_division(db_conn: sqlite3.Connection, player_id: int) -> str | None:
    """Return the division of the chronologically first active match this
    player appears in. Used to seed division-specific starting μ.
    """
    row = db_conn.execute(
        """
        SELECT m.division
        FROM matches m
        JOIN match_sides ms ON ms.match_id = m.id
        WHERE (ms.player1_id = ? OR ms.player2_id = ?)
          AND m.superseded_by_run_id IS NULL
        ORDER BY m.played_on, m.id
        LIMIT 1
        """,
        (player_id, player_id),
    ).fetchone()
    return row[0] if row else None


def _player_primary_division(db_conn: sqlite3.Connection, player_id: int) -> str | None:
    """Return the player's MOST-COMMON division across all active matches.
    Used for cap/floor enforcement (better than first-seen for team-rubber
    players who are stable in one slot but may have one outlier match).
    """
    row = db_conn.execute(
        """
        SELECT m.division
        FROM matches m
        JOIN match_sides ms ON ms.match_id = m.id
        WHERE (ms.player1_id = ? OR ms.player2_id = ?)
          AND m.superseded_by_run_id IS NULL
          AND m.division IS NOT NULL
        GROUP BY m.division
        ORDER BY COUNT(*) DESC, m.division
        LIMIT 1
        """,
        (player_id, player_id),
    ).fetchone()
    return row[0] if row else None


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
    decay_tau_days: float | None = None,
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

    # If time-decay is requested, anchor "now" at the latest match in the
    # dataset so the most recent match always has weight 1.0 and matches
    # decay relative to it. Pure date math — no openskill state involved.
    decay_anchor: str | None = None
    if decay_tau_days and decay_tau_days > 0:
        row = db_conn.execute(
            "SELECT MAX(played_on) FROM matches WHERE superseded_by_run_id IS NULL"
        ).fetchone()
        decay_anchor = row[0] if row else None

    # Wipe prior state for this model_name (full recompute semantics)
    with db_conn:
        db_conn.execute("DELETE FROM rating_history WHERE model_name = ?", (model_name,))
        db_conn.execute("DELETE FROM ratings WHERE model_name = ?", (model_name,))

    # In-memory state during replay
    player_ratings: dict[int, object] = {}        # player_id → current Rating
    player_last_played: dict[int, str] = {}       # player_id → ISO date string
    player_n_matches: dict[int, int] = {}         # player_id → cumulative count
    player_first_division: dict[int, str | None] = {}    # cached first-division per player (for starting μ)
    player_primary_division: dict[int, str | None] = {}  # cached most-common division (for cap/floor)

    n_matches = 0

    with db_conn:
        for m in _iter_active_matches(db_conn):
            player_ids = (
                m.side_a_player1_id, m.side_a_player2_id,
                m.side_b_player1_id, m.side_b_player2_id,
            )

            # Get-or-create rating, applying sigma drift on inactivity.
            # New players' starting μ is division-specific (T-P0-011).
            for pid in player_ids:
                if pid not in player_ratings:
                    first_div = _player_first_division(db_conn, pid)
                    player_first_division[pid] = first_div
                    # Compute primary division ONCE per player (used for caps).
                    # Falls back to first_div if there's no clear primary
                    # (single-match player).
                    primary_div = _player_primary_division(db_conn, pid) or first_div
                    player_primary_division[pid] = primary_div
                    starting_mu = division_starting_mu(first_div)
                    player_ratings[pid] = model.rating(mu=starting_mu)
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

            # Predict expected outcome BEFORE the rate() call — needed for
            # the upset-amplification multiplier. predict_win returns
            # win-probability per team given current ratings.
            try:
                predicted_win = model.predict_win([team_a, team_b])
                e_a = predicted_win[0]
            except Exception:
                # Defensive: if predict_win is unavailable / errors, fall back
                # to "expect a draw" so K_upset reduces to surprise = |S - 0.5|
                e_a = 0.5

            # OpenSkill rate: higher score = better outcome
            new_a, new_b = model.rate([team_a, team_b], scores=[s_a, s_b])

            # Combined K-multiplier (T-P0-011 + T-P0-012 + upset amp + v2):
            # K = K_division × K_volume × K_upset
            # v2: K_division is per-PLAYER (mixed-doubles "Division N" matches
            # use each player's gendered-primary tier instead of defaulting to 1.0).
            # We average across the 4 players for a single K_div per match
            # (simple; could also do per-player if needed).
            k_div_per_player = [
                division_k_multiplier_for_match(db_conn, m.division, pid)
                for pid in player_ids
            ]
            k_div = sum(k_div_per_player) / 4.0
            total_games = m.side_a_games + m.side_b_games
            k_vol = volume_k_multiplier(total_games, walkover=m.walkover)
            k_ups = upset_k_multiplier(s_a, e_a)
            k_combined = k_div * k_vol * k_ups

            # Time-decay weighting: old matches contribute less. Combined with
            # K above, so newer matches get the full effect of all multipliers
            # while older matches taper out. Recommended τ ≈ 365d (see
            # _ANALYSIS_/model_evaluation/SUMMARY.md backtest results).
            if decay_anchor and decay_tau_days:
                from datetime import date
                age_days = max(
                    0,
                    (date.fromisoformat(decay_anchor)
                     - date.fromisoformat(m.played_on)).days,
                )
                k_combined *= math.exp(-age_days / decay_tau_days)

            # Apply K_combined to scale the OpenSkill-recommended delta.
            # OpenSkill doesn't expose a per-match K-factor, so we scale
            # the post-update delta manually (both μ and σ — less σ
            # shrinkage when K<1, since less of the update is applied).
            old_objs = (
                player_ratings[m.side_a_player1_id],
                player_ratings[m.side_a_player2_id],
                player_ratings[m.side_b_player1_id],
                player_ratings[m.side_b_player2_id],
            )
            new_objs = (new_a[0], new_a[1], new_b[0], new_b[1])

            # v2: NO clipping (caps removed). Math flows free; class-based
            # display sort handles tier ordering.
            # Step 1: scale OpenSkill delta by K_combined.
            scaled_pre = []
            for pid, old, new in zip(player_ids, old_objs, new_objs):
                adj_mu = old.mu + k_combined * (new.mu - old.mu)
                adj_sigma = old.sigma + k_combined * (new.sigma - old.sigma)
                scaled_pre.append((pid, old, adj_mu, adj_sigma))

            # Step 2: apply partner-weighted Δμ within each team
            # (per friend's research §7) — stronger partner moves more.
            scaled_objs = []
            if PARTNER_WEIGHT_ENABLED:
                # Team A: side_a_player1 + side_a_player2
                a1_pid, a1_old, a1_mu_pre, a1_sigma = scaled_pre[0]
                a2_pid, a2_old, a2_mu_pre, a2_sigma = scaled_pre[1]
                a1_mu_w, a2_mu_w = apply_partner_weighting(
                    a1_old.mu, a2_old.mu, a1_mu_pre, a2_mu_pre
                )
                # Team B: side_b_player1 + side_b_player2
                b1_pid, b1_old, b1_mu_pre, b1_sigma = scaled_pre[2]
                b2_pid, b2_old, b2_mu_pre, b2_sigma = scaled_pre[3]
                b1_mu_w, b2_mu_w = apply_partner_weighting(
                    b1_old.mu, b2_old.mu, b1_mu_pre, b2_mu_pre
                )

                scaled_objs = [
                    model.rating(mu=a1_mu_w, sigma=a1_sigma),
                    model.rating(mu=a2_mu_w, sigma=a2_sigma),
                    model.rating(mu=b1_mu_w, sigma=b1_sigma),
                    model.rating(mu=b2_mu_w, sigma=b2_sigma),
                ]
            else:
                for _, _, mu, sigma in scaled_pre:
                    scaled_objs.append(model.rating(mu=mu, sigma=sigma))

            player_ratings[m.side_a_player1_id] = scaled_objs[0]
            player_ratings[m.side_a_player2_id] = scaled_objs[1]
            player_ratings[m.side_b_player1_id] = scaled_objs[2]
            player_ratings[m.side_b_player2_id] = scaled_objs[3]

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
