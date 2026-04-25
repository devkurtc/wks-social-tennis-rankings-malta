"""Tests for the rating helpers (T-P0-006 partial — score helper only).

The full `recompute_all` integration tests land with T-P0-006 once
the parser (T-P0-004) has loaded matches and openskill is installed.
This file pre-lands the pure-helper tests so the universal-score
formula has regression coverage from day one.

Run from repo root:
    python -m unittest scripts.phase0.test_rating
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import rating  # noqa: E402


class TestUniversalScore(unittest.TestCase):
    """Per PLAN.md §5.2 (revised) and `_RESEARCH_/...` §4."""

    def test_dominant_win_is_one(self):
        # 6-0 6-0 → games 12 vs 0 → S = 1.0
        self.assertEqual(rating.universal_score(12, 0), 1.0)

    def test_whitewash_loss_is_zero(self):
        self.assertEqual(rating.universal_score(0, 12), 0.0)

    def test_even_split_is_half(self):
        # 7-6 6-7 (games 13 vs 13) → draw, no rating movement
        self.assertEqual(rating.universal_score(13, 13), 0.5)

    def test_comfortable_win(self):
        # 6-3 6-2 → 12 vs 5 → S ≈ 0.706
        self.assertAlmostEqual(rating.universal_score(12, 5), 12 / 17, places=4)

    def test_narrow_win(self):
        # 7-6 7-5 → 14 vs 11 → S = 0.56
        self.assertAlmostEqual(rating.universal_score(14, 11), 14 / 25, places=4)

    def test_eighteen_game_format_normalizes_naturally(self):
        # 11-7 in an 18-game event → 11/18 = 0.611, no special handling
        self.assertAlmostEqual(rating.universal_score(11, 7), 11 / 18, places=4)
        # 18-0 max
        self.assertEqual(rating.universal_score(18, 0), 1.0)

    def test_walkover_winner_is_zero_point_nine(self):
        # Per PLAN.md §5.2: walkovers preserve some uncertainty
        # Side that "won" has games_won > 0 (or 6, conventionally)
        self.assertEqual(rating.universal_score(6, 0, walkover=True), 0.90)

    def test_walkover_loser_is_zero_point_one(self):
        self.assertEqual(rating.universal_score(0, 6, walkover=True), 0.10)

    def test_zero_zero_data_error_returns_half(self):
        # Defensive: if both sides have 0 games (shouldn't happen, but
        # avoid divide-by-zero), treat as uninformative draw
        self.assertEqual(rating.universal_score(0, 0), 0.5)


class TestPeriodsBetween(unittest.TestCase):
    def test_zero_when_dates_equal(self):
        self.assertEqual(rating._periods_between("2025-06-01", "2025-06-01", 30), 0)

    def test_zero_when_to_before_from(self):
        self.assertEqual(rating._periods_between("2025-08-01", "2025-06-01", 30), 0)

    def test_one_period_at_30_days(self):
        self.assertEqual(rating._periods_between("2025-06-01", "2025-07-01", 30), 1)

    def test_three_periods_at_90_days(self):
        # June 1 → Aug 30 = 90 days; 90 // 30 = 3 periods
        self.assertEqual(rating._periods_between("2025-06-01", "2025-08-30", 30), 3)

    def test_handles_none_inputs(self):
        # last_played might be None for never-seen players
        self.assertEqual(rating._periods_between(None, "2025-06-01", 30), 0)


class TestRecomputeAll(unittest.TestCase):
    """Integration: load a tiny fixture and verify rating engine end-to-end."""

    def setUp(self):
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).parent))
        import db

        self.conn = db.init_db(":memory:")
        self.conn.execute("INSERT INTO clubs (id, name, slug) VALUES (1, 'VLTC', 'vltc')")
        self.conn.execute(
            "INSERT INTO source_files (id, club_id, original_filename, sha256) "
            "VALUES (1, 1, 'fixture.xlsx', 'fixture')"
        )
        self.conn.execute(
            "INSERT INTO ingestion_runs (id, source_file_id, status, started_at) "
            "VALUES (1, 1, 'completed', '2025-01-01')"
        )
        self.conn.execute(
            "INSERT INTO tournaments (id, club_id, name, year, format, source_file_id) "
            "VALUES (1, 1, 'Fixture', 2025, 'doubles_division', 1)"
        )
        # 4 players, all start at default OpenSkill rating
        for pid, name in [(1, "P1"), (2, "P2"), (3, "P3"), (4, "P4")]:
            self.conn.execute(
                "INSERT INTO players (id, canonical_name) VALUES (?, ?)", (pid, name)
            )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _add_match(self, match_id: int, played_on: str, side_a_games: int, side_b_games: int, walkover: bool = False):
        self.conn.execute(
            "INSERT INTO matches (id, tournament_id, played_on, ingestion_run_id, walkover) "
            "VALUES (?, 1, ?, 1, ?)",
            (match_id, played_on, 1 if walkover else 0),
        )
        self.conn.execute(
            "INSERT INTO match_sides (match_id, side, player1_id, player2_id, games_won, won) "
            "VALUES (?, 'A', 1, 2, ?, ?)",
            (match_id, side_a_games, 1 if side_a_games > side_b_games else 0),
        )
        self.conn.execute(
            "INSERT INTO match_sides (match_id, side, player1_id, player2_id, games_won, won) "
            "VALUES (?, 'B', 3, 4, ?, ?)",
            (match_id, side_b_games, 1 if side_b_games > side_a_games else 0),
        )
        self.conn.commit()

    def test_single_match_produces_4_history_rows_and_4_rating_rows(self):
        self._add_match(1, "2025-06-01", 6, 3)  # team A wins decisively
        n = rating.recompute_all(self.conn, model_name="test_model")
        self.assertEqual(n, 1)

        n_hist = self.conn.execute(
            "SELECT COUNT(*) FROM rating_history WHERE model_name = 'test_model'"
        ).fetchone()[0]
        self.assertEqual(n_hist, 4)

        n_rate = self.conn.execute(
            "SELECT COUNT(*) FROM ratings WHERE model_name = 'test_model'"
        ).fetchone()[0]
        self.assertEqual(n_rate, 4)

    def test_winners_mu_increases_losers_decreases(self):
        self._add_match(1, "2025-06-01", 12, 0)  # whitewash for A
        rating.recompute_all(self.conn, model_name="test_model")
        rows = self.conn.execute(
            "SELECT player_id, mu FROM ratings WHERE model_name = 'test_model' ORDER BY player_id"
        ).fetchall()
        # Players 1, 2 (side A) should have mu > default (25); 3, 4 (side B) < 25
        self.assertGreater(rows[0][1], 25.0)  # P1
        self.assertGreater(rows[1][1], 25.0)  # P2
        self.assertLess(rows[2][1], 25.0)     # P3
        self.assertLess(rows[3][1], 25.0)     # P4

    def test_recompute_is_idempotent(self):
        self._add_match(1, "2025-06-01", 6, 3)
        self._add_match(2, "2025-06-02", 4, 6)
        rating.recompute_all(self.conn, model_name="test_model")
        rows1 = self.conn.execute(
            "SELECT player_id, mu, sigma FROM ratings WHERE model_name = 'test_model' ORDER BY player_id"
        ).fetchall()
        rating.recompute_all(self.conn, model_name="test_model")
        rows2 = self.conn.execute(
            "SELECT player_id, mu, sigma FROM ratings WHERE model_name = 'test_model' ORDER BY player_id"
        ).fetchall()
        self.assertEqual(rows1, rows2)
        # And only 4 rating rows (not 8 — the wipe worked)
        self.assertEqual(len(rows2), 4)

    def test_superseded_matches_excluded(self):
        self._add_match(1, "2025-06-01", 6, 3)
        # Mark this match as superseded
        self.conn.execute(
            "INSERT INTO ingestion_runs (id, source_file_id, status, started_at) "
            "VALUES (2, 1, 'completed', '2025-06-02')"
        )
        self.conn.execute(
            "UPDATE matches SET superseded_by_run_id = 2 WHERE id = 1"
        )
        self.conn.commit()
        n = rating.recompute_all(self.conn, model_name="test_model")
        self.assertEqual(n, 0)

    def test_walkover_uses_dampened_score(self):
        # Walkover with winner_games=6, loser_games=0
        self._add_match(1, "2025-06-01", 6, 0, walkover=True)
        rating.recompute_all(self.conn, model_name="test_model_walk")
        # And a regular 6-0 6-0 (whitewash, real match)
        self._add_match(2, "2025-06-01", 12, 0, walkover=False)
        rating.recompute_all(self.conn, model_name="test_model_real")
        # Walkover should produce SMALLER mu shift than a real whitewash
        walk_p1 = self.conn.execute(
            "SELECT mu FROM ratings WHERE model_name = 'test_model_walk' AND player_id = 1"
        ).fetchone()[0]
        real_p1 = self.conn.execute(
            "SELECT mu FROM ratings WHERE model_name = 'test_model_real' AND player_id = 1"
        ).fetchone()[0]
        self.assertLess(walk_p1, real_p1)  # walkover gives less of a boost


if __name__ == "__main__":
    unittest.main()
