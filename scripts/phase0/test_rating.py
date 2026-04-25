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


if __name__ == "__main__":
    unittest.main()
