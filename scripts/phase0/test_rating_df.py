"""Tests for the DF Glicko-2 challenger rating engine.

Mirrors the structure of test_rating.py.

Run from repo root:
    python -m unittest scripts.phase0.test_rating_df
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import rating_df


class TestGlicko2Helpers(unittest.TestCase):
    """Pure-function coverage for the Glicko-2 math layer."""

    def test_g_at_zero_phi_is_one(self):
        # When opponent RD converts to φ=0, g(0) = 1 (no uncertainty discount)
        self.assertAlmostEqual(rating_df._g(0.0), 1.0, places=6)

    def test_g_decreases_with_phi(self):
        # More uncertain opponent → lower g → update is discounted
        self.assertGreater(rating_df._g(0.5), rating_df._g(1.0))
        self.assertGreater(rating_df._g(1.0), rating_df._g(2.0))

    def test_E_at_equal_ratings_is_half(self):
        # Equal μ, any φ_j → E = 0.5
        self.assertAlmostEqual(rating_df._E(0.0, 0.0, 1.0), 0.5, places=6)

    def test_E_favours_stronger_player(self):
        # μ > μ_j → E > 0.5 (self is stronger, expected to win)
        self.assertGreater(rating_df._E(1.0, 0.0, 1.0), 0.5)
        # μ < μ_j → E < 0.5
        self.assertLess(rating_df._E(-1.0, 0.0, 1.0), 0.5)

    def test_to_internal_and_back(self):
        r, rd = 1600.0, 200.0
        mu, phi = rating_df._to_internal(r, rd)
        r2, rd2 = rating_df._to_external(mu, phi)
        self.assertAlmostEqual(r2, r, places=4)
        self.assertAlmostEqual(rd2, rd, places=4)

    def test_team_aggregate_equal_partners(self):
        r, rd = rating_df._team_aggregate(1500.0, 100.0, 1500.0, 100.0)
        self.assertAlmostEqual(r, 1500.0, places=4)
        self.assertAlmostEqual(rd, 100.0, places=4)

    def test_team_aggregate_rms_rd(self):
        # RD = rms of partners: sqrt((100² + 200²) / 2)
        _, rd = rating_df._team_aggregate(1500.0, 100.0, 1500.0, 200.0)
        expected = math.sqrt((100.0 ** 2 + 200.0 ** 2) / 2.0)
        self.assertAlmostEqual(rd, expected, places=4)

    def test_drift_rd_grows_with_periods(self):
        rd = 100.0
        rd1 = rating_df._drift_rd(rd, 1)
        rd3 = rating_df._drift_rd(rd, 3)
        self.assertGreater(rd1, rd)
        self.assertGreater(rd3, rd1)

    def test_drift_rd_capped_at_max(self):
        # Very long gap should not exceed MAX_RD
        rd_drifted = rating_df._drift_rd(rating_df.MIN_RD, 10000)
        self.assertLessEqual(rd_drifted, rating_df.MAX_RD)

    def test_drift_rd_zero_periods_unchanged(self):
        rd = 150.0
        self.assertEqual(rating_df._drift_rd(rd, 0), rd)


class TestGlicko2Update(unittest.TestCase):
    """Single-match update behaves correctly."""

    def test_winner_gains_rating(self):
        r_new, _ = rating_df.glicko2_update(1500.0, 200.0, 1500.0, 200.0, 1.0)
        self.assertGreater(r_new, 1500.0)

    def test_loser_loses_rating(self):
        r_new, _ = rating_df.glicko2_update(1500.0, 200.0, 1500.0, 200.0, 0.0)
        self.assertLess(r_new, 1500.0)

    def test_draw_does_not_move_equal_players(self):
        # s=0.5 against identical opponent → μ unchanged (Δ = 0)
        r_new, _ = rating_df.glicko2_update(1500.0, 200.0, 1500.0, 200.0, 0.5)
        self.assertAlmostEqual(r_new, 1500.0, places=4)

    def test_rd_shrinks_after_match(self):
        _, rd_new = rating_df.glicko2_update(1500.0, 300.0, 1500.0, 300.0, 1.0)
        self.assertLess(rd_new, 300.0)

    def test_rd_floor_respected(self):
        # Even with many wins, RD should never fall below MIN_RD
        r, rd = 1500.0, rating_df.MIN_RD + 0.01
        _, rd_new = rating_df.glicko2_update(r, rd, 1200.0, 30.0, 1.0)
        self.assertGreaterEqual(rd_new, rating_df.MIN_RD)

    def test_upset_moves_rating_more(self):
        # Upset: weaker player (r=1300) beats stronger opponent (r=1700)
        # Expected score is low (≈0.09), actual = 1.0 → big upward jump
        r_upset, _ = rating_df.glicko2_update(1300.0, 200.0, 1700.0, 200.0, 1.0)
        # Normal win: equal players
        r_normal, _ = rating_df.glicko2_update(1500.0, 200.0, 1500.0, 200.0, 1.0)
        # Upset winner gains more rating points above starting point
        self.assertGreater(r_upset - 1300.0, r_normal - 1500.0)


class TestDivisionStartingR(unittest.TestCase):
    def test_tier_ordering(self):
        m1 = rating_df._division_starting_r("Men Div 1")
        m2 = rating_df._division_starting_r("Men Div 2")
        m3 = rating_df._division_starting_r("Men Div 3")
        m4 = rating_df._division_starting_r("Men Div 4")
        self.assertGreater(m1, m2)
        self.assertGreater(m2, m3)
        self.assertGreater(m3, m4)

    def test_men_a_equals_men_div_1(self):
        self.assertEqual(
            rating_df._division_starting_r("Men A"),
            rating_df._division_starting_r("Men Div 1"),
        )

    def test_unknown_returns_default(self):
        self.assertEqual(rating_df._division_starting_r(None), rating_df.DEFAULT_R)
        self.assertEqual(rating_df._division_starting_r("Unknown"), rating_df.DEFAULT_R)


class TestRecomputeAll(unittest.TestCase):
    """Integration: small synthetic fixture, known ordering."""

    def setUp(self):
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
        for pid, name in [(1, "P1"), (2, "P2"), (3, "P3"), (4, "P4")]:
            self.conn.execute(
                "INSERT INTO players (id, canonical_name) VALUES (?, ?)", (pid, name)
            )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _add_match(self, match_id, played_on, side_a_games, side_b_games, walkover=False):
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
        self._add_match(1, "2025-06-01", 6, 3)
        n = rating_df.recompute_all(self.conn)
        self.assertEqual(n, 1)
        n_hist = self.conn.execute(
            "SELECT COUNT(*) FROM rating_history WHERE model_name = ?",
            (rating_df.DF_MODEL,),
        ).fetchone()[0]
        self.assertEqual(n_hist, 4)
        n_rate = self.conn.execute(
            "SELECT COUNT(*) FROM ratings WHERE model_name = ?",
            (rating_df.DF_MODEL,),
        ).fetchone()[0]
        self.assertEqual(n_rate, 4)

    def test_winners_rating_increases_losers_decreases(self):
        self._add_match(1, "2025-06-01", 12, 0)
        rating_df.recompute_all(self.conn)
        rows = self.conn.execute(
            "SELECT player_id, mu FROM ratings WHERE model_name = ? ORDER BY player_id",
            (rating_df.DF_MODEL,),
        ).fetchall()
        # P1, P2 won → r > DEFAULT_R; P3, P4 lost → r < DEFAULT_R
        self.assertGreater(rows[0][1], rating_df.DEFAULT_R)
        self.assertGreater(rows[1][1], rating_df.DEFAULT_R)
        self.assertLess(rows[2][1], rating_df.DEFAULT_R)
        self.assertLess(rows[3][1], rating_df.DEFAULT_R)

    def test_recompute_is_idempotent(self):
        self._add_match(1, "2025-06-01", 6, 3)
        self._add_match(2, "2025-06-02", 4, 6)
        rating_df.recompute_all(self.conn)
        rows1 = self.conn.execute(
            "SELECT player_id, mu, sigma FROM ratings WHERE model_name = ? ORDER BY player_id",
            (rating_df.DF_MODEL,),
        ).fetchall()
        rating_df.recompute_all(self.conn)
        rows2 = self.conn.execute(
            "SELECT player_id, mu, sigma FROM ratings WHERE model_name = ? ORDER BY player_id",
            (rating_df.DF_MODEL,),
        ).fetchall()
        self.assertEqual(rows1, rows2)
        self.assertEqual(len(rows2), 4)

    def test_does_not_mutate_openskill_pl_rows(self):
        """DF recompute must not touch openskill_pl rows."""
        import rating as kc_rating
        self._add_match(1, "2025-06-01", 6, 3)
        kc_rating.recompute_all(self.conn, model_name="openskill_pl")
        kc_before = self.conn.execute(
            "SELECT player_id, mu, sigma FROM ratings "
            "WHERE model_name = 'openskill_pl' ORDER BY player_id"
        ).fetchall()
        # Now run DF recompute
        rating_df.recompute_all(self.conn)
        kc_after = self.conn.execute(
            "SELECT player_id, mu, sigma FROM ratings "
            "WHERE model_name = 'openskill_pl' ORDER BY player_id"
        ).fetchall()
        self.assertEqual(kc_before, kc_after, "DF recompute must not touch openskill_pl rows")

    def test_known_ordering_dominant_winner(self):
        """After repeated wins, consistent winners rank higher than consistent losers."""
        for i in range(1, 6):
            self._add_match(i, f"2025-0{i+1}-01", 12, 0)
        rating_df.recompute_all(self.conn)
        rows = {
            pid: mu
            for pid, mu in self.conn.execute(
                "SELECT player_id, mu FROM ratings WHERE model_name = ?",
                (rating_df.DF_MODEL,),
            ).fetchall()
        }
        self.assertGreater(rows[1], rows[3])  # P1 (won 5x) > P3 (lost 5x)

    def test_superseded_match_excluded(self):
        self._add_match(1, "2025-06-01", 6, 3)
        self.conn.execute(
            "INSERT INTO ingestion_runs (id, source_file_id, status, started_at) "
            "VALUES (2, 1, 'completed', '2025-06-02')"
        )
        self.conn.execute("UPDATE matches SET superseded_by_run_id = 2 WHERE id = 1")
        self.conn.commit()
        n = rating_df.recompute_all(self.conn)
        self.assertEqual(n, 0)

    def test_walkover_produces_smaller_shift_than_real_match(self):
        self._add_match(1, "2025-06-01", 6, 0, walkover=True)
        rating_df.recompute_all(self.conn, model_name="df_walk_test")
        self._add_match(2, "2025-06-01", 12, 0, walkover=False)
        rating_df.recompute_all(self.conn, model_name="df_real_test")
        walk_r = self.conn.execute(
            "SELECT mu FROM ratings WHERE model_name = 'df_walk_test' AND player_id = 1"
        ).fetchone()[0]
        real_r = self.conn.execute(
            "SELECT mu FROM ratings WHERE model_name = 'df_real_test' AND player_id = 1"
        ).fetchone()[0]
        self.assertLess(walk_r, real_r)

    def test_rd_shrinks_with_matches(self):
        """More matches → lower RD (more certainty)."""
        for i in range(1, 8):
            self._add_match(i, f"2025-0{i}-01", 6, 3)
        rating_df.recompute_all(self.conn)
        rd = self.conn.execute(
            "SELECT sigma FROM ratings WHERE model_name = ? AND player_id = 1",
            (rating_df.DF_MODEL,),
        ).fetchone()[0]
        self.assertLess(rd, rating_df.DEFAULT_RD)

    def test_model_name_override(self):
        """recompute_all respects the model_name= argument."""
        self._add_match(1, "2025-06-01", 6, 3)
        rating_df.recompute_all(self.conn, model_name="df_test_override")
        rows = self.conn.execute(
            "SELECT COUNT(*) FROM ratings WHERE model_name = 'df_test_override'"
        ).fetchone()[0]
        self.assertEqual(rows, 4)
        # Default DF_MODEL should have zero rows
        rows_default = self.conn.execute(
            "SELECT COUNT(*) FROM ratings WHERE model_name = ?",
            (rating_df.DF_MODEL,),
        ).fetchone()[0]
        self.assertEqual(rows_default, 0)


if __name__ == "__main__":
    unittest.main()
