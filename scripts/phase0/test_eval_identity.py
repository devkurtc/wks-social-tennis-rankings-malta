"""Tests for the identity-eval harness (eval_identity.py).

Run from repo root:
    python -m unittest scripts.phase0.test_eval_identity
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import db  # noqa: E402
import eval_identity as ei  # noqa: E402


def _conn_with_player(name: str, gender: str | None = "M"):
    conn = db.init_db(":memory:")
    conn.execute(
        "INSERT INTO players (canonical_name, gender) VALUES (?, ?)",
        (name, gender),
    )
    return conn


class TestBuildPlayerDict(unittest.TestCase):
    def test_returns_full_dict_when_player_exists(self):
        conn = _conn_with_player("Real Player", gender="M")
        try:
            d = ei._build_player_dict(conn, "Real Player")
            self.assertIsNotNone(d["id"])
            self.assertEqual(d["name"], "Real Player")
            self.assertEqual(d["gender"], "M")
            self.assertEqual(d["n"], 0)        # no matches inserted
            self.assertEqual(d["_first"], "r")
            self.assertIn("real player", d["_key"])
        finally:
            conn.close()

    def test_returns_stub_when_player_missing(self):
        conn = db.init_db(":memory:")
        try:
            d = ei._build_player_dict(conn, "Ghost")
            self.assertIsNone(d["id"])
            self.assertEqual(d["name"], "Ghost")
            self.assertIsNone(d["gender"])
            self.assertEqual(d["_first"], "g")
        finally:
            conn.close()


class TestScorePair(unittest.TestCase):
    def test_identical_names_score_high(self):
        conn = db.init_db(":memory:")
        try:
            out = ei.score_pair(conn, "Same Name", "Same Name")
            self.assertEqual(out["raw_score"], 1.0)
            self.assertGreater(out["confidence"], 0.95)
        finally:
            conn.close()

    def test_typo_pair_scores_above_default_threshold(self):
        conn = db.init_db(":memory:")
        try:
            # One-letter difference; both stub records.
            out = ei.score_pair(conn, "Lillian Baldacchino", "Lillian Badacchino")
            self.assertGreaterEqual(out["confidence"], 0.78)
            self.assertEqual(out["raw_score"] > 0.85, True)
        finally:
            conn.close()

    def test_completely_different_names_score_low(self):
        conn = db.init_db(":memory:")
        try:
            out = ei.score_pair(conn, "Alpha One", "Zulu Nine")
            self.assertLess(out["confidence"], 0.5)
        finally:
            conn.close()

    def test_resolved_flag_reflects_db_lookup(self):
        conn = _conn_with_player("Resolved Player")
        try:
            out = ei.score_pair(conn, "Resolved Player", "Stub Player")
            self.assertTrue(out["a_resolved"])
            self.assertFalse(out["b_resolved"])
        finally:
            conn.close()


class TestLoadPositivePairs(unittest.TestCase):
    def test_yields_winner_loser_per_loser_entry(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump({
                "merges": [
                    {"winner": "W1", "losers": ["L1a", "L1b"]},
                    {"winner": "W2", "losers": ["L2"]},
                    {"winner": "W3", "losers": []},  # empty losers — skip
                    {"losers": ["L4"]},               # missing winner — skip
                ]
            }, f)
            path = f.name
        try:
            pairs = ei.load_positive_pairs(path)
            self.assertEqual(
                pairs, [("W1", "L1a"), ("W1", "L1b"), ("W2", "L2")],
            )
        finally:
            Path(path).unlink()


class TestLoadNegativePairs(unittest.TestCase):
    def test_missing_file_returns_empty(self):
        self.assertEqual(
            ei.load_negative_pairs("/nonexistent/path.json"), [],
        )

    def test_skips_entries_missing_a_or_b(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump({
                "pairs": [
                    {"a": "X", "b": "Y", "reason": "different ppl"},
                    {"a": "X", "reason": "missing b"},
                    {"b": "Y", "reason": "missing a"},
                    {"a": "P", "b": "Q"},
                ]
            }, f)
            path = f.name
        try:
            self.assertEqual(
                ei.load_negative_pairs(path), [("X", "Y"), ("P", "Q")],
            )
        finally:
            Path(path).unlink()


class TestEvaluate(unittest.TestCase):
    def setUp(self):
        # Synthetic ground truth: 2 obvious positives + 1 obvious negative.
        self.aliases = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8",
        )
        json.dump({
            "merges": [
                # Identical name → very high confidence
                {"winner": "Same Person", "losers": ["Same Person"]},
                # Spelling typo → high confidence
                {"winner": "Lillian Baldacchino",
                 "losers": ["Lillian Badacchino"]},
            ]
        }, self.aliases)
        self.aliases.close()

        self.distinct = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8",
        )
        json.dump({
            "pairs": [
                # Different first letters + different surnames → very low conf
                {"a": "Alpha One", "b": "Zulu Nine", "reason": "diff people"},
            ]
        }, self.distinct)
        self.distinct.close()

        self.conn = db.init_db(":memory:")

    def tearDown(self):
        Path(self.aliases.name).unlink(missing_ok=True)
        Path(self.distinct.name).unlink(missing_ok=True)
        self.conn.close()

    def test_high_threshold_separates_positives_from_negatives(self):
        report = ei.evaluate(
            self.conn, self.aliases.name, self.distinct.name,
            thresholds=(0.80,),
        )
        self.assertEqual(report["n_positive"], 2)
        self.assertEqual(report["n_negative"], 1)
        row = report["thresholds"][0]
        # Both positives surface at 0.80
        self.assertEqual(row["tp"], 2)
        self.assertEqual(row["fn"], 0)
        # Negative does NOT surface at 0.80
        self.assertEqual(row["fp"], 0)
        self.assertEqual(row["tn"], 1)
        self.assertEqual(row["recall"], 1.0)
        self.assertEqual(row["fp_rate"], 0.0)
        self.assertEqual(row["precision"], 1.0)

    def test_threshold_zero_admits_everything(self):
        report = ei.evaluate(
            self.conn, self.aliases.name, self.distinct.name,
            thresholds=(0.0,),
        )
        row = report["thresholds"][0]
        self.assertEqual(row["tp"], 2)
        self.assertEqual(row["fp"], 1)

    def test_each_threshold_yields_one_row(self):
        report = ei.evaluate(
            self.conn, self.aliases.name, self.distinct.name,
            thresholds=(0.5, 0.7, 0.9),
        )
        self.assertEqual(len(report["thresholds"]), 3)
        # As threshold rises, TP can only stay same or fall.
        tps = [r["tp"] for r in report["thresholds"]]
        self.assertEqual(tps, sorted(tps, reverse=True))


class TestFormatReport(unittest.TestCase):
    def test_handles_empty_negatives_with_disclaimer(self):
        # Build a minimal report manually.
        report = {
            "n_positive": 3, "n_negative": 0,
            "thresholds": [{
                "threshold": 0.78, "tp": 3, "fn": 0, "fp": 0, "tn": 0,
                "recall": 1.0, "fp_rate": None, "precision": 1.0,
            }],
            "positive_pairs": [],
            "negative_pairs": [],
        }
        out = ei.format_report(report)
        self.assertIn("No negative pairs", out)
        self.assertIn("100.0%", out)

    def test_lists_misses_below_threshold(self):
        report = {
            "n_positive": 1, "n_negative": 0,
            "thresholds": [],
            "positive_pairs": [
                {"a_name": "A", "b_name": "B",
                 "raw_score": 0.5, "confidence": 0.5,
                 "reasons": [], "a_resolved": True, "b_resolved": True},
            ],
            "negative_pairs": [],
        }
        out = ei.format_report(report, miss_threshold=0.78)
        self.assertIn("Misses", out)
        self.assertIn("'A'", out)
        self.assertIn("'B'", out)


class TestProductionDataFile(unittest.TestCase):
    """Snapshot-style guard: today's recall at threshold 0.78 is ~91%
    against the live ground-truth files. This catches regressions in the
    score function without depending on the live DB (uses ":memory:" so
    enrichment is name-only)."""

    def test_recall_at_production_threshold_above_floor(self):
        repo_root = Path(__file__).resolve().parent.parent.parent
        aliases = repo_root / "scripts/phase0/manual_aliases.json"
        distinct = repo_root / "scripts/phase0/known_distinct.json"
        if not aliases.exists():
            self.skipTest("manual_aliases.json not present")

        conn = db.init_db(":memory:")
        try:
            report = ei.evaluate(
                conn, str(aliases), str(distinct), thresholds=(0.78,),
            )
        finally:
            conn.close()
        # 50%+ recall floor — surname-change cases (Vassallo↔Schembri etc)
        # legitimately can't be caught by name similarity alone, so we
        # don't demand a higher floor without a name-only enrichment.
        recall = report["thresholds"][0]["recall"]
        self.assertGreaterEqual(
            recall, 0.50,
            f"Score function regressed: recall@0.78 = {recall:.1%}",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
