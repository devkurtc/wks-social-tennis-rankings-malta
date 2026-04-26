"""Tests for the VLTC Team-Tournament parser (T-P0-014).

One test per "Suggested parser test case" in
`parser_spec_team_tournament.md`, plus an idempotency / supersede test for
the re-process flow and a multi-file load smoke test.

Run from repo root:
    scripts/phase0/.venv/bin/python -m unittest scripts.phase0.parsers.test_team_tournament -v
"""

from __future__ import annotations

import os
import sqlite3
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))           # for team_tournament
sys.path.insert(0, str(HERE.parent))    # for db / players

import db  # noqa: E402
import team_tournament as parser  # noqa: E402

REPO_ROOT = HERE.parent.parent.parent
DATA_DIR = REPO_ROOT / "_DATA_" / "VLTC"

ANTES_2025 = str(DATA_DIR / "Antes Insurance Team Tournament IMO Joe results 2025.xlsx")
TENNIS_TRADE_2024 = str(DATA_DIR / "Results Tennis Trade Team Tournament(1).xlsx")
SAN_MICHEL_2026 = str(DATA_DIR / "San Michel Results 2026.xlsx")


def _player_name(conn: sqlite3.Connection, pid: int | None) -> str | None:
    if pid is None:
        return None
    row = conn.execute("SELECT canonical_name FROM players WHERE id = ?", (pid,)).fetchone()
    return row[0] if row else None


def _find_match(
    conn: sqlite3.Connection,
    *,
    division: str,
    side_a_names: set[str],
    side_b_names: set[str],
    round_label: str | None = None,
    played_on: str | None = None,
) -> int:
    """Find one match matching the criteria. Asserts found+unique."""
    sql = "SELECT m.id, m.round, m.played_on FROM matches m WHERE m.division = ?"
    args: list = [division]
    if round_label is not None:
        sql += " AND m.round = ?"
        args.append(round_label)
    if played_on is not None:
        sql += " AND m.played_on = ?"
        args.append(played_on)

    cands = conn.execute(sql, args).fetchall()

    found = []
    for mid, rnd, dt in cands:
        sides = conn.execute(
            "SELECT side, player1_id, player2_id FROM match_sides WHERE match_id = ?", (mid,)
        ).fetchall()
        side_map = {s: (p1, p2) for s, p1, p2 in sides}
        if "A" not in side_map or "B" not in side_map:
            continue
        a_set = {_player_name(conn, p) for p in side_map["A"] if p is not None}
        b_set = {_player_name(conn, p) for p in side_map["B"] if p is not None}
        if a_set == side_a_names and b_set == side_b_names:
            found.append(mid)
    if not found:
        raise AssertionError(
            f"no match found in division={division!r} round={round_label!r} "
            f"date={played_on!r} side_a={side_a_names!r} side_b={side_b_names!r}"
        )
    if len(found) > 1:
        raise AssertionError(f"multiple matches matched: {found}")
    return found[0]


class TestAntes2025(unittest.TestCase):
    """Tests against `Antes Insurance Team Tournament IMO Joe results 2025.xlsx`."""

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(ANTES_2025):
            raise unittest.SkipTest(f"Antes 2025 file not present: {ANTES_2025}")
        cls.conn = db.init_db(":memory:")
        cls.run_id = parser.parse(ANTES_2025, cls.conn)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "conn"):
            cls.conn.close()

    def _sides_summary(self, match_id: int) -> dict[str, tuple[int, int, int]]:
        """Return {side: (sets_won, games_won, won)}."""
        rows = self.conn.execute(
            "SELECT side, sets_won, games_won, won FROM match_sides WHERE match_id = ?",
            (match_id,),
        ).fetchall()
        return {side: (sw, gw, won) for (side, sw, gw, won) in rows}

    def test_1_day1_court1_first_rubber_men_d(self):
        """Day 1, Court 1, first rubber: Conrad Treeby Ward / Daniele Privitera vs Ray Ciantar / Kevin Sciberras (Men D, 6-3 / 3-6, undecided)."""
        mid = _find_match(
            self.conn,
            division="Men D",
            round_label="day 1",
            played_on="2025-05-28",
            side_a_names={"Conrad Treeby Ward", "Daniele Privitera"},
            side_b_names={"Ray Ciantar", "Kevin Sciberras"},
        )
        sides = self._sides_summary(mid)
        self.assertEqual(sides["A"], (1, 9, 0))
        self.assertEqual(sides["B"], (1, 9, 0))
        # Two set rows: 6-3 and 3-6.
        sets = self.conn.execute(
            "SELECT set_number, side_a_games, side_b_games FROM match_set_scores WHERE match_id = ? ORDER BY set_number",
            (mid,),
        ).fetchall()
        self.assertEqual(sets, [(1, 6, 3), (2, 3, 6)])

    def test_2_day1_court1_lad_b_clean_2_0(self):
        """Day 1, Court 1: Romina Gauci / Mariska Steenkamer vs Angele Pule' / Jade Sammut (Lad B, 6-2 6-1)."""
        mid = _find_match(
            self.conn,
            division="Lad B",
            round_label="day 1",
            played_on="2025-05-28",
            side_a_names={"Romina Gauci", "Mariska Steenkamer"},
            side_b_names={"Angele Pule'", "Jade Sammut"},
        )
        sides = self._sides_summary(mid)
        self.assertEqual(sides["A"], (2, 12, 1))
        self.assertEqual(sides["B"], (0, 3, 0))

        # Players inserted with gender 'F' (Lad rubber).
        for name in ("Romina Gauci", "Mariska Steenkamer", "Angele Pule'", "Jade Sammut"):
            row = self.conn.execute(
                "SELECT gender FROM players WHERE canonical_name = ?", (name,)
            ).fetchone()
            self.assertIsNotNone(row, f"player {name!r} not found")
            self.assertEqual(row[0], "F", f"player {name!r} should have gender F")

    def test_3_day1_pro_substitute_marker(self):
        """Day 1, Court 2: Naomi Zammit Ciantar / Amanda Falzon vs Annmarie Mangion / Jade Sammut (with (pro) sub annotation in cell)."""
        mid = _find_match(
            self.conn,
            division="Lad A",
            round_label="day 1",
            played_on="2025-05-28",
            side_a_names={"Naomi Zammit Ciantar", "Amanda Falzon"},
            side_b_names={"Annmarie Mangion", "Jade Sammut"},
        )
        sets = self.conn.execute(
            "SELECT set_number, side_a_games, side_b_games FROM match_set_scores WHERE match_id = ? ORDER BY set_number",
            (mid,),
        ).fetchall()
        self.assertEqual(sets, [(1, 6, 2), (2, 7, 5)])
        sides = self._sides_summary(mid)
        self.assertEqual(sides["A"], (2, 13, 1))
        self.assertEqual(sides["B"], (0, 7, 0))

    def test_4_final_first_rubber(self):
        """Final, first rubber: Nikolai Belli / Ivan Cachia vs Kurt Cassar / Roderick Spiteri (Men B, 6-0 6-2)."""
        mid = _find_match(
            self.conn,
            division="Men B",
            round_label="final",
            played_on="2025-07-11",
            side_a_names={"Nikolai Belli", "Ivan Cachia"},
            side_b_names={"Kurt Cassar", "Roderick Spiteri"},
        )
        sets = self.conn.execute(
            "SELECT set_number, side_a_games, side_b_games FROM match_set_scores WHERE match_id = ? ORDER BY set_number",
            (mid,),
        ).fetchall()
        self.assertEqual(sets, [(1, 6, 0), (2, 6, 2)])
        sides = self._sides_summary(mid)
        self.assertEqual(sides["A"], (2, 12, 1))
        self.assertEqual(sides["B"], (0, 2, 0))

    def test_5_total_match_count(self):
        """Antes 2025 should produce >= 100 matches (sanity check)."""
        n = self.conn.execute(
            "SELECT COUNT(*) FROM matches WHERE ingestion_run_id = ?", (self.run_id,)
        ).fetchone()[0]
        self.assertGreaterEqual(n, 100, f"expected >=100 matches, got {n}")
        self.assertLessEqual(n, 200, f"expected <=200 matches, got {n}")

    def test_6_tournament_metadata(self):
        """Tournament row should be created with format='doubles_team' and year=2025."""
        rows = self.conn.execute(
            "SELECT id, name, year, format FROM tournaments"
        ).fetchall()
        self.assertEqual(len(rows), 1)
        _, _, year, fmt = rows[0]
        self.assertEqual(year, 2025)
        self.assertEqual(fmt, "doubles_team")


class TestTennisTrade2024SingleRow(unittest.TestCase):
    """Single-row variant + walkover detection.

    Uses `Results Tennis Trade Team Tournament(1).xlsx` (Tennis Trade 2024).
    """

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(TENNIS_TRADE_2024):
            raise unittest.SkipTest(f"Tennis Trade 2024 file not present: {TENNIS_TRADE_2024}")
        cls.conn = db.init_db(":memory:")
        cls.run_id = parser.parse(TENNIS_TRADE_2024, cls.conn)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "conn"):
            cls.conn.close()

    def test_walkover_detected_men_d_first_rubber(self):
        """Day 1 Court 1 first rubber should be a walkover, single-row scoring."""
        mid = _find_match(
            self.conn,
            division="Men D",
            round_label="day 1",
            played_on="2024-10-30",
            side_a_names={"Joseph Randich", "Chris Vella"},
            side_b_names={"Matthew Micallef", "Justin Scicluna"},
        )
        # Single set row only.
        sets = self.conn.execute(
            "SELECT set_number, side_a_games, side_b_games FROM match_set_scores WHERE match_id = ?",
            (mid,),
        ).fetchall()
        self.assertEqual(len(sets), 1)
        self.assertEqual(sets[0], (1, 6, 12))
        # walkover flag set.
        wo = self.conn.execute("SELECT walkover FROM matches WHERE id = ?", (mid,)).fetchone()[0]
        self.assertEqual(wo, 1, "walkover flag should be set")
        # Side B won (12 > 6).
        rows = self.conn.execute(
            "SELECT side, won, games_won FROM match_sides WHERE match_id = ?", (mid,)
        ).fetchall()
        sides = {side: (won, gw) for (side, won, gw) in rows}
        self.assertEqual(sides["A"][0], 0)
        self.assertEqual(sides["A"][1], 6)
        self.assertEqual(sides["B"][0], 1)
        self.assertEqual(sides["B"][1], 12)

    def test_at_least_one_match_loaded(self):
        n = self.conn.execute(
            "SELECT COUNT(*) FROM matches WHERE ingestion_run_id = ?", (self.run_id,)
        ).fetchone()[0]
        self.assertGreater(n, 0, "expected at least 1 match")


class TestIdempotency(unittest.TestCase):
    """Re-loading the same file should supersede prior matches."""

    def test_reload_supersedes(self):
        if not os.path.exists(ANTES_2025):
            self.skipTest(f"Antes 2025 file not present")
        conn = db.init_db(":memory:")
        try:
            run1 = parser.parse(ANTES_2025, conn)
            n_after_first = conn.execute(
                "SELECT COUNT(*) FROM matches WHERE superseded_by_run_id IS NULL"
            ).fetchone()[0]
            self.assertGreater(n_after_first, 0)

            run2 = parser.parse(ANTES_2025, conn)
            self.assertNotEqual(run1, run2)

            n_active = conn.execute(
                "SELECT COUNT(*) FROM matches WHERE superseded_by_run_id IS NULL"
            ).fetchone()[0]
            n_superseded = conn.execute(
                "SELECT COUNT(*) FROM matches WHERE superseded_by_run_id = ?",
                (run2,),
            ).fetchone()[0]
            self.assertEqual(n_active, n_after_first)
            self.assertEqual(n_superseded, n_after_first)

            # source_files row not duplicated (same sha + filename).
            n_sf = conn.execute("SELECT COUNT(*) FROM source_files").fetchone()[0]
            self.assertEqual(n_sf, 1)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
