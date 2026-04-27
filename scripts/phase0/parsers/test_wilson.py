"""Tests for the Wilson team-tournament parser (T-P0-014).

One test per "Suggested parser test case" in `parser_spec_wilson.md`,
plus an end-to-end smoke test across multiple Wilson files.

Run from repo root:
    python -m unittest scripts.phase0.parsers.test_wilson -v
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))                # for wilson
sys.path.insert(0, str(HERE.parent))         # for db / players

import db  # noqa: E402
import wilson as parser  # noqa: E402

REPO_ROOT = HERE.parent.parent.parent

from _test_fixtures import locate as _locate  # noqa: E402

XLSX_2020 = _locate("Wilson Autumn Results 2020.xlsx") or ""
XLSX_2019 = _locate("Wilson Autumn Results 2019.xlsx") or ""
XLSX_2021 = _locate("Wilson Autumn Results 2021.xlsx") or ""
XLS_2017 = _locate("Wilson Autumn Results 2017.xls") or ""


def _player_name(conn: sqlite3.Connection, pid: int) -> str:
    return conn.execute("SELECT canonical_name FROM players WHERE id = ?", (pid,)).fetchone()[0]


def _find_match_by_pairs(
    conn: sqlite3.Connection,
    division: str,
    side_a_names: tuple[str, str],
    side_b_names: tuple[str, str],
    round_label: str | None = None,
    sheet_hint: str | None = None,
) -> int:
    """Find a match (rubber) whose pair A and pair B match the given names.

    Order of players within a pair is irrelevant.
    """
    candidates = conn.execute(
        "SELECT id, round FROM matches WHERE division = ?",
        (division,),
    ).fetchall()
    matches: list[int] = []
    for mid, rnd in candidates:
        if round_label is not None and rnd != round_label:
            continue
        if round_label is None and rnd is not None:
            continue
        sides = conn.execute(
            "SELECT side, player1_id, player2_id FROM match_sides WHERE match_id = ?", (mid,)
        ).fetchall()
        side_map = {s: (p1, p2) for s, p1, p2 in sides}
        if "A" not in side_map or "B" not in side_map:
            continue
        a_names = {_player_name(conn, side_map["A"][0]), _player_name(conn, side_map["A"][1])}
        b_names = {_player_name(conn, side_map["B"][0]), _player_name(conn, side_map["B"][1])}
        if a_names == set(side_a_names) and b_names == set(side_b_names):
            matches.append(mid)
    if len(matches) == 0:
        raise AssertionError(
            f"no match found in division={division!r} round={round_label!r} "
            f"with side A={side_a_names} side B={side_b_names}"
        )
    if len(matches) > 1:
        raise AssertionError(
            f"multiple matches matched in division={division!r}: {matches}"
        )
    return matches[0]


class _LoadedDB2020:
    """One-time per-class load of the Wilson 2020 file."""

    _conn: sqlite3.Connection | None = None
    _run_id: int | None = None

    @classmethod
    def get(cls) -> sqlite3.Connection:
        if cls._conn is None:
            cls._conn = db.init_db(":memory:")
            cls._run_id = parser.parse(XLSX_2020, cls._conn)
        return cls._conn


class _LoadedDB2017:
    _conn: sqlite3.Connection | None = None
    _run_id: int | None = None

    @classmethod
    def get(cls) -> sqlite3.Connection:
        if cls._conn is None:
            cls._conn = db.init_db(":memory:")
            cls._run_id = parser.parse(XLS_2017, cls._conn)
        return cls._conn


class TestCase1_TiedRubberDay1Mxd(unittest.TestCase):
    """Test case 1 — Day 1 Court 1 first rubber, Mxd BA, sets tied 1-1.

    Side A: Neville Sciriha / Mariska Steenkamer
    Side B: George Grech / Grace Barbara
    Set 1: A=1, B=6 ; Set 2: A=6, B=0
    No T.B. cell → tied; both `won=0`, both `sets_won=1`.
    """

    def test_match_present_with_tied_outcome(self):
        conn = _LoadedDB2020.get()
        mid = _find_match_by_pairs(
            conn,
            "Mxd BA",
            ("Neville Sciriha", "Mariska Steenkamer"),
            ("George Grech", "Grace Barbara"),
        )
        sets = conn.execute(
            "SELECT set_number, side_a_games, side_b_games, was_tiebreak "
            "FROM match_set_scores WHERE match_id = ? ORDER BY set_number",
            (mid,),
        ).fetchall()
        self.assertEqual(sets, [(1, 1, 6, 0), (2, 6, 0, 0)])

        sides = dict(
            (side, (sets_won, games_won, won))
            for side, sets_won, games_won, won in conn.execute(
                "SELECT side, sets_won, games_won, won FROM match_sides WHERE match_id = ?",
                (mid,),
            )
        )
        # Tied 1-1 sets, no super-tb → both undecided (won=0).
        self.assertEqual(sides["A"], (1, 7, 0))
        self.assertEqual(sides["B"], (1, 6, 0))

    def test_quality_report_has_tied_rubber(self):
        conn = _LoadedDB2020.get()
        row = conn.execute(
            "SELECT quality_report_jsonb FROM ingestion_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        report = json.loads(row[0])
        tied = report["tied_rubbers_undecided"]
        self.assertTrue(
            any(
                e["division"] == "Mxd BA"
                and "Neville Sciriha" in e["pair_A"]
                and "Mariska Steenkamer" in e["pair_A"]
                for e in tied
            ),
            f"expected tied rubber not found. tied={tied!r}",
        )


class TestCase2_TwoSetSweepWithSetTiebreak(unittest.TestCase):
    """Test case 2 — Day 1 Court 1 Lad A, two-set sweep with set-tiebreak in set 1.

    Side A: Olivia Belli / Nicole Fava
    Side B: Alexia Spiteri / Elaine Grech
    Set 1: A=7, B=6 (was_tiebreak=TRUE)
    Set 2: A=6, B=4
    Side A wins 2-0.
    """

    def test_match_present_with_correct_sets(self):
        conn = _LoadedDB2020.get()
        mid = _find_match_by_pairs(
            conn,
            "Lad A",
            ("Olivia Belli", "Nicole Fava"),
            ("Alexia Spiteri", "Elaine Grech"),
        )
        sets = conn.execute(
            "SELECT set_number, side_a_games, side_b_games, was_tiebreak "
            "FROM match_set_scores WHERE match_id = ? ORDER BY set_number",
            (mid,),
        ).fetchall()
        self.assertEqual(sets, [(1, 7, 6, 1), (2, 6, 4, 0)])

        sides = dict(
            (side, (sets_won, games_won, won))
            for side, sets_won, games_won, won in conn.execute(
                "SELECT side, sets_won, games_won, won FROM match_sides WHERE match_id = ?",
                (mid,),
            )
        )
        self.assertEqual(sides["A"], (2, 13, 1))
        self.assertEqual(sides["B"], (0, 10, 0))


class TestCase3_ColumnAnchorShiftDay2(unittest.TestCase):
    """Test case 3 — Wilson 2020 Day 2 uses col-2 anchor (not col-3 like Day 1).

    Day 2 first rubber, Court 1, Men A:
    Side A: Nicholas Gollcher / Dean Callus
    Side B: Kurt Carabott / Clive Borg
    Set 1: A=4, B=6 ; Set 2: A=7, B=6 (set-tiebreak)
    Sets 1-1 tied; both won=0.
    """

    def test_day2_match_extracted_with_correct_anchor(self):
        conn = _LoadedDB2020.get()
        mid = _find_match_by_pairs(
            conn,
            "Men A",
            ("Nicholas Gollcher", "Dean Callus"),
            ("Kurt Carabott", "Clive Borg"),
        )
        sets = conn.execute(
            "SELECT set_number, side_a_games, side_b_games, was_tiebreak "
            "FROM match_set_scores WHERE match_id = ? ORDER BY set_number",
            (mid,),
        ).fetchall()
        self.assertEqual(sets, [(1, 4, 6, 0), (2, 7, 6, 1)])

        sides = dict(
            (side, (sets_won, games_won, won))
            for side, sets_won, games_won, won in conn.execute(
                "SELECT side, sets_won, games_won, won FROM match_sides WHERE match_id = ?",
                (mid,),
            )
        )
        self.assertEqual(sides["A"], (1, 11, 0))
        self.assertEqual(sides["B"], (1, 12, 0))


class TestCase4_RetirementXLS2017(unittest.TestCase):
    """Test case 4 — Retirement (`'ret'`) in Wilson 2017 .xls Final.

    Sheet: Final, row 31, Men A
    Side A: Marcelo Villanueva / Richard Curmi
    Side B: Suniel Balani / Trevor Rutter
    Set 1: A=7, B=5 ; Set 2: 'ret' → A wins by retirement.
    """

    def test_retirement_recorded_with_walkover_flag(self):
        conn = _LoadedDB2017.get()
        mid = _find_match_by_pairs(
            conn,
            "Men A",
            ("Marcelo Villanueva", "Richard Curmi"),
            ("Suniel Balani", "Trevor Rutter"),
            round_label="final",
        )
        sets = conn.execute(
            "SELECT set_number, side_a_games, side_b_games, was_tiebreak "
            "FROM match_set_scores WHERE match_id = ? ORDER BY set_number",
            (mid,),
        ).fetchall()
        # Only set 1 should be recorded; 7 in set 1 → was_tiebreak=TRUE
        self.assertEqual(sets, [(1, 7, 5, 1)])

        walkover = conn.execute(
            "SELECT walkover FROM matches WHERE id = ?", (mid,)
        ).fetchone()[0]
        self.assertEqual(walkover, 1)

        sides = dict(
            (side, (sets_won, games_won, won))
            for side, sets_won, games_won, won in conn.execute(
                "SELECT side, sets_won, games_won, won FROM match_sides WHERE match_id = ?",
                (mid,),
            )
        )
        self.assertEqual(sides["A"], (1, 7, 1))
        self.assertEqual(sides["B"], (0, 5, 0))


class TestCase5_SmokeMultipleFiles(unittest.TestCase):
    """Test case 5 — smoke test across 3 Wilson files (.xlsx 2019/2020/2021).

    Each must parse without exceptions and produce >50 matches with valid
    sets/sides rows.
    """

    def test_smoke_2019(self):
        self._smoke(XLSX_2019)

    def test_smoke_2020(self):
        self._smoke(XLSX_2020)

    def test_smoke_2021(self):
        self._smoke(XLSX_2021)

    def _smoke(self, path: str):
        conn = db.init_db(":memory:")
        try:
            run_id = parser.parse(path, conn)
            n_matches = conn.execute(
                "SELECT COUNT(*) FROM matches WHERE ingestion_run_id = ?", (run_id,)
            ).fetchone()[0]
            self.assertGreater(n_matches, 50, f"{path}: expected >50 matches, got {n_matches}")

            # Every match has exactly 2 match_sides rows.
            bad = conn.execute(
                "SELECT m.id, COUNT(ms.match_id) "
                "FROM matches m LEFT JOIN match_sides ms ON ms.match_id = m.id "
                "WHERE m.ingestion_run_id = ? "
                "GROUP BY m.id HAVING COUNT(ms.match_id) != 2",
                (run_id,),
            ).fetchall()
            self.assertEqual(bad, [], f"{path}: matches without 2 sides: {bad}")

            # Every match has 1, 2, or 3 set rows.
            bad_sets = conn.execute(
                "SELECT m.id, COUNT(s.match_id) "
                "FROM matches m LEFT JOIN match_set_scores s ON s.match_id = m.id "
                "WHERE m.ingestion_run_id = ? "
                "GROUP BY m.id HAVING COUNT(s.match_id) NOT IN (1, 2, 3)",
                (run_id,),
            ).fetchall()
            self.assertEqual(bad_sets, [], f"{path}: matches with bad set count: {bad_sets}")

            # All players have non-empty canonical_name.
            empty = conn.execute(
                "SELECT id FROM players WHERE canonical_name = '' OR canonical_name IS NULL"
            ).fetchall()
            self.assertEqual(empty, [], f"{path}: players with empty name: {empty}")
        finally:
            conn.close()


class TestReprocessAndSupersede(unittest.TestCase):
    """Re-loading the same file creates a new run and supersedes prior matches."""

    def test_supersede(self):
        conn = db.init_db(":memory:")
        try:
            run_id_1 = parser.parse(XLSX_2020, conn)
            n_active_1 = conn.execute(
                "SELECT COUNT(*) FROM matches WHERE superseded_by_run_id IS NULL"
            ).fetchone()[0]
            self.assertGreater(n_active_1, 0)

            run_id_2 = parser.parse(XLSX_2020, conn)
            self.assertNotEqual(run_id_1, run_id_2)

            n_super_marked = conn.execute(
                "SELECT COUNT(*) FROM matches WHERE ingestion_run_id = ? AND superseded_by_run_id = ?",
                (run_id_1, run_id_2),
            ).fetchone()[0]
            self.assertEqual(n_super_marked, n_active_1)

            row = conn.execute(
                "SELECT supersedes_run_id, status FROM ingestion_runs WHERE id = ?",
                (run_id_2,),
            ).fetchone()
            self.assertEqual(row[0], run_id_1)
            self.assertEqual(row[1], "completed")

            old_status = conn.execute(
                "SELECT status FROM ingestion_runs WHERE id = ?", (run_id_1,)
            ).fetchone()[0]
            self.assertEqual(old_status, "superseded")

            n_active_2 = conn.execute(
                "SELECT COUNT(*) FROM matches WHERE superseded_by_run_id IS NULL"
            ).fetchone()[0]
            self.assertEqual(n_active_2, n_active_1)

            n_source_files = conn.execute("SELECT COUNT(*) FROM source_files").fetchone()[0]
            self.assertEqual(n_source_files, 1)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
