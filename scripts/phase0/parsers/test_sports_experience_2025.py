"""Tests for the Sports Experience Chosen Doubles 2025 parser (T-P0-004).

One test per "Suggested parser test case" in `parser_spec_sports_experience_2025.md`
plus an idempotency / supersede test for the re-process flow.

Run from repo root:
    python -m unittest scripts.phase0.parsers.test_sports_experience_2025 -v
"""

from __future__ import annotations

import os
import sqlite3
import sys
import unittest
from pathlib import Path

# Allow `import db` / `import players` / `import sports_experience_2025`
# whether run as script or as a module.
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))                # for sports_experience_2025
sys.path.insert(0, str(HERE.parent))         # for db / players

import db  # noqa: E402
import sports_experience_2025 as parser  # noqa: E402

REPO_ROOT = HERE.parent.parent.parent
from _test_fixtures import locate as _locate  # noqa: E402
XLSX_PATH = _locate("Sports Experience Chosen Doubles 2025 result sheet.xlsx") or ""


def _player_name(conn: sqlite3.Connection, pid: int) -> str:
    return conn.execute("SELECT canonical_name FROM players WHERE id = ?", (pid,)).fetchone()[0]


def _find_match_by_pairs(
    conn: sqlite3.Connection,
    division: str,
    side_a_names: tuple[str, str],
    side_b_names: tuple[str, str],
    round_label: str | None = None,
) -> int:
    """Return the match_id for a match whose Side A is the given pair and
    Side B is the given pair (regardless of player1/player2 order). Raises if
    not found or non-unique.
    """
    candidates = conn.execute(
        """
        SELECT m.id, m.round
        FROM matches m
        WHERE m.division = ?
        """,
        (division,),
    ).fetchall()

    matches = []
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


class _LoadedDB:
    """One-time per-class load to keep tests fast (full parse takes ~1s)."""

    _conn: sqlite3.Connection | None = None
    _run_id: int | None = None

    @classmethod
    def get(cls) -> sqlite3.Connection:
        if cls._conn is None:
            cls._conn = db.init_db(":memory:")
            cls._run_id = parser.parse(XLSX_PATH, cls._conn)
        return cls._conn


class TestCase1_CleanTwoSetWinLeftBlock(unittest.TestCase):
    """Test case 1 — Clean 2-set win, left block, single-group division.

    Sheet: Men Div 1, anchor row r=9, left block.
    Side A: Duncan D'Alessandro / Clayton Zammit Cesare
    Side B: Mark Gatt / Manuel Bonello
    Set 1: A=6, B=4 (was_tiebreak=False)
    Set 2: A=4, B=6 (was_tiebreak=False)
    Match-tiebreak: A=10, B=3 (was_tiebreak=True)
    A wins via deciding super-tiebreak.
    """

    def test_match_present_with_correct_sets_and_winner(self):
        conn = _LoadedDB.get()
        mid = _find_match_by_pairs(
            conn,
            "Men Division 1",
            ("Duncan D'Alessandro", "Clayton Zammit Cesare"),
            ("Mark Gatt", "Manuel Bonello"),
        )
        sets = conn.execute(
            "SELECT set_number, side_a_games, side_b_games, was_tiebreak "
            "FROM match_set_scores WHERE match_id = ? ORDER BY set_number",
            (mid,),
        ).fetchall()
        self.assertEqual(sets, [(1, 6, 4, 0), (2, 4, 6, 0), (3, 10, 3, 1)])

        sides = dict(
            (side, (sets_won, games_won, won))
            for side, sets_won, games_won, won in conn.execute(
                "SELECT side, sets_won, games_won, won FROM match_sides WHERE match_id = ?",
                (mid,),
            )
        )
        # Per spec: when match decided by super-tb, sets_won = 1 for both sides
        # (the regular sets), games_won counts only regular sets, won is decided
        # by the super-tb.
        self.assertEqual(sides["A"], (1, 10, 1))
        self.assertEqual(sides["B"], (1, 10, 0))


class TestCase2_RightBlockMatchSameRowBand(unittest.TestCase):
    """Test case 2 — Right-block match, same row band, different opponents.

    Sheet: Men Div 1, anchor r=9, right block (col 16).
    Side A: Duncan D'Alessandro / Clayton Zammit Cesare
    Side B: Gabriel Pace / Nikolai Belli
    Set 1: A=6, B=0 ; Set 2: A=6, B=3 ; no super-tb.
    A wins 2-0.
    """

    def test_match_present_with_correct_sets_and_winner(self):
        conn = _LoadedDB.get()
        mid = _find_match_by_pairs(
            conn,
            "Men Division 1",
            ("Duncan D'Alessandro", "Clayton Zammit Cesare"),
            ("Gabriel Pace", "Nikolai Belli"),
        )
        sets = conn.execute(
            "SELECT set_number, side_a_games, side_b_games, was_tiebreak "
            "FROM match_set_scores WHERE match_id = ? ORDER BY set_number",
            (mid,),
        ).fetchall()
        self.assertEqual(sets, [(1, 6, 0, 0), (2, 6, 3, 0)])

        sides = dict(
            (side, (sets_won, games_won, won))
            for side, sets_won, games_won, won in conn.execute(
                "SELECT side, sets_won, games_won, won FROM match_sides WHERE match_id = ?",
                (mid,),
            )
        )
        self.assertEqual(sides["A"], (2, 12, 1))
        self.assertEqual(sides["B"], (0, 3, 0))


class TestCase3_TwoGroupSheetGroupBSuperTB(unittest.TestCase):
    """Test case 3 — Two-group sheet, group B match, with super-tiebreak.

    Sheet: Men Div 3, anchor r=39, left block.
    division = 'Men Division 3 - Group B'
    Side A: Dunstan Vella / Cyril Lastimosa
    Side B: Manuel Mifsud / Julian Esposito
    Set 1: A=3, B=6 ; Set 2: A=6, B=3 ; super-tb: A=10, B=3.
    Side A wins.
    """

    def test_match_present_with_correct_sets_and_winner(self):
        conn = _LoadedDB.get()
        mid = _find_match_by_pairs(
            conn,
            "Men Division 3 - Group B",
            ("Dunstan Vella", "Cyril Lastimosa"),
            ("Manuel Mifsud", "Julian Esposito"),
        )
        sets = conn.execute(
            "SELECT set_number, side_a_games, side_b_games, was_tiebreak "
            "FROM match_set_scores WHERE match_id = ? ORDER BY set_number",
            (mid,),
        ).fetchall()
        self.assertEqual(sets, [(1, 3, 6, 0), (2, 6, 3, 0), (3, 10, 3, 1)])

        sides = dict(
            (side, (sets_won, games_won, won))
            for side, sets_won, games_won, won in conn.execute(
                "SELECT side, sets_won, games_won, won FROM match_sides WHERE match_id = ?",
                (mid,),
            )
        )
        self.assertEqual(sides["A"], (1, 9, 1))
        self.assertEqual(sides["B"], (1, 9, 0))


class TestCase4_FinalBlockSplitNameLayoutMenDiv3(unittest.TestCase):
    """Test case 4 — Final block (split-name layout, Men Div 3).

    'Final' label at [67,16]; pair-A name at [70,16]+[71,16] (split across
    two rows), pair-A scores at row 71; pair-B name at [73,16]+[74,16],
    pair-B scores at row 73.

    round = 'final', division = 'Men Division 3' (no group suffix).
    Side A: Dunstan Vella / Cyril Lastimosa
    Side B: Neville Sciriha / Matthias Sciriha
    Set 1: A=6, B=7 ; Set 2: A=0, B=6 ; no super-tb.
    Side B wins.
    """

    def test_match_present_with_correct_sets_and_winner(self):
        conn = _LoadedDB.get()
        mid = _find_match_by_pairs(
            conn,
            "Men Division 3",
            ("Dunstan Vella", "Cyril Lastimosa"),
            ("Neville Sciriha", "Matthias Sciriha"),
            round_label="final",
        )
        sets = conn.execute(
            "SELECT set_number, side_a_games, side_b_games, was_tiebreak "
            "FROM match_set_scores WHERE match_id = ? ORDER BY set_number",
            (mid,),
        ).fetchall()
        # Set 1 has a 7 in it → was_tiebreak=True per the spec rule.
        self.assertEqual(sets, [(1, 6, 7, 1), (2, 0, 6, 0)])

        sides = dict(
            (side, (sets_won, games_won, won))
            for side, sets_won, games_won, won in conn.execute(
                "SELECT side, sets_won, games_won, won FROM match_sides WHERE match_id = ?",
                (mid,),
            )
        )
        self.assertEqual(sides["A"], (0, 6, 0))
        self.assertEqual(sides["B"], (2, 13, 1))


class TestCase5_LadDiv1UnplayedMatchSkipped(unittest.TestCase):
    """Test case 5 — Lad Div 1 unplayed match (must NOT insert).

    Sheet Lad Div 1, r=13, left block: Renette Magro/Diane Fenech vs
    Martina Cuschieri/Elaine Grech — all score cells blank → skip.

    Counter-example same row-band right block r=13: Renette Magro/Diane
    Fenech vs Kim Fava/Annmarie Mangion. Per the actual cell values in the
    file (`[13,17]=6, [15,17]=3, [13,20]=4, [15,20]=6, [13,23]=6, [15,23]=10`),
    set1 = 6-3, set2 = 4-6, super-tb = 6-10 → Side B wins.

    NOTE — spec deviation: the spec text says "set 1 = 6-4" but the file
    actually has set 1 = 6-3 (cell [15,17]=3.0). The parser follows the file.
    """

    def test_left_block_unplayed_not_inserted(self):
        conn = _LoadedDB.get()
        # The unplayed left-block match (Renette Magro/Diane Fenech vs Martina
        # Cuschieri/Elaine Grech) should NOT exist in matches at all.
        with self.assertRaises(AssertionError):
            _find_match_by_pairs(
                conn,
                "Ladies Division 1",
                ("Renette Magro", "Diane Fenech"),
                ("Martina Cuschieri", "Elaine Grech"),
            )

    def test_right_block_played_match_inserted_correctly(self):
        conn = _LoadedDB.get()
        mid = _find_match_by_pairs(
            conn,
            "Ladies Division 1",
            ("Renette Magro", "Diane Fenech"),
            ("Kim Fava", "Annmarie Mangion"),
        )
        sets = conn.execute(
            "SELECT set_number, side_a_games, side_b_games, was_tiebreak "
            "FROM match_set_scores WHERE match_id = ? ORDER BY set_number",
            (mid,),
        ).fetchall()
        self.assertEqual(sets, [(1, 6, 3, 0), (2, 4, 6, 0), (3, 6, 10, 1)])

        sides = dict(
            (side, (sets_won, games_won, won))
            for side, sets_won, games_won, won in conn.execute(
                "SELECT side, sets_won, games_won, won FROM match_sides WHERE match_id = ?",
                (mid,),
            )
        )
        # games_won = sum of regular sets only: A=6+4=10, B=3+6=9
        self.assertEqual(sides["A"], (1, 10, 0))
        self.assertEqual(sides["B"], (1, 9, 1))

    def test_quality_report_records_skipped_matches(self):
        conn = _LoadedDB.get()
        # Find the latest ingestion run; inspect its quality_report_jsonb for
        # the entry describing the unplayed left-block match at row 13.
        import json

        row = conn.execute(
            "SELECT quality_report_jsonb FROM ingestion_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        report = json.loads(row[0])
        skipped = report["skipped_unplayed_matches"]
        self.assertTrue(
            any(
                e["sheet"] == "Lad Div 1"
                and e["row"] == 13
                and e["block"] == "left"
                and e["pair_A"] == "Renette Magro/Diane Fenech"
                and e["pair_B"] == "Martina Cuschieri/Elaine Grech"
                for e in skipped
            ),
            f"expected unplayed entry not found in quality_report. skipped={skipped!r}",
        )


class TestCase6_StandingsCrossValidation(unittest.TestCase):
    """Test case 6 (cross-validation) — Standings sum check.

    After parsing all 15 matches, sum the per-set games for
    Duncan D'Alessandro / Clayton Zammit Cesare across every row where they
    appear as side A or side B.

    Spec expected: games_won = 59, matches_played = 5.

    NOTE on `sets_won`: the spec tests 1 and 2 establish that `sets_won`
    counts only regular (non-super-tb) sets. Under that rule, the per-match
    sums give sets_won = 9 for this pair (one match was won via super-tb,
    so its sets_won contribution is 1 instead of 2). The standings panel in
    the file shows 10 because the file's formulas count the super-tb as a
    set won. That is a model-vs-data convention difference, not a parser
    bug — see PLAN.md §5.2 'games won' definition.
    """

    def test_pair_aggregate_games_and_matches(self):
        conn = _LoadedDB.get()
        duncan_id = conn.execute(
            "SELECT id FROM players WHERE canonical_name = ?",
            ("Duncan D'Alessandro",),
        ).fetchone()[0]
        clayton_id = conn.execute(
            "SELECT id FROM players WHERE canonical_name = ?",
            ("Clayton Zammit Cesare",),
        ).fetchone()[0]

        # Sum across all rows where this pair appears on either side
        # (either ordering of the two players inside the pair).
        rows = conn.execute(
            """
            SELECT ms.games_won, ms.sets_won
            FROM match_sides ms
            JOIN matches m ON m.id = ms.match_id
            WHERE m.division = 'Men Division 1'
              AND (
                (ms.player1_id = ? AND ms.player2_id = ?)
                OR (ms.player1_id = ? AND ms.player2_id = ?)
              )
            """,
            (duncan_id, clayton_id, clayton_id, duncan_id),
        ).fetchall()

        self.assertEqual(len(rows), 5, f"expected 5 matches for the pair, got {len(rows)}")
        total_games = sum(r[0] for r in rows)
        total_sets = sum(r[1] for r in rows)
        self.assertEqual(total_games, 59)
        # Per the parser convention (super-tb is NOT a set won), the sum is 9.
        # This deliberately differs from the file's standings panel value of 10.
        self.assertEqual(total_sets, 9)


# ─────────────────────────────────────────────────────────────────────────────
# Re-process / supersede test (acceptance criterion #4 in T-P0-004).
# Use a fresh DB (not the shared _LoadedDB) since this mutates state across runs.
# ─────────────────────────────────────────────────────────────────────────────

class TestReprocessAndSupersede(unittest.TestCase):
    def test_second_load_creates_new_run_and_supersedes_prior_matches(self):
        conn = db.init_db(":memory:")
        try:
            run_id_1 = parser.parse(XLSX_PATH, conn)
            n_active_after_1 = conn.execute(
                "SELECT COUNT(*) FROM matches WHERE superseded_by_run_id IS NULL"
            ).fetchone()[0]
            n_total_after_1 = conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
            self.assertGreater(n_active_after_1, 0)
            self.assertEqual(n_active_after_1, n_total_after_1)

            run_id_2 = parser.parse(XLSX_PATH, conn)
            self.assertNotEqual(run_id_1, run_id_2)

            # First run is now superseded; its matches all carry superseded_by_run_id = run_id_2.
            n_super_marked = conn.execute(
                "SELECT COUNT(*) FROM matches WHERE ingestion_run_id = ? AND superseded_by_run_id = ?",
                (run_id_1, run_id_2),
            ).fetchone()[0]
            self.assertEqual(n_super_marked, n_active_after_1)

            # supersedes_run_id on the new run points at the old run.
            row = conn.execute(
                "SELECT supersedes_run_id, status FROM ingestion_runs WHERE id = ?",
                (run_id_2,),
            ).fetchone()
            self.assertEqual(row[0], run_id_1)
            self.assertEqual(row[1], "completed")

            # Old run is now marked 'superseded'.
            old_status = conn.execute(
                "SELECT status FROM ingestion_runs WHERE id = ?", (run_id_1,)
            ).fetchone()[0]
            self.assertEqual(old_status, "superseded")

            # New run's matches are active.
            n_active_after_2 = conn.execute(
                "SELECT COUNT(*) FROM matches WHERE superseded_by_run_id IS NULL"
            ).fetchone()[0]
            self.assertEqual(n_active_after_2, n_active_after_1)

            # Source file: same sha → reused, only one source_files row.
            n_source_files = conn.execute("SELECT COUNT(*) FROM source_files").fetchone()[0]
            self.assertEqual(n_source_files, 1)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
