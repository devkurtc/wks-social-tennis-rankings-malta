"""Tests for the TCK Chosen Tournament Divisions 2024 parser.

One test per "Suggested parser test case" in
`scripts/phase0/parser_spec_tck_chosen_2024.md`.

Run from repo root:
    python -m unittest scripts.phase0.parsers.test_tck_chosen_2024 -v

Or directly:
    scripts/phase0/.venv/bin/python -m unittest \
        scripts/phase0/parsers/test_tck_chosen_2024.py -v
"""

from __future__ import annotations

import os
import sqlite3
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))            # for tck_chosen_2024 + sports_experience_2025
sys.path.insert(0, str(HERE.parent))     # for db / players

import db  # noqa: E402
import tck_chosen_2024 as parser  # noqa: E402

REPO_ROOT = HERE.parent.parent.parent
from _test_fixtures import locate as _locate  # noqa: E402
TCK_2024 = _locate("TCK CHOSEN TOUNAMENT DIVISIONS 2024.xlsx") or ""


def _player_name(conn: sqlite3.Connection, pid: int) -> str:
    return conn.execute("SELECT canonical_name FROM players WHERE id = ?", (pid,)).fetchone()[0]


def _find_match_by_pairs(
    conn: sqlite3.Connection,
    division: str,
    side_a_names: tuple[str, str],
    side_b_names: tuple[str, str],
    played_on: str | None = None,
) -> int:
    """Return the unique match_id matching (division, side A pair, side B pair).

    Player names compared as a SET on each side so the order within a pair
    does not matter. Optionally filter by played_on to disambiguate when two
    pairs play each other twice in the same tournament (round-robin home + away).
    """
    candidates = conn.execute(
        "SELECT m.id, m.played_on FROM matches m WHERE m.division = ?", (division,)
    ).fetchall()
    matches: list[int] = []
    for mid, p_on in candidates:
        if played_on is not None and p_on != played_on:
            continue
        sides = conn.execute(
            "SELECT side, player1_id, player2_id FROM match_sides WHERE match_id = ?",
            (mid,),
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
            f"no match found in division={division!r} on={played_on!r} "
            f"with side A={side_a_names} side B={side_b_names}"
        )
    if len(matches) > 1:
        raise AssertionError(
            f"multiple matches matched in division={division!r}: {matches}"
        )
    return matches[0]


# ─────────────────────────────────────────────────────────────────────────────
# One-time per-class load to keep tests fast.
# ─────────────────────────────────────────────────────────────────────────────

class _LoadedDB:
    _conn: sqlite3.Connection | None = None

    @classmethod
    def get(cls) -> sqlite3.Connection:
        if cls._conn is None:
            cls._conn = db.init_db(":memory:")
            parser.parse(TCK_2024, cls._conn)
        return cls._conn


# ─────────────────────────────────────────────────────────────────────────────
# Test 1 — MEN 1ST DIV r17: clean 2-set match (Adrian Manduca / Farrugia
#                                              Melchior vs Magri Gareth/Daryl)
# ─────────────────────────────────────────────────────────────────────────────

class TestMen1Div_StraightSets(unittest.TestCase):
    def test_match_inserted_correctly(self):
        conn = _LoadedDB.get()
        mid = _find_match_by_pairs(
            conn,
            "Men Division 1",
            ("ADRIAN MANDUCA", "FARRUGIA MELCHIOR"),
            ("MAGRI GARETH", "MAGRI DARYL"),
            played_on="2024-06-30",
        )

        # Match: walkover=0, doubles, division correct, played_on correct
        row = conn.execute(
            "SELECT match_type, division, played_on, walkover FROM matches WHERE id = ?",
            (mid,),
        ).fetchone()
        self.assertEqual(row[0], "doubles")
        self.assertEqual(row[1], "Men Division 1")
        self.assertEqual(row[2], "2024-06-30")
        self.assertEqual(row[3], 0)

        # Set scores: (1, 7, 5, 1=tiebreak), (2, 6, 1, 0)
        sets = conn.execute(
            "SELECT set_number, side_a_games, side_b_games, was_tiebreak "
            "FROM match_set_scores WHERE match_id = ? ORDER BY set_number",
            (mid,),
        ).fetchall()
        self.assertEqual(sets, [(1, 7, 5, 1), (2, 6, 1, 0)])

        # Side A wins, sets_won=2, games_won=13; Side B sets_won=0, games_won=6
        sides = dict(
            (s, (sw, gw, won))
            for s, sw, gw, won in conn.execute(
                "SELECT side, sets_won, games_won, won FROM match_sides WHERE match_id = ?",
                (mid,),
            ).fetchall()
        )
        self.assertEqual(sides["A"], (2, 13, 1))
        self.assertEqual(sides["B"], (0, 6, 0))


# ─────────────────────────────────────────────────────────────────────────────
# Test 2 — MEN 1ST DIV r18: 'W/O' walkover
# ─────────────────────────────────────────────────────────────────────────────

class TestMen1Div_Walkover_WO(unittest.TestCase):
    def test_walkover_inserted_with_placeholder_score(self):
        conn = _LoadedDB.get()
        mid = _find_match_by_pairs(
            conn,
            "Men Division 1",
            ("MICALLEF NIKOLAI", "BORG MATTEW"),
            ("SCHEMBRI DAVID", "ATTARD JEAN PIERRE"),
            played_on="2024-06-30",
        )

        row = conn.execute(
            "SELECT walkover, played_on FROM matches WHERE id = ?", (mid,)
        ).fetchone()
        self.assertEqual(row[0], 1, "walkover flag must be set")
        self.assertEqual(row[1], "2024-06-30")

        # Placeholder set score: (1, 6, 0, 0)
        sets = conn.execute(
            "SELECT set_number, side_a_games, side_b_games, was_tiebreak "
            "FROM match_set_scores WHERE match_id = ? ORDER BY set_number",
            (mid,),
        ).fetchall()
        self.assertEqual(sets, [(1, 6, 0, 0)])

        # Side A wins by walkover default
        sides = dict(
            (s, won) for s, won in conn.execute(
                "SELECT side, won FROM match_sides WHERE match_id = ?", (mid,)
            ).fetchall()
        )
        self.assertEqual(sides["A"], 1)
        self.assertEqual(sides["B"], 0)


# ─────────────────────────────────────────────────────────────────────────────
# Test 3 — MEN 1ST DIV r24: 'W/0' typo variant — same handling as W/O
# ─────────────────────────────────────────────────────────────────────────────

class TestMen1Div_Walkover_W0_Typo(unittest.TestCase):
    def test_w0_typo_treated_as_walkover(self):
        conn = _LoadedDB.get()
        mid = _find_match_by_pairs(
            conn,
            "Men Division 1",
            ("SCHEMBRI DAVID", "ATTARD JEAN PIERRE"),
            ("MAGRI GARETH", "MAGRI DARYL"),
            played_on="2024-07-21",
        )

        walkover = conn.execute(
            "SELECT walkover FROM matches WHERE id = ?", (mid,)
        ).fetchone()[0]
        self.assertEqual(walkover, 1)

        # Placeholder set score
        sets = conn.execute(
            "SELECT set_number, side_a_games, side_b_games, was_tiebreak "
            "FROM match_set_scores WHERE match_id = ? ORDER BY set_number",
            (mid,),
        ).fetchall()
        self.assertEqual(sets, [(1, 6, 0, 0)])


# ─────────────────────────────────────────────────────────────────────────────
# Test 4 — MEN 1ST DIV r26: super-tiebreak match '6-4   5-7   10-4'
# ─────────────────────────────────────────────────────────────────────────────

class TestMen1Div_SuperTiebreak(unittest.TestCase):
    def test_supertb_match_parsed(self):
        conn = _LoadedDB.get()
        mid = _find_match_by_pairs(
            conn,
            "Men Division 1",
            ("CASSAR CLINT", "MIFSUD MATTHEW JOHN"),
            ("RUTTER TREVOR", "AZZOPARDI JEAN KARL"),
            played_on="2024-07-28",
        )

        sets = conn.execute(
            "SELECT set_number, side_a_games, side_b_games, was_tiebreak "
            "FROM match_set_scores WHERE match_id = ? ORDER BY set_number",
            (mid,),
        ).fetchall()
        # Set 1: 6-4 normal (no tiebreak); Set 2: 5-7 with tiebreak flag (7 in score);
        # Set 3: 10-4 super-tiebreak (was_tiebreak=1).
        self.assertEqual(sets, [(1, 6, 4, 0), (2, 5, 7, 1), (3, 10, 4, 1)])

        # Side A wins: 1 set + super-TB. Sets-won counted only for normal sets:
        # A=1, B=1; super-TB decides → A wins.
        sides = dict(
            (s, (sw, gw, won)) for s, sw, gw, won in conn.execute(
                "SELECT side, sets_won, games_won, won FROM match_sides WHERE match_id = ?",
                (mid,),
            ).fetchall()
        )
        # games_won uses regular sets only (excludes super-TB):
        self.assertEqual(sides["A"], (1, 11, 1))   # 6+5 = 11
        self.assertEqual(sides["B"], (1, 11, 0))   # 4+7 = 11

        walkover = conn.execute(
            "SELECT walkover FROM matches WHERE id = ?", (mid,)
        ).fetchone()[0]
        self.assertEqual(walkover, 0)


# ─────────────────────────────────────────────────────────────────────────────
# Test 5 — LDYS 1ST DIV r17: SCRATCHED in col 8 with a real score in col 9
# ─────────────────────────────────────────────────────────────────────────────

class TestLdys1Div_ScratchedWithOverrideScore(unittest.TestCase):
    def test_scratched_uses_col9_score(self):
        conn = _LoadedDB.get()
        mid = _find_match_by_pairs(
            conn,
            "Ladies Division 1",
            ("FAVA ANNA", "ANDREOZZI LUISA"),
            ("FENECH DIANE", "MAGRO RENETTE"),
            played_on="2024-06-30",
        )

        walkover = conn.execute(
            "SELECT walkover FROM matches WHERE id = ?", (mid,)
        ).fetchone()[0]
        self.assertEqual(walkover, 1, "SCRATCHED must set walkover=1")

        # Set rows from col-9 score '2-6   3-6'
        sets = conn.execute(
            "SELECT set_number, side_a_games, side_b_games, was_tiebreak "
            "FROM match_set_scores WHERE match_id = ? ORDER BY set_number",
            (mid,),
        ).fetchall()
        self.assertEqual(sets, [(1, 2, 6, 0), (2, 3, 6, 0)])

        # Winner is determined from the recorded score: side B wins both sets.
        sides = dict(
            (s, won) for s, won in conn.execute(
                "SELECT side, won FROM match_sides WHERE match_id = ?", (mid,)
            ).fetchall()
        )
        self.assertEqual(sides["A"], 0)
        self.assertEqual(sides["B"], 1)


# ─────────────────────────────────────────────────────────────────────────────
# Test 6 — MEN 3RD DIV r23: trailing-whitespace score '3-6   7-5   10-5   '
# ─────────────────────────────────────────────────────────────────────────────

class TestMen3Div_TrailingWhitespaceScore(unittest.TestCase):
    def test_trailing_whitespace_score_parses_clean(self):
        conn = _LoadedDB.get()
        mid = _find_match_by_pairs(
            conn,
            "Men Division 3",
            ("ELLUL FRANS", "RICCI MARCO"),
            ("FARRUGIA KENNETH", "CACHIA SEAN"),
            played_on="2024-07-26",
        )

        sets = conn.execute(
            "SELECT set_number, side_a_games, side_b_games, was_tiebreak "
            "FROM match_set_scores WHERE match_id = ? ORDER BY set_number",
            (mid,),
        ).fetchall()
        # Set 3 super-TB (10-5)
        self.assertEqual(sets, [(1, 3, 6, 0), (2, 7, 5, 1), (3, 10, 5, 1)])

        sides = dict(
            (s, won) for s, won in conn.execute(
                "SELECT side, won FROM match_sides WHERE match_id = ?", (mid,)
            ).fetchall()
        )
        # A wins: 1 normal set + super-TB
        self.assertEqual(sides["A"], 1)


# ─────────────────────────────────────────────────────────────────────────────
# Test 7 — Tournament-level smoke: name + format + match count sanity
# ─────────────────────────────────────────────────────────────────────────────

class TestTournamentSmoke(unittest.TestCase):
    def test_tournament_metadata_and_count(self):
        conn = _LoadedDB.get()
        t = conn.execute(
            "SELECT name, year, format FROM tournaments LIMIT 1"
        ).fetchone()
        self.assertIsNotNone(t)
        self.assertEqual(t[1], 2024)
        self.assertEqual(t[2], "doubles_division")
        # name should mention TCK / TOURNAMENT
        self.assertIn("TCK", t[0].upper())

        n_matches = conn.execute(
            "SELECT COUNT(*) FROM matches WHERE superseded_by_run_id IS NULL"
        ).fetchone()[0]
        # We observed 84 result-bearing rows in the source file.
        # Allow a small tolerance — the parser may legitimately skip a row
        # for reasons we want to surface in stderr.
        self.assertGreaterEqual(n_matches, 80, f"expected ~84 matches, got {n_matches}")
        self.assertLessEqual(n_matches, 90, f"expected ~84 matches, got {n_matches}")


if __name__ == "__main__":
    unittest.main()
