"""Tests for player normalization + alias storage (T-P0-005).

Run from repo root:
    python -m unittest scripts.phase0.test_players
or:
    python scripts/phase0/test_players.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# Allow `import db` and `import players` whether run as script or as module
sys.path.insert(0, str(Path(__file__).parent))

import db  # noqa: E402
import players  # noqa: E402


class TestNormalizeName(unittest.TestCase):
    def test_curly_right_apostrophe_to_straight(self):
        # U+2019 RIGHT SINGLE QUOTATION MARK — most common in Word/Excel
        self.assertEqual(players.normalize_name("D’Alessandro"), "D'Alessandro")

    def test_curly_left_apostrophe_to_straight(self):
        # U+2018 LEFT SINGLE QUOTATION MARK
        self.assertEqual(players.normalize_name("D‘Alessandro"), "D'Alessandro")

    def test_internal_whitespace_collapsed(self):
        self.assertEqual(players.normalize_name("Mark   Gatt"), "Mark Gatt")
        self.assertEqual(players.normalize_name("Mark\tGatt"), "Mark Gatt")
        self.assertEqual(players.normalize_name("Mark\nGatt"), "Mark Gatt")

    def test_leading_trailing_whitespace_stripped(self):
        self.assertEqual(players.normalize_name("  Mark Gatt  "), "Mark Gatt")

    def test_casing_preserved(self):
        # Phase 0 explicit trade-off: case-sensitive (Phase 1 fuzzy match handles this)
        self.assertNotEqual(
            players.normalize_name("Mark Gatt"),
            players.normalize_name("mark gatt"),
        )

    def test_nfkc_composes_decomposed_chars(self):
        # 'é' as decomposed (e + combining acute) should normalize to single codepoint
        decomposed = "Marc" + "é"  # already composed for control
        decomposed_via_combining = "Marc" + "e" + "́"
        self.assertEqual(
            players.normalize_name(decomposed_via_combining),
            players.normalize_name(decomposed),
        )


class TestGetOrCreatePlayer(unittest.TestCase):
    def setUp(self):
        # Apply the schema to an in-memory DB; satisfy FKs with one club + one source_file
        self.conn = db.init_db(":memory:")
        self.conn.execute("INSERT INTO clubs (id, name, slug) VALUES (1, 'VLTC', 'vltc')")
        self.conn.execute(
            "INSERT INTO source_files (id, club_id, original_filename, sha256) "
            "VALUES (1, 1, 'test.xlsx', 'deadbeef')"
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_first_sight_creates_player_and_alias(self):
        pid = players.get_or_create_player(self.conn, "Mark Gatt", 1)
        self.assertIsNotNone(pid)
        self.assertEqual(self._count("players"), 1)
        self.assertEqual(self._count("player_aliases"), 1)

    def test_curly_and_straight_apostrophe_collide_to_one_player(self):
        pid_curly = players.get_or_create_player(self.conn, "D’Alessandro", 1)
        pid_straight = players.get_or_create_player(self.conn, "D'Alessandro", 1)
        self.assertEqual(pid_curly, pid_straight)
        # ...but two distinct alias rows since the raw forms differ
        n = self.conn.execute(
            "SELECT COUNT(*) FROM player_aliases WHERE player_id = ?", (pid_curly,)
        ).fetchone()[0]
        self.assertEqual(n, 2)

    def test_repeated_raw_name_does_not_duplicate_alias(self):
        pid1 = players.get_or_create_player(self.conn, "Mark Gatt", 1)
        pid2 = players.get_or_create_player(self.conn, "Mark Gatt", 1)
        self.assertEqual(pid1, pid2)
        n = self.conn.execute(
            "SELECT COUNT(*) FROM player_aliases WHERE player_id = ?", (pid1,)
        ).fetchone()[0]
        self.assertEqual(n, 1)

    def test_whitespace_variants_collide(self):
        pid1 = players.get_or_create_player(self.conn, "Mark Gatt", 1)
        pid2 = players.get_or_create_player(self.conn, "  Mark   Gatt  ", 1)
        self.assertEqual(pid1, pid2)

    def test_distinct_names_create_distinct_players(self):
        pid1 = players.get_or_create_player(self.conn, "Mark Gatt", 1)
        pid2 = players.get_or_create_player(self.conn, "Mark Smith", 1)
        self.assertNotEqual(pid1, pid2)
        self.assertEqual(self._count("players"), 2)

    def test_casing_distinguishes_in_phase_0(self):
        # Phase 0 explicit trade-off — case-sensitive distinction documented.
        pid1 = players.get_or_create_player(self.conn, "Mark Gatt", 1)
        pid2 = players.get_or_create_player(self.conn, "MARK GATT", 1)
        self.assertNotEqual(pid1, pid2)

    def test_source_file_id_optional(self):
        pid = players.get_or_create_player(self.conn, "Mark Gatt", None)
        self.assertIsNotNone(pid)
        self.assertEqual(self._count("player_aliases"), 1)

    def _count(self, table: str) -> int:
        return self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


if __name__ == "__main__":
    unittest.main()
