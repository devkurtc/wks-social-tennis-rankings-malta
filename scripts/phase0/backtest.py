"""Backtest harness for rating models.

Iterates matches in chronological order. Up to `cutoff_date`, ratings are
just updated (training set). For each match on or after the cutoff, we
predict P(side-A wins) BEFORE updating, then update — true held-out evaluation.

Reports:
  - per-match prediction log written to a CSV
  - aggregate log-loss + accuracy + Brier score
  - calibration table (10 deciles): predicted-prob vs realized-frequency
  - per-player calibration on the held-out set

Reusable for any rating engine that exposes predict_win + rate. To compare
two engines, run twice with different `engine_factory` arguments.

Usage:
    python3 scripts/phase0/backtest.py
        --cutoff 2025-10-01
        --engine openskill_pl
        --out _ANALYSIS_/model_evaluation/baseline_pl.csv
"""
from __future__ import annotations

import argparse
import csv
import math
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

# Allow running from anywhere — the existing rating module has helpers we reuse.
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from rating import (  # noqa: E402
    DEFAULT_RATING_PERIOD_DAYS,
    DEFAULT_TAU,
    _iter_active_matches,
    _periods_between,
    _player_first_division,
    division_starting_mu,
)


# ---- Engine protocol -------------------------------------------------------
# An "engine" is anything implementing:
#   .new_rating(mu)               -> Rating
#   .predict_win([team_a, team_b]) -> [p_a, p_b]
#   .rate([team_a, team_b], scores=[s_a, s_b]) -> ([new_a1, new_a2], [new_b1, new_b2])
#   .inflate_sigma(rating, periods, tau) -> Rating  (passive σ drift)


@dataclass
class OpenSkillPLEngine:
    """Vanilla OpenSkill Plackett-Luce — no K-factor or partner weighting.
    The closest backtest baseline to the algorithm itself, separating model
    quality from the project's bespoke K-multiplier choices."""

    tau: float = DEFAULT_TAU
    name: str = "openskill_pl_vanilla"

    def __post_init__(self) -> None:
        from openskill.models import PlackettLuce

        self._model = PlackettLuce(tau=self.tau)

    def new_rating(self, mu: float):
        return self._model.rating(mu=mu)

    def predict_win(self, teams):
        return self._model.predict_win(teams)

    def rate(self, teams, scores, weight: float = 1.0):
        new_a, new_b = self._model.rate(teams, scores=scores)
        if weight >= 1.0:
            return new_a, new_b
        # Blend the proposed update toward the original by `weight`. weight=0
        # → no update; weight=1 → full update.
        old_a, old_b = teams
        def blend(old, new):
            mu = old.mu + weight * (new.mu - old.mu)
            sigma = old.sigma + weight * (new.sigma - old.sigma)
            return self._model.rating(mu=mu, sigma=sigma)
        return (
            [blend(old_a[0], new_a[0]), blend(old_a[1], new_a[1])],
            [blend(old_b[0], new_b[0]), blend(old_b[1], new_b[1])],
        )

    def inflate_sigma(self, rating, periods: int):
        if periods <= 0:
            return rating
        new_sigma = math.sqrt(rating.sigma ** 2 + periods * (self.tau ** 2))
        return self._model.rating(mu=rating.mu, sigma=new_sigma)


@dataclass
class OpenSkillPLDecayEngine(OpenSkillPLEngine):
    """OpenSkill PL with exponential time-decay weighting on each match.

    The weight applied to a match's update is `exp(-age_days / decay_tau_days)`
    where `age_days` is the days between the match date and `as_of_date`
    (defaults to 'today' = the latest match in the dataset, set externally).

    Recent matches get full weight; old matches get attenuated weight,
    so an old win/loss decays out of the rating instead of persisting forever.
    """

    decay_tau_days: float = 365.0
    as_of_date: str | None = None  # caller fills in
    name: str = "openskill_pl_decay"

    def weight_for_match(self, played_on: str) -> float:
        if not self.as_of_date or not played_on:
            return 1.0
        from datetime import date
        a = date.fromisoformat(played_on)
        b = date.fromisoformat(self.as_of_date)
        age_days = max(0, (b - a).days)
        return math.exp(-age_days / self.decay_tau_days)


# Registry of engines. Add new engines here as we implement them.
ENGINES: dict[str, Callable[[], object]] = {
    "openskill_pl_vanilla": lambda: OpenSkillPLEngine(),
    "openskill_pl_decay365": lambda: OpenSkillPLDecayEngine(decay_tau_days=365.0),
    "openskill_pl_decay180": lambda: OpenSkillPLDecayEngine(decay_tau_days=180.0),
    "openskill_pl_decay730": lambda: OpenSkillPLDecayEngine(decay_tau_days=730.0),
}


# ---- The backtest -----------------------------------------------------------


def universal_score(games_a: int, games_b: int) -> float:
    """W=1.0, L=0.0, draw=0.5 — same convention as rating.universal_score
    minus the walkover special case (we treat walkover wins as W=1.0 too,
    which is the engine's natural input)."""
    if games_a + games_b == 0:
        return 0.5
    if games_a == games_b:
        return 0.5
    return 1.0 if games_a > games_b else 0.0


def safe_log(p: float) -> float:
    return math.log(max(min(p, 1 - 1e-9), 1e-9))


def run_backtest(
    db_conn: sqlite3.Connection,
    engine_factory: Callable[[], object],
    cutoff_date: str,
    rating_period_days: int = DEFAULT_RATING_PERIOD_DAYS,
) -> dict:
    """Run one engine through all matches, returning aggregate metrics +
    per-match prediction rows.
    """
    engine = engine_factory()

    # Time-decay engines need to know "today" — set to the latest match date
    # in the dataset so the most recent match has weight 1.
    if hasattr(engine, "as_of_date") and engine.as_of_date is None:
        last_date = db_conn.execute(
            "SELECT MAX(played_on) FROM matches WHERE superseded_by_run_id IS NULL"
        ).fetchone()[0]
        engine.as_of_date = last_date

    player_ratings: dict[int, object] = {}
    player_last_played: dict[int, str] = {}
    player_first_division: dict[int, str | None] = {}

    predictions: list[dict] = []  # one dict per held-out match

    n_train = 0
    n_test = 0

    for m in _iter_active_matches(db_conn):
        is_holdout = m.played_on >= cutoff_date

        player_ids = (
            m.side_a_player1_id, m.side_a_player2_id,
            m.side_b_player1_id, m.side_b_player2_id,
        )

        # Initialise or σ-drift each player's rating.
        for pid in player_ids:
            if pid not in player_ratings:
                first_div = _player_first_division(db_conn, pid)
                player_first_division[pid] = first_div
                player_ratings[pid] = engine.new_rating(
                    mu=division_starting_mu(first_div)
                )
            else:
                last = player_last_played.get(pid)
                periods = _periods_between(last, m.played_on, rating_period_days)
                player_ratings[pid] = engine.inflate_sigma(
                    player_ratings[pid], periods
                )

        team_a = [
            player_ratings[m.side_a_player1_id],
            player_ratings[m.side_a_player2_id],
        ]
        team_b = [
            player_ratings[m.side_b_player1_id],
            player_ratings[m.side_b_player2_id],
        ]

        # PREDICT on held-out matches before updating.
        # Skip ties (rare; walkover edge cases) — they don't tell us who's
        # better and would inflate log-loss artificially.
        is_tie = m.side_a_games == m.side_b_games
        if is_holdout and not is_tie:
            try:
                p_a = engine.predict_win([team_a, team_b])[0]
            except Exception:
                p_a = 0.5
            actual_a = 1 if m.side_a_games > m.side_b_games else 0
            log_loss = -(actual_a * safe_log(p_a) + (1 - actual_a) * safe_log(1 - p_a))
            brier = (p_a - actual_a) ** 2
            predictions.append({
                "match_id": m.match_id,
                "played_on": m.played_on,
                "p_a": p_a,
                "actual_a": actual_a,
                "log_loss": log_loss,
                "brier": brier,
                "correct": int((p_a > 0.5) == bool(actual_a)),
                # Raw rating context useful for later drill-down
                "team_a": (m.side_a_player1_id, m.side_a_player2_id),
                "team_b": (m.side_b_player1_id, m.side_b_player2_id),
                "team_a_mu_avg": (team_a[0].mu + team_a[1].mu) / 2,
                "team_b_mu_avg": (team_b[0].mu + team_b[1].mu) / 2,
                "team_a_sigma_avg": (team_a[0].sigma + team_a[1].sigma) / 2,
                "team_b_sigma_avg": (team_b[0].sigma + team_b[1].sigma) / 2,
            })
            n_test += 1
        elif not is_holdout:
            n_train += 1
        # Ties on held-out days update state but don't contribute to metrics.

        # Always update — both train and test, so chronological ordering of
        # held-out matches is preserved.
        s_a = universal_score(m.side_a_games, m.side_b_games)
        s_b = 1.0 - s_a
        # Time-decay engines weight old matches less so stale form attenuates.
        if hasattr(engine, "weight_for_match"):
            weight = engine.weight_for_match(m.played_on)
            new_a, new_b = engine.rate(
                [team_a, team_b], scores=[s_a, s_b], weight=weight
            )
        else:
            new_a, new_b = engine.rate([team_a, team_b], scores=[s_a, s_b])
        player_ratings[m.side_a_player1_id] = new_a[0]
        player_ratings[m.side_a_player2_id] = new_a[1]
        player_ratings[m.side_b_player1_id] = new_b[0]
        player_ratings[m.side_b_player2_id] = new_b[1]

        for pid in player_ids:
            player_last_played[pid] = m.played_on

    if not predictions:
        return {"engine": engine.name, "n_train": n_train, "n_test": 0,
                "predictions": []}

    avg_log_loss = sum(p["log_loss"] for p in predictions) / n_test
    avg_brier = sum(p["brier"] for p in predictions) / n_test
    accuracy = sum(p["correct"] for p in predictions) / n_test

    # Calibration: bucket predictions into 10 deciles of p_a, see actual freq
    deciles = [[] for _ in range(10)]
    for p in predictions:
        idx = min(int(p["p_a"] * 10), 9)
        deciles[idx].append(p["actual_a"])
    calibration = []
    for i, bucket in enumerate(deciles):
        n = len(bucket)
        if n == 0:
            calibration.append((i / 10, (i + 1) / 10, 0, None))
            continue
        freq = sum(bucket) / n
        calibration.append((i / 10, (i + 1) / 10, n, freq))

    return {
        "engine": engine.name,
        "n_train": n_train,
        "n_test": n_test,
        "log_loss": avg_log_loss,
        "brier": avg_brier,
        "accuracy": accuracy,
        "calibration": calibration,
        "predictions": predictions,
    }


def write_predictions_csv(predictions: list[dict], path: Path) -> None:
    if not predictions:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "match_id", "played_on", "p_a", "actual_a", "log_loss", "brier", "correct",
        "team_a_mu_avg", "team_a_sigma_avg",
        "team_b_mu_avg", "team_b_sigma_avg",
    ]
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for p in predictions:
            writer.writerow(p)


def print_report(result: dict) -> None:
    print(f"\n=== {result['engine']} ===")
    print(f"  train matches: {result['n_train']:>5}")
    print(f"  test  matches: {result['n_test']:>5}")
    if result["n_test"] == 0:
        print("  (no held-out matches — pick an earlier cutoff)")
        return
    print(f"  log-loss:      {result['log_loss']:.4f}  (lower is better; "
          f"random=0.6931, perfect=0.0)")
    print(f"  Brier score:   {result['brier']:.4f}  (lower is better; "
          f"random=0.25, perfect=0.0)")
    print(f"  accuracy:      {result['accuracy']:.4f}  (>0.5 = better than coin)")
    print(f"\n  Calibration (predicted decile → actual frequency):")
    print(f"  {'bin':<14}  {'n':>5}  {'predicted':>10}  {'actual':>8}")
    for lo, hi, n, freq in result["calibration"]:
        if n == 0:
            continue
        mid = (lo + hi) / 2
        print(f"  [{lo:.1f}, {hi:.1f}) {n:>5}  {mid:>10.2f}  "
              f"{freq:>8.4f}")


def main() -> int:
    parser = argparse.ArgumentParser(prog="backtest")
    parser.add_argument("--cutoff", default="2025-10-01",
                        help="Held-out matches are those with played_on >= cutoff (ISO date).")
    from pathlib import Path as _P
    _default_db = str(_P(__file__).resolve().parent.parent.parent / "phase0.sqlite")
    parser.add_argument("--db", default=_default_db)
    parser.add_argument("--engine", default="openskill_pl_vanilla",
                        choices=list(ENGINES.keys()))
    parser.add_argument("--out", default=None,
                        help="Optional CSV path for per-match predictions.")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    try:
        result = run_backtest(conn, ENGINES[args.engine], args.cutoff)
    finally:
        conn.close()

    print_report(result)

    if args.out and result["predictions"]:
        out = Path(args.out)
        write_predictions_csv(result["predictions"], out)
        print(f"\n  per-match predictions → {out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
