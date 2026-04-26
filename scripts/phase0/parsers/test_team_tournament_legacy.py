"""Tests for the LEGACY VLTC Team-Tournament parser (T-P0-014).

One test per "Suggested parser test case" in
`parser_spec_team_tournament_legacy.md`, plus an idempotency / supersede test
for the re-process flow and a multi-file load smoke test.

Run from repo root:
    scripts/phase0/.venv/bin/python -m unittest scripts.phase0.parsers.test_team_tournament_legacy -v
"""

from __future__ import annotations

import os
import sqlite3
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))           # for team_tournament_legacy
sys.path.insert(0, str(HERE.parent))    # for db / players

import db  # noqa: E402
import team_tournament_legacy as parser  # noqa: E402

REPO_ROOT = HERE.parent.parent.parent
DATA_DIR = REPO_ROOT / "_DATA_" / "VLTC"

PKF_2023 = str(DATA_DIR / "PKF  Team Tournament 2023.xlsx")
PKF_2024 = str(DATA_DIR / " PKF  Team Tournament 2024.xlsx")
TENNIS_TRADE_2023 = str(DATA_DIR / "TENNIS TRADE  Team Tournament 2023.xlsx")
SAN_MICHEL_2023 = str(DATA_DIR / "SAN MICHEL TEAM TOURNAMENT 2023.xlsx")
SAN_MICHEL_2025_LEGACY = str(DATA_DIR / "SAN MICHEL TEAM TOURNAMENT 2025.xlsx")
SAN_MICHEL_2024_BARE = str(DATA_DIR / " Team Tournament 2024.xlsx")


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
    """Find one match matching the criteria. Asserts found+unique.

    `side_a_names` / `side_b_names` are the EXPECTED canonical-name sets for
    each side. None values (singles player2) are excluded from comparison.
    """
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


class TestPKF2023(unittest.TestCase):
    """Tests against `PKF  Team Tournament 2023.xlsx`."""

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(PKF_2023):
            raise unittest.SkipTest(f"PKF 2023 file not present: {PKF_2023}")
        cls.conn = db.init_db(":memory:")
        cls.run_id = parser.parse(PKF_2023, cls.conn)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "conn"):
            cls.conn.close()

    def _sides_summary(self, match_id: int) -> dict[str, tuple[int, int, int]]:
        rows = self.conn.execute(
            "SELECT side, sets_won, games_won, won FROM match_sides WHERE match_id = ?",
            (match_id,),
        ).fetchall()
        return {side: (sw, gw, won) for side, sw, gw, won in rows}

    def _set_scores(self, match_id: int) -> list[tuple[int, int, int]]:
        return [
            (n, a, b)
            for n, a, b in self.conn.execute(
                "SELECT set_number, side_a_games, side_b_games FROM match_set_scores "
                "WHERE match_id = ? ORDER BY set_number",
                (match_id,),
            ).fetchall()
        ]

    def test_men_b_walkover_rubber(self):
        """Test 1 — PKF 2023 Day 1, MEN B rubber with walkover note in row 25."""
        mid = _find_match(
            self.conn,
            division="Men B",
            side_a_names={"MARTINELLI JONATHAN", "MARCUS GIO"},
            side_b_names={"CANONCE CHI CHI", "PACE GABRIEL"},
            round_label="day 1",
            played_on="2023-07-04",
        )
        # Confirm walkover detected via NOTES row (`MEN B 1st set walkover ...`)
        row = self.conn.execute(
            "SELECT walkover, match_type FROM matches WHERE id = ?", (mid,)
        ).fetchone()
        self.assertEqual(row[0], 1)
        self.assertEqual(row[1], "doubles")
        self.assertEqual(self._set_scores(mid), [(1, 0, 6), (2, 3, 6)])
        sides = self._sides_summary(mid)
        self.assertEqual(sides["A"], (0, 3, 0))
        self.assertEqual(sides["B"], (2, 12, 1))

        # Player gender update for MEN rubber
        a1_gender = self.conn.execute(
            "SELECT gender FROM players WHERE canonical_name = 'MARTINELLI JONATHAN'"
        ).fetchone()[0]
        self.assertEqual(a1_gender, "M")

    def test_lad_a_clean_2_0(self):
        """Test 2 — PKF 2023 Day 1, LAD A rubber, clean 2-0."""
        mid = _find_match(
            self.conn,
            division="Lad A",
            side_a_names={"AZZOPARDI ERIKA", "BONETT CHRISTINA"},
            side_b_names={"MANGION ANNEMARIE", "MAGRI LUCIENNE"},
            round_label="day 1",
            played_on="2023-07-04",
        )
        self.assertEqual(self._set_scores(mid), [(1, 6, 4), (2, 6, 1)])
        sides = self._sides_summary(mid)
        self.assertEqual(sides["A"], (2, 12, 1))
        self.assertEqual(sides["B"], (0, 5, 0))
        # Players inserted with gender='F'
        gender = self.conn.execute(
            "SELECT gender FROM players WHERE canonical_name = 'AZZOPARDI ERIKA'"
        ).fetchone()[0]
        self.assertEqual(gender, "F")

    def test_singles_rubber(self):
        """Test 3 — PKF 2023 Day 1, SINGLES rubber 2023-07-06."""
        mid = _find_match(
            self.conn,
            division="Singles",
            side_a_names={"RUTTER TREVOR"},
            side_b_names={"AZZOPARDI JEAN KARL"},
            round_label="day 1",
            played_on="2023-07-06",
        )
        row = self.conn.execute(
            "SELECT match_type FROM matches WHERE id = ?", (mid,)
        ).fetchone()
        self.assertEqual(row[0], "singles")
        # SET 1 4-6, SET 2 7-6
        self.assertEqual(self._set_scores(mid), [(1, 4, 6), (2, 7, 6)])
        sides = self._sides_summary(mid)
        self.assertEqual(sides["A"], (1, 11, 0))
        self.assertEqual(sides["B"], (1, 12, 0))

        # player2_id is NULL on both sides
        rows = self.conn.execute(
            "SELECT side, player2_id FROM match_sides WHERE match_id = ?", (mid,)
        ).fetchall()
        for side, p2 in rows:
            self.assertIsNone(p2, f"singles player2_id should be NULL on side {side}")


class TestTennisTrade2023(unittest.TestCase):
    """Tests against `TENNIS TRADE  Team Tournament 2023.xlsx`."""

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(TENNIS_TRADE_2023):
            raise unittest.SkipTest(f"Tennis Trade 2023 file not present: {TENNIS_TRADE_2023}")
        cls.conn = db.init_db(":memory:")
        cls.run_id = parser.parse(TENNIS_TRADE_2023, cls.conn)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "conn"):
            cls.conn.close()

    def test_subtier_collapse_lad_a(self):
        """Test 4 — Tennis Trade 2023 LAD A1 / LAD A2 → 'Lad A'."""
        # Row 9 LAD A1 — Thursday 19/10/2023
        mid1 = _find_match(
            self.conn,
            division="Lad A",
            side_a_names={"FENECH ROBERTA", "ABELA NATALYA"},
            side_b_names={"AZZOPARDI ERIKA", "ZAMMIT CIANTAR NAOMI"},
            played_on="2023-10-19",
        )
        scores1 = [
            (n, a, b)
            for n, a, b in self.conn.execute(
                "SELECT set_number, side_a_games, side_b_games FROM match_set_scores "
                "WHERE match_id = ? ORDER BY set_number",
                (mid1,),
            ).fetchall()
        ]
        self.assertEqual(scores1, [(1, 2, 6), (2, 6, 7)])

        # Row 15 LAD A2 — Saturday 21/10/2023
        mid2 = _find_match(
            self.conn,
            division="Lad A",
            side_a_names={"ABELA NATALYA", "FAVA ANNA"},
            side_b_names={"BONETT CHRISTINA", "JULIE SPITERI"},
            played_on="2023-10-21",
        )
        scores2 = [
            (n, a, b)
            for n, a, b in self.conn.execute(
                "SELECT set_number, side_a_games, side_b_games FROM match_set_scores "
                "WHERE match_id = ? ORDER BY set_number",
                (mid2,),
            ).fetchall()
        ]
        self.assertEqual(scores2, [(1, 5, 7), (2, 6, 3)])

        # Both matches share division = 'Lad A' (sub-tier collapsed).
        for mid in (mid1, mid2):
            div = self.conn.execute(
                "SELECT division FROM matches WHERE id = ?", (mid,)
            ).fetchone()[0]
            self.assertEqual(div, "Lad A")


class TestSanMichel2023(unittest.TestCase):
    """Tests against `SAN MICHEL TEAM TOURNAMENT 2023.xlsx` (single MATCH RESULTS sheet)."""

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(SAN_MICHEL_2023):
            raise unittest.SkipTest(f"San Michel 2023 file not present: {SAN_MICHEL_2023}")
        cls.conn = db.init_db(":memory:")
        cls.run_id = parser.parse(SAN_MICHEL_2023, cls.conn)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "conn"):
            cls.conn.close()

    def test_encounter_2_lad_b_set_tie(self):
        """Test 5 — encounter at row 28, first rubber LDY'S B (collapsed to Lad B)."""
        mid = _find_match(
            self.conn,
            division="Lad B",
            side_a_names={"CASSAR TANYA", "ABELA ANNABELLE"},
            side_b_names={"MICALLEF YLENIA", "BUHAGIAR DORIANNE"},
            played_on="2023-03-23",
        )
        scores = [
            (n, a, b)
            for n, a, b in self.conn.execute(
                "SELECT set_number, side_a_games, side_b_games FROM match_set_scores "
                "WHERE match_id = ? ORDER BY set_number",
                (mid,),
            ).fetchall()
        ]
        self.assertEqual(scores, [(1, 6, 4), (2, 3, 6)])

        sides = {
            side: (sw, gw, won)
            for side, sw, gw, won in self.conn.execute(
                "SELECT side, sets_won, games_won, won FROM match_sides WHERE match_id = ?",
                (mid,),
            ).fetchall()
        }
        # 1-1 set tie, no super-tiebreak → undecided
        self.assertEqual(sides["A"], (1, 9, 0))
        self.assertEqual(sides["B"], (1, 10, 0))


class TestPKF2024Sanity(unittest.TestCase):
    """Test 6 — PKF 2024 sanity: file parses, total match count plausible."""

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(PKF_2024):
            raise unittest.SkipTest(f"PKF 2024 file not present: {PKF_2024}")
        cls.conn = db.init_db(":memory:")
        cls.run_id = parser.parse(PKF_2024, cls.conn)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "conn"):
            cls.conn.close()

    def test_match_count_plausible(self):
        n = self.conn.execute(
            "SELECT COUNT(*) FROM matches WHERE ingestion_run_id = ?", (self.run_id,)
        ).fetchone()[0]
        # 10 days × ~3 encounters × 6-8 rubbers = ~150-200
        self.assertGreaterEqual(n, 100, f"too few matches: {n}")
        self.assertLessEqual(n, 250, f"too many matches: {n}")

    def test_singles_present(self):
        n = self.conn.execute(
            "SELECT COUNT(*) FROM matches WHERE match_type = 'singles' AND ingestion_run_id = ?",
            (self.run_id,),
        ).fetchone()[0]
        self.assertGreater(n, 0, "expected at least one SINGLES rubber in PKF 2024")

    def test_tournament_year_2024(self):
        row = self.conn.execute(
            "SELECT name, year, format FROM tournaments LIMIT 1"
        ).fetchone()
        self.assertEqual(row[1], 2024)
        self.assertEqual(row[2], "doubles_team")


class TestIdempotency(unittest.TestCase):
    """Verify that re-loading the same file supersedes the prior run."""

    def test_supersede(self):
        if not os.path.exists(PKF_2023):
            self.skipTest(f"PKF 2023 file not present: {PKF_2023}")
        conn = db.init_db(":memory:")
        try:
            run1 = parser.parse(PKF_2023, conn)
            n1 = conn.execute(
                "SELECT COUNT(*) FROM matches WHERE ingestion_run_id = ? "
                "AND superseded_by_run_id IS NULL",
                (run1,),
            ).fetchone()[0]
            self.assertGreater(n1, 0)

            run2 = parser.parse(PKF_2023, conn)
            self.assertNotEqual(run1, run2)

            # Run 1 matches now superseded by run 2.
            n1_active = conn.execute(
                "SELECT COUNT(*) FROM matches WHERE ingestion_run_id = ? "
                "AND superseded_by_run_id IS NULL",
                (run1,),
            ).fetchone()[0]
            self.assertEqual(n1_active, 0)

            # Run 1 marked superseded
            status1 = conn.execute(
                "SELECT status FROM ingestion_runs WHERE id = ?", (run1,)
            ).fetchone()[0]
            self.assertEqual(status1, "superseded")
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
