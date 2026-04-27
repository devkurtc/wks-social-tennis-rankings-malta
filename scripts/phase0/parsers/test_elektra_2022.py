"""Tests for the Elektra 2022 cross-tab matrix parser.

One test per "Suggested parser test case" in
`scripts/phase0/parser_spec_elektra_2022.md`, plus reprocess + smoke tests.

Run from repo root:
    scripts/phase0/.venv/bin/python -m unittest \
        scripts/phase0/parsers/test_elektra_2022.py -v
"""

from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))            # for elektra_2022, sports_experience_2025
sys.path.insert(0, str(HERE.parent))     # for db / players

import db  # noqa: E402
import elektra_2022 as parser  # noqa: E402
from _test_fixtures import locate as _locate  # noqa: E402

REPO_ROOT = HERE.parent.parent.parent
ELEKTRA_2022 = (
    _locate("Draws and Results Elektra Mixed Doubles 2022.xlsx") or ""
)


def _player_name(conn: sqlite3.Connection, pid: int) -> str:
    return conn.execute(
        "SELECT canonical_name FROM players WHERE id = ?", (pid,)
    ).fetchone()[0]


def _find_match_by_pairs(
    conn: sqlite3.Connection,
    division: str,
    pair_x: tuple[str, str],
    pair_y: tuple[str, str],
    round_label: str | None = None,
) -> int:
    """Return match_id for the (division, pair_x, pair_y) match.

    Side assignment in the cross-tab matrix is "row pair = side A; column pair
    = side B" (i.e. the pair whose row in the matrix is the LOW-numbered rank
    is side A). Tests therefore must pass the LOW-rank pair as pair_x.
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
        if (a_set == set(pair_x) and b_set == set(pair_y)) or (
            a_set == set(pair_y) and b_set == set(pair_x)
        ):
            matches.append(mid)
    if not matches:
        raise AssertionError(
            f"no match in division={division!r} round={round_label!r} "
            f"with pairs {pair_x} vs {pair_y}"
        )
    if len(matches) > 1:
        raise AssertionError(f"multiple matches matched in division={division!r}: {matches}")
    return matches[0]


# ─────────────────────────────────────────────────────────────────────────────
# One-time per-class load to keep tests fast.
# ─────────────────────────────────────────────────────────────────────────────

class _LoadedDB:
    _conn: sqlite3.Connection | None = None

    @classmethod
    def get(cls) -> sqlite3.Connection:
        if cls._conn is None:
            if not ELEKTRA_2022:
                raise unittest.SkipTest(
                    "Elektra 2022 fixture not found in _DATA_/"
                )
            conn = db.init_db(":memory:")
            parser.parse(ELEKTRA_2022, conn)
            cls._conn = conn
        return cls._conn


# ─────────────────────────────────────────────────────────────────────────────
# Score-string parser unit tests (no DB needed)
# ─────────────────────────────────────────────────────────────────────────────

class TestParseScoreString(unittest.TestCase):
    """Direct tests for parse_score_string covering the score-string variants
    enumerated in the spec.
    """

    def test_clean_two_sets(self):
        r = parser.parse_score_string("7-5, 6-0")
        self.assertIsNotNone(r)
        self.assertEqual(r["sets"], [(1, 7, 5, 1), (2, 6, 0, 0)])
        self.assertFalse(r["walkover"])
        self.assertIsNone(r["super_tiebreak"])

    def test_super_tiebreak_with_TB_label(self):
        r = parser.parse_score_string("2-6, 6-4 TB 8-10")
        self.assertEqual(r["sets"], [(1, 2, 6, 0), (2, 6, 4, 0), (3, 8, 10, 1)])
        self.assertEqual(r["super_tiebreak"], (8, 10))

    def test_super_tiebreak_with_T_slash_B_label(self):
        r = parser.parse_score_string("2-6, 6-7 T/B 9-11")
        self.assertEqual(r["sets"], [(1, 2, 6, 0), (2, 6, 7, 1), (3, 9, 11, 1)])

    def test_super_tiebreak_no_label(self):
        # '6-4, 3-6 4-10' — the third \d-\d is the bare super-tb
        r = parser.parse_score_string("6-4, 3-6 4-10")
        self.assertEqual(r["sets"], [(1, 6, 4, 0), (2, 3, 6, 0), (3, 4, 10, 1)])

    def test_semicolon_separator(self):
        r = parser.parse_score_string("6-2; 4-6 TB 10-8")
        self.assertEqual(r["sets"], [(1, 6, 2, 0), (2, 4, 6, 0), (3, 10, 8, 1)])

    def test_no_space_after_comma(self):
        r = parser.parse_score_string("1-6,3-6")
        self.assertEqual(r["sets"], [(1, 1, 6, 0), (2, 3, 6, 0)])

    def test_embedded_newline_before_TB(self):
        r = parser.parse_score_string("6-3, 4-6\nTB 10-6")
        self.assertEqual(r["sets"], [(1, 6, 3, 0), (2, 4, 6, 0), (3, 10, 6, 1)])

    def test_trailing_newline(self):
        r = parser.parse_score_string("1-6, 6-4 TB 10-4\n")
        self.assertEqual(r["sets"], [(1, 1, 6, 0), (2, 6, 4, 0), (3, 10, 4, 1)])

    def test_walkover_marker(self):
        r = parser.parse_score_string("6-0, 6-0 w/o")
        self.assertEqual(r["sets"], [(1, 6, 0, 0), (2, 6, 0, 0)])
        self.assertTrue(r["walkover"])

    def test_empty_or_none(self):
        self.assertIsNone(parser.parse_score_string(None))
        self.assertIsNone(parser.parse_score_string(""))
        self.assertIsNone(parser.parse_score_string("   "))

    def test_too_few_score_pairs(self):
        # Single score pair — not a valid match
        self.assertIsNone(parser.parse_score_string("6-3"))

    def test_too_many_score_pairs(self):
        # >3 score pairs — unexpected, return None
        self.assertIsNone(parser.parse_score_string("6-3, 6-4 7-5 6-2 8-6"))


# ─────────────────────────────────────────────────────────────────────────────
# Test 1 — Div 1: rank 1 vs rank 2 — clean two-set win
# ─────────────────────────────────────────────────────────────────────────────

class TestDiv1_Rank1vs2_CleanTwoSet(unittest.TestCase):
    """Div 1 row 5 col 4 = '7-5, 6-0' (Marc Vella Bonnici/Martina Cuschieri
    vs Jean Carl Azzopardi/Erika Azzopardi). Side A wins 2-0; first set has
    a 7 → was_tiebreak=1.
    """

    def test_match_present_with_correct_sets_and_winner(self):
        conn = _LoadedDB.get()
        mid = _find_match_by_pairs(
            conn,
            "Division 1",
            ("Vella Bonnici Marc", "Cuschieri Martina"),
            ("Azzopardi Jean Carl", "Azzopardi Erika"),
        )
        sets = conn.execute(
            "SELECT set_number, side_a_games, side_b_games, was_tiebreak "
            "FROM match_set_scores WHERE match_id = ? ORDER BY set_number",
            (mid,),
        ).fetchall()
        self.assertEqual(sets, [(1, 7, 5, 1), (2, 6, 0, 0)])

        sides = dict(
            (side, (sw, gw, won))
            for side, sw, gw, won in conn.execute(
                "SELECT side, sets_won, games_won, won FROM match_sides WHERE match_id = ?",
                (mid,),
            )
        )
        self.assertEqual(sides["A"], (2, 13, 1))
        self.assertEqual(sides["B"], (0, 5, 0))

        walkover = conn.execute(
            "SELECT walkover FROM matches WHERE id = ?", (mid,)
        ).fetchone()[0]
        self.assertEqual(walkover, 0)


# ─────────────────────────────────────────────────────────────────────────────
# Test 2 — Div 1: rank 2 vs rank 4 — super-tiebreak decides
# ─────────────────────────────────────────────────────────────────────────────

class TestDiv1_Rank2vs4_SuperTiebreak(unittest.TestCase):
    """Div 1 row 6 col 6 = '2-6, 6-4 TB 8-10' (Jean Carl Azzopardi/Erika
    Azzopardi vs Trevor Rutter/Alison Muscat).
    Sets 1-1, super-tb 8-10 → side B wins.
    """

    def test_match_present_with_correct_sets_and_winner(self):
        conn = _LoadedDB.get()
        mid = _find_match_by_pairs(
            conn,
            "Division 1",
            ("Azzopardi Jean Carl", "Azzopardi Erika"),
            ("Rutter Trevor", "Muscat Alison"),
        )
        sets = conn.execute(
            "SELECT set_number, side_a_games, side_b_games, was_tiebreak "
            "FROM match_set_scores WHERE match_id = ? ORDER BY set_number",
            (mid,),
        ).fetchall()
        self.assertEqual(sets, [(1, 2, 6, 0), (2, 6, 4, 0), (3, 8, 10, 1)])

        sides = dict(
            (side, (sw, gw, won))
            for side, sw, gw, won in conn.execute(
                "SELECT side, sets_won, games_won, won FROM match_sides WHERE match_id = ?",
                (mid,),
            )
        )
        # Sets 1-1; games_won counts only regular sets.
        self.assertEqual(sides["A"], (1, 8, 0))
        self.assertEqual(sides["B"], (1, 10, 1))


# ─────────────────────────────────────────────────────────────────────────────
# Test 3 — Div 3: walkover marker on '6-0, 6-0 w/o'
# ─────────────────────────────────────────────────────────────────────────────

class TestDiv3_WalkoverFlag(unittest.TestCase):
    """Div 3 row 5 col 4 = '6-0, 6-0 w/o' (Mavric Sawyer/Alexia Gouder vs
    Manuel Bonello/Josette D'Alessandro).
    Side A wins 2-0; matches.walkover = 1.
    """

    def test_walkover_match_present_and_flagged(self):
        conn = _LoadedDB.get()
        mid = _find_match_by_pairs(
            conn,
            "Division 3",
            ("Sawyer Mavric", "Gouder Alexia"),
            ("Bonello Manuel", "D'Alessandro Josette"),
        )
        sets = conn.execute(
            "SELECT set_number, side_a_games, side_b_games, was_tiebreak "
            "FROM match_set_scores WHERE match_id = ? ORDER BY set_number",
            (mid,),
        ).fetchall()
        self.assertEqual(sets, [(1, 6, 0, 0), (2, 6, 0, 0)])

        walkover = conn.execute(
            "SELECT walkover FROM matches WHERE id = ?", (mid,)
        ).fetchone()[0]
        self.assertEqual(walkover, 1)

        sides = dict(
            (side, (sw, gw, won))
            for side, sw, gw, won in conn.execute(
                "SELECT side, sets_won, games_won, won FROM match_sides WHERE match_id = ?",
                (mid,),
            )
        )
        self.assertEqual(sides["A"], (2, 12, 1))
        self.assertEqual(sides["B"], (0, 0, 0))


# ─────────────────────────────────────────────────────────────────────────────
# Test 4 — Div 5 A: cross-group Final string in row 15
# ─────────────────────────────────────────────────────────────────────────────

class TestDiv5_FinalRowParsed(unittest.TestCase):
    """Div 5 A row 15 col 2 = 'Final: Denis Caruana/Jennifer Mifsud vs Clint
    Agius/Laureen Agius 1-6, 6-7' → division 'Division 5' (group suffix
    dropped), round 'final', side B wins 2-0.
    """

    def test_final_present_and_correct(self):
        conn = _LoadedDB.get()
        mid = _find_match_by_pairs(
            conn,
            "Division 5",
            ("Denis Caruana", "Jennifer Mifsud"),
            ("Clint Agius", "Laureen Agius"),
            round_label="final",
        )
        sets = conn.execute(
            "SELECT set_number, side_a_games, side_b_games, was_tiebreak "
            "FROM match_set_scores WHERE match_id = ? ORDER BY set_number",
            (mid,),
        ).fetchall()
        # Set 2 has '6-7' → was_tiebreak=1 (a 7 was scored)
        self.assertEqual(sets, [(1, 1, 6, 0), (2, 6, 7, 1)])

        sides = dict(
            (side, (sw, gw, won))
            for side, sw, gw, won in conn.execute(
                "SELECT side, sets_won, games_won, won FROM match_sides WHERE match_id = ?",
                (mid,),
            )
        )
        self.assertEqual(sides["A"], (0, 7, 0))
        self.assertEqual(sides["B"], (2, 13, 1))


# ─────────────────────────────────────────────────────────────────────────────
# Test 5 — Smoke: total match counts + per-division coverage
# ─────────────────────────────────────────────────────────────────────────────

class TestSmokeMatchCounts(unittest.TestCase):
    def test_total_matches_at_or_above_expected(self):
        conn = _LoadedDB.get()
        n = conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
        # 5 RR + 6 RR + 6 RR + 6 RR + 5 RR + 5 RR = 5+15+15+15+10+10 = 70 RR
        # plus 1 cross-group final = 71 minimum if some Div cells were unplayed.
        # Observed file has 75 RR + 1 final = 76. Allow some tolerance.
        self.assertGreaterEqual(n, 71, f"too few matches: {n}")

    def test_each_division_has_at_least_one_match(self):
        conn = _LoadedDB.get()
        divs = dict(conn.execute(
            "SELECT division, COUNT(*) FROM matches GROUP BY division"
        ).fetchall())
        for d in ("Division 1", "Division 2", "Division 3", "Division 4",
                  "Division 5 - Group A", "Division 5 - Group B", "Division 5"):
            self.assertGreaterEqual(divs.get(d, 0), 1, f"division {d!r} empty")

    def test_no_gender_set(self):
        # Mixed doubles → players.gender stays NULL
        conn = _LoadedDB.get()
        n_with_gender = conn.execute(
            "SELECT COUNT(*) FROM players WHERE gender IS NOT NULL"
        ).fetchone()[0]
        self.assertEqual(n_with_gender, 0)


# ─────────────────────────────────────────────────────────────────────────────
# Test 6 — Re-process / supersede flow
# ─────────────────────────────────────────────────────────────────────────────

class TestReprocessAndSupersede(unittest.TestCase):
    def test_second_load_supersedes_prior_run(self):
        conn = db.init_db(":memory:")
        try:
            run_id_1 = parser.parse(ELEKTRA_2022, conn)
            n_active = conn.execute(
                "SELECT COUNT(*) FROM matches WHERE superseded_by_run_id IS NULL"
            ).fetchone()[0]
            self.assertGreater(n_active, 0)

            run_id_2 = parser.parse(ELEKTRA_2022, conn)
            self.assertNotEqual(run_id_1, run_id_2)

            n_super = conn.execute(
                "SELECT COUNT(*) FROM matches WHERE ingestion_run_id = ? AND superseded_by_run_id = ?",
                (run_id_1, run_id_2),
            ).fetchone()[0]
            self.assertEqual(n_super, n_active)

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

            n_files = conn.execute("SELECT COUNT(*) FROM source_files").fetchone()[0]
            self.assertEqual(n_files, 1)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
