"""Tests for the Mixed Doubles parser.

One test per "Suggested parser test case" in
`scripts/phase0/parser_spec_mixed_doubles.md`.

Run from repo root:
    python -m unittest scripts.phase0.parsers.test_mixed_doubles -v

Or directly:
    scripts/phase0/.venv/bin/python -m unittest \
        scripts/phase0/parsers/test_mixed_doubles.py -v
"""

from __future__ import annotations

import os
import sqlite3
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))            # for mixed_doubles, sports_experience_2025
sys.path.insert(0, str(HERE.parent))     # for db / players

import db  # noqa: E402
import mixed_doubles as parser  # noqa: E402

REPO_ROOT = HERE.parent.parent.parent
from _test_fixtures import locate as _locate  # noqa: E402
ESS_2025 = _locate("ESS Mixed Tournament Div and Results 2025.xlsx") or ""
ESS_2024 = _locate("ESS Mixed Tournament Div and Results 2024.xlsx") or ""
ELEKTRA_2023 = _locate("Elektra Mixed Tournament Div and Results 2023.xlsx") or ""


def _player_name(conn: sqlite3.Connection, pid: int) -> str:
    return conn.execute("SELECT canonical_name FROM players WHERE id = ?", (pid,)).fetchone()[0]


def _find_match_by_pairs(
    conn: sqlite3.Connection,
    division: str,
    side_a_names: tuple[str, str],
    side_b_names: tuple[str, str],
    round_label: str | None = None,
) -> int:
    """Return the unique match_id matching (division, side A pair, side B pair).

    Player names compared as a SET on each side so the order within a pair
    does not matter.
    """
    candidates = conn.execute(
        "SELECT m.id, m.round FROM matches m WHERE m.division = ?", (division,)
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
        a_set = {_player_name(conn, side_map["A"][0]), _player_name(conn, side_map["A"][1])}
        b_set = {_player_name(conn, side_map["B"][0]), _player_name(conn, side_map["B"][1])}
        if a_set == set(side_a_names) and b_set == set(side_b_names):
            matches.append(mid)
    if not matches:
        raise AssertionError(
            f"no match found in division={division!r} round={round_label!r} "
            f"with side A={side_a_names} side B={side_b_names}"
        )
    if len(matches) > 1:
        raise AssertionError(f"multiple matches matched in division={division!r}: {matches}")
    return matches[0]


# ─────────────────────────────────────────────────────────────────────────────
# One-time per-class load to keep tests fast.
# ─────────────────────────────────────────────────────────────────────────────

class _LoadedDB:
    _instances: dict[str, sqlite3.Connection] = {}

    @classmethod
    def get(cls, xlsx_path: str) -> sqlite3.Connection:
        if xlsx_path not in cls._instances:
            conn = db.init_db(":memory:")
            parser.parse(xlsx_path, conn)
            cls._instances[xlsx_path] = conn
        return cls._instances[xlsx_path]


# ─────────────────────────────────────────────────────────────────────────────
# Test 1 — ESS 2025 Division 1, second match left block (clean tiebreak set)
# ─────────────────────────────────────────────────────────────────────────────

class TestESS2025_Div1_TiebreakWin(unittest.TestCase):
    """Sheet Division 1, anchor r=13 left block.

    Side A: Matthew Mifsud / Lara Pule'
    Side B: Duncan D'alessandro / Renette Magro
    Set 1: A=5, B=7 (was_tiebreak=True per the 7 rule)
    Set 2: A=0, B=6
    No super-tb. Side B wins 0-2.
    """

    def test_match_present_with_correct_sets_and_winner(self):
        conn = _LoadedDB.get(ESS_2025)
        mid = _find_match_by_pairs(
            conn,
            "Division 1",
            ("Matthew Mifsud", "Lara Pule'"),
            ("Duncan D'alessandro", "Renette Magro"),
        )
        sets = conn.execute(
            "SELECT set_number, side_a_games, side_b_games, was_tiebreak "
            "FROM match_set_scores WHERE match_id = ? ORDER BY set_number",
            (mid,),
        ).fetchall()
        self.assertEqual(sets, [(1, 5, 7, 1), (2, 0, 6, 0)])

        sides = dict(
            (side, (sets_won, games_won, won))
            for side, sets_won, games_won, won in conn.execute(
                "SELECT side, sets_won, games_won, won FROM match_sides WHERE match_id = ?",
                (mid,),
            )
        )
        self.assertEqual(sides["A"], (0, 5, 0))
        self.assertEqual(sides["B"], (2, 13, 1))


# ─────────────────────────────────────────────────────────────────────────────
# Test 2 — ESS 2025 Division 6 Group A (label at row 5)
# ─────────────────────────────────────────────────────────────────────────────

class TestESS2025_Div6GroupA_FirstMatch(unittest.TestCase):
    """Sheet Division 6, label '[5,1]=Division 6 - Group A'.

    First match anchor r=9 left block.
    Side A: Dayle Scicluna / Alida Borg
    Side B: Dunstan Vella / Tiziana Spiteri
    Set 1: A=3, B=6 ; Set 2: A=6, B=4 ; Super-tb: A=10, B=5
    Side A wins.
    division == 'Division 6 - Group A'.
    """

    def test_match_present_with_correct_sets_and_winner(self):
        conn = _LoadedDB.get(ESS_2025)
        mid = _find_match_by_pairs(
            conn,
            "Division 6 - Group A",
            ("Dayle Scicluna", "Alida Borg"),
            ("Dunstan Vella", "Tiziana Spiteri"),
        )
        sets = conn.execute(
            "SELECT set_number, side_a_games, side_b_games, was_tiebreak "
            "FROM match_set_scores WHERE match_id = ? ORDER BY set_number",
            (mid,),
        ).fetchall()
        self.assertEqual(sets, [(1, 3, 6, 0), (2, 6, 4, 0), (3, 10, 5, 1)])

        sides = dict(
            (side, (sets_won, games_won, won))
            for side, sets_won, games_won, won in conn.execute(
                "SELECT side, sets_won, games_won, won FROM match_sides WHERE match_id = ?",
                (mid,),
            )
        )
        # games_won counts only regular sets (set 1 + set 2)
        self.assertEqual(sides["A"], (1, 9, 1))
        self.assertEqual(sides["B"], (1, 10, 0))


# ─────────────────────────────────────────────────────────────────────────────
# Test 3 — ESS 2025 Division 6 Group B (dynamically-positioned label at row 31)
# ─────────────────────────────────────────────────────────────────────────────

class TestESS2025_Div6GroupB_DynamicLabel(unittest.TestCase):
    """Sheet Division 6, label '[31,1]=Division 6 - Group B', first match r=35.

    Side A: Cory Greenland / Sabrina Xuereb
    Side B: Steve Gambin / Suzanne Gambin
    Set 1: A=6, B=2 ; Set 2: A=6, B=3 ; no super-tb
    Side A wins 2-0.
    division == 'Division 6 - Group B'.
    """

    def test_match_present_with_correct_sets_and_winner(self):
        conn = _LoadedDB.get(ESS_2025)
        mid = _find_match_by_pairs(
            conn,
            "Division 6 - Group B",
            ("Cory Greenland", "Sabrina Xuereb"),
            ("Steve Gambin", "Suzanne Gambin"),
        )
        sets = conn.execute(
            "SELECT set_number, side_a_games, side_b_games, was_tiebreak "
            "FROM match_set_scores WHERE match_id = ? ORDER BY set_number",
            (mid,),
        ).fetchall()
        self.assertEqual(sets, [(1, 6, 2, 0), (2, 6, 3, 0)])

        sides = dict(
            (side, (sets_won, games_won, won))
            for side, sets_won, games_won, won in conn.execute(
                "SELECT side, sets_won, games_won, won FROM match_sides WHERE match_id = ?",
                (mid,),
            )
        )
        self.assertEqual(sides["A"], (2, 12, 1))
        self.assertEqual(sides["B"], (0, 5, 0))


# ─────────────────────────────────────────────────────────────────────────────
# Test 4 — ESS 2025 Division 6 Final (single-row pair-string layout)
# ─────────────────────────────────────────────────────────────────────────────

class TestESS2025_Div6_Final(unittest.TestCase):
    """Sheet Division 6, '[58,16]=Final', pair A at row 62 (single row),
    pair B at row 64.

    Side A: Daye Scicluna/Alida Borg (note 'Daye' typo in file)
    Side B: Cory Greenland/Sabrina Xuereb
    Set 1: A=7, B=6 (was_tiebreak=True)
    Set 2: A=3, B=6
    Super-tb: A=7, B=10
    Side B wins.
    division == 'Division 6' (group suffix dropped for finals)
    round == 'final'
    """

    def test_match_present_with_correct_sets_and_winner(self):
        conn = _LoadedDB.get(ESS_2025)
        mid = _find_match_by_pairs(
            conn,
            "Division 6",
            ("Daye Scicluna", "Alida Borg"),
            ("Cory Greenland", "Sabrina Xuereb"),
            round_label="final",
        )
        sets = conn.execute(
            "SELECT set_number, side_a_games, side_b_games, was_tiebreak "
            "FROM match_set_scores WHERE match_id = ? ORDER BY set_number",
            (mid,),
        ).fetchall()
        self.assertEqual(sets, [(1, 7, 6, 1), (2, 3, 6, 0), (3, 7, 10, 1)])

        sides = dict(
            (side, (sets_won, games_won, won))
            for side, sets_won, games_won, won in conn.execute(
                "SELECT side, sets_won, games_won, won FROM match_sides WHERE match_id = ?",
                (mid,),
            )
        )
        # Sets 1-1 in regular sets; super-tb decides for B.
        self.assertEqual(sides["A"], (1, 10, 0))
        self.assertEqual(sides["B"], (1, 12, 1))


# ─────────────────────────────────────────────────────────────────────────────
# Test 5 — ESS 2024 Division 5 Group B (dynamic label at row 60)
# ─────────────────────────────────────────────────────────────────────────────

class TestESS2024_Div5GroupB_DynamicLabel(unittest.TestCase):
    """Sheet Division 5, label '[60,1]=Division 5 - Group B', first match r=64.

    Side A: Juan Sammut / Maria Angela Gambin
    Side B: Dayle Scicluna / Alida Borg
    Set 1: A=6, B=0 ; Set 2: A=6, B=3 ; no super-tb
    Side A wins 2-0.
    division == 'Division 5 - Group B'.
    """

    def test_match_present_with_correct_sets_and_winner(self):
        conn = _LoadedDB.get(ESS_2024)
        mid = _find_match_by_pairs(
            conn,
            "Division 5 - Group B",
            ("Juan Sammut", "Maria Angela Gambin"),
            ("Dayle Scicluna", "Alida Borg"),
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


# ─────────────────────────────────────────────────────────────────────────────
# Test 6 — Smoke test: file produces enough matches
# ─────────────────────────────────────────────────────────────────────────────

class TestPerFileMatchCounts(unittest.TestCase):
    """The parser must produce a reasonable number of matches per file —
    no division goes empty unless the source file has no matches there.
    """

    def test_ess_2025_count_in_range(self):
        conn = _LoadedDB.get(ESS_2025)
        n = conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
        self.assertGreaterEqual(n, 90, f"too few matches: {n}")
        # No empty-division surprises
        divs = conn.execute(
            "SELECT division, COUNT(*) FROM matches GROUP BY division"
        ).fetchall()
        for div, count in divs:
            self.assertGreaterEqual(count, 1, f"division {div!r} has 0 matches")

    def test_ess_2024_count_in_range(self):
        conn = _LoadedDB.get(ESS_2024)
        n = conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
        self.assertGreaterEqual(n, 90, f"too few matches: {n}")

    def test_elektra_2023_count_in_range(self):
        conn = _LoadedDB.get(ELEKTRA_2023)
        n = conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
        self.assertGreaterEqual(n, 80, f"too few matches: {n}")


# ─────────────────────────────────────────────────────────────────────────────
# Test 7 — Re-process / supersede flow
# ─────────────────────────────────────────────────────────────────────────────

class TestReprocessAndSupersede(unittest.TestCase):
    def test_second_load_supersedes_prior_run(self):
        conn = db.init_db(":memory:")
        try:
            run_id_1 = parser.parse(ESS_2025, conn)
            n_active = conn.execute(
                "SELECT COUNT(*) FROM matches WHERE superseded_by_run_id IS NULL"
            ).fetchone()[0]
            self.assertGreater(n_active, 0)

            run_id_2 = parser.parse(ESS_2025, conn)
            self.assertNotEqual(run_id_1, run_id_2)

            # Old matches now have superseded_by_run_id = new run
            n_super = conn.execute(
                "SELECT COUNT(*) FROM matches WHERE ingestion_run_id = ? AND superseded_by_run_id = ?",
                (run_id_1, run_id_2),
            ).fetchone()[0]
            self.assertEqual(n_super, n_active)

            # New run links to old via supersedes_run_id
            row = conn.execute(
                "SELECT supersedes_run_id, status FROM ingestion_runs WHERE id = ?",
                (run_id_2,),
            ).fetchone()
            self.assertEqual(row[0], run_id_1)
            self.assertEqual(row[1], "completed")

            # Old run marked 'superseded'
            old_status = conn.execute(
                "SELECT status FROM ingestion_runs WHERE id = ?", (run_id_1,)
            ).fetchone()[0]
            self.assertEqual(old_status, "superseded")

            # Same source file reused
            n_files = conn.execute("SELECT COUNT(*) FROM source_files").fetchone()[0]
            self.assertEqual(n_files, 1)
        finally:
            conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Test 8 — Mixed doubles parser does NOT set players.gender
# ─────────────────────────────────────────────────────────────────────────────

class TestNoGenderSet(unittest.TestCase):
    def test_all_players_have_null_gender(self):
        conn = _LoadedDB.get(ESS_2025)
        n_with_gender = conn.execute(
            "SELECT COUNT(*) FROM players WHERE gender IS NOT NULL"
        ).fetchone()[0]
        self.assertEqual(n_with_gender, 0)


if __name__ == "__main__":
    unittest.main()
