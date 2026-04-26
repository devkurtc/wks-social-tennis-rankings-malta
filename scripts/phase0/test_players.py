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


class TestCaseDuplicateMerge(unittest.TestCase):
    """Tests for the case-only duplicate-merge helper (Phase-0-bridge-to-Phase-1)."""

    def setUp(self):
        self.conn = db.init_db(":memory:")
        self.conn.execute("INSERT INTO clubs (id, name, slug) VALUES (1, 'VLTC', 'vltc')")
        self.conn.execute(
            "INSERT INTO source_files (id, club_id, original_filename, sha256) "
            "VALUES (1, 1, 'fixture.xlsx', 'sha')"
        )
        self.conn.execute(
            "INSERT INTO ingestion_runs (id, source_file_id, status, started_at) "
            "VALUES (1, 1, 'completed', '2025-01-01')"
        )
        self.conn.execute(
            "INSERT INTO tournaments (id, club_id, name, year, format, source_file_id) "
            "VALUES (1, 1, 'Fixture', 2025, 'doubles_division', 1)"
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _add_match(self, match_id: int, p1: int, p2: int, p3: int, p4: int):
        self.conn.execute(
            "INSERT INTO matches (id, tournament_id, played_on, ingestion_run_id) "
            "VALUES (?, 1, '2025-06-01', 1)",
            (match_id,),
        )
        self.conn.execute(
            "INSERT INTO match_sides (match_id, side, player1_id, player2_id, games_won, won) "
            "VALUES (?, 'A', ?, ?, 6, 1)",
            (match_id, p1, p2),
        )
        self.conn.execute(
            "INSERT INTO match_sides (match_id, side, player1_id, player2_id, games_won, won) "
            "VALUES (?, 'B', ?, ?, 3, 0)",
            (match_id, p3, p4),
        )

    def test_finds_case_only_duplicate_groups(self):
        # Two players with same name modulo case
        self.conn.execute("INSERT INTO players (id, canonical_name) VALUES (1, 'Kurt Carabott')")
        self.conn.execute("INSERT INTO players (id, canonical_name) VALUES (2, 'KURT CARABOTT')")
        self.conn.execute("INSERT INTO players (id, canonical_name) VALUES (3, 'Different Player')")
        self.conn.commit()
        groups = players.find_case_duplicate_groups(self.conn)
        self.assertEqual(len(groups), 1)
        names_in_group = {entry[1] for entry in groups[0]}
        self.assertEqual(names_in_group, {"Kurt Carabott", "KURT CARABOTT"})

    def test_winner_is_player_with_most_matches(self):
        # Player 1 has 2 matches, player 2 has 1 — player 1 wins
        for pid in (1, 2, 3, 4):
            self.conn.execute("INSERT INTO players (id, canonical_name) VALUES (?, ?)",
                              (pid, ["Kurt Carabott", "KURT CARABOTT", "Foe1", "Foe2"][pid - 1]))
        self._add_match(1, 1, 3, 4, 4)  # Player 1 in match 1
        self._add_match(2, 1, 3, 4, 4)  # Player 1 in match 2
        self._add_match(3, 2, 3, 4, 4)  # Player 2 in match 3
        self.conn.commit()
        groups = players.find_case_duplicate_groups(self.conn)
        # Group ordered by n_matches DESC; first is winner
        self.assertEqual(groups[0][0][1], "Kurt Carabott")  # winner
        self.assertEqual(groups[0][1][1], "KURT CARABOTT")  # loser

    def test_merge_redirects_match_sides(self):
        for pid in (1, 2, 3, 4):
            self.conn.execute("INSERT INTO players (id, canonical_name) VALUES (?, ?)",
                              (pid, ["Kurt Carabott", "KURT CARABOTT", "Foe1", "Foe2"][pid - 1]))
        self._add_match(1, 1, 3, 4, 4)  # Player 1
        self._add_match(2, 2, 3, 4, 4)  # Player 2 (loser)
        self.conn.commit()
        players.merge_player_into(self.conn, loser_id=2, winner_id=1)
        # All match_sides referencing player 2 should now reference player 1
        n_loser_refs = self.conn.execute(
            "SELECT COUNT(*) FROM match_sides WHERE player1_id = 2 OR player2_id = 2"
        ).fetchone()[0]
        self.assertEqual(n_loser_refs, 0)
        n_winner_matches = self.conn.execute(
            "SELECT COUNT(*) FROM match_sides WHERE player1_id = 1 OR player2_id = 1"
        ).fetchone()[0]
        self.assertEqual(n_winner_matches, 2)

    def test_merge_marks_loser_with_merged_into_id(self):
        self.conn.execute("INSERT INTO players (id, canonical_name) VALUES (1, 'Kurt Carabott')")
        self.conn.execute("INSERT INTO players (id, canonical_name) VALUES (2, 'KURT CARABOTT')")
        self.conn.commit()
        players.merge_player_into(self.conn, loser_id=2, winner_id=1)
        row = self.conn.execute("SELECT merged_into_id FROM players WHERE id = 2").fetchone()
        self.assertEqual(row[0], 1)
        # Loser row preserved (not deleted)
        n_rows = self.conn.execute("SELECT COUNT(*) FROM players WHERE id = 2").fetchone()[0]
        self.assertEqual(n_rows, 1)

    def test_merge_writes_audit_log(self):
        self.conn.execute("INSERT INTO players (id, canonical_name) VALUES (1, 'Kurt Carabott')")
        self.conn.execute("INSERT INTO players (id, canonical_name) VALUES (2, 'KURT CARABOTT')")
        self.conn.commit()
        players.merge_player_into(self.conn, loser_id=2, winner_id=1, reason="test")
        row = self.conn.execute(
            "SELECT action, entity_id, before_jsonb, after_jsonb FROM audit_log "
            "WHERE action = 'player.merged'"
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "player.merged")
        self.assertEqual(row[1], 2)  # loser id
        self.assertIn("KURT CARABOTT", row[2])  # before captures loser name
        self.assertIn("Kurt Carabott", row[3])  # after captures winner

    def test_merge_player_into_self_raises(self):
        self.conn.execute("INSERT INTO players (id, canonical_name) VALUES (1, 'A')")
        self.conn.commit()
        with self.assertRaises(ValueError):
            players.merge_player_into(self.conn, loser_id=1, winner_id=1)

    def test_merge_already_merged_is_idempotent(self):
        self.conn.execute("INSERT INTO players (id, canonical_name) VALUES (1, 'Winner')")
        self.conn.execute(
            "INSERT INTO players (id, canonical_name, merged_into_id) VALUES (2, 'AlreadyMerged', 1)"
        )
        self.conn.commit()
        # Second merge call should be a no-op (no exception, no extra audit row)
        players.merge_player_into(self.conn, loser_id=2, winner_id=1)
        n_audit = self.conn.execute(
            "SELECT COUNT(*) FROM audit_log WHERE action = 'player.merged'"
        ).fetchone()[0]
        self.assertEqual(n_audit, 0)  # never logged because was already merged

    def test_merge_case_duplicates_end_to_end(self):
        # Three players: 2 case-duplicates, 1 unique
        self.conn.execute("INSERT INTO players (id, canonical_name) VALUES (1, 'Kurt Carabott')")
        self.conn.execute("INSERT INTO players (id, canonical_name) VALUES (2, 'KURT CARABOTT')")
        self.conn.execute("INSERT INTO players (id, canonical_name) VALUES (3, 'Mark Gatt')")
        self.conn.execute("INSERT INTO players (id, canonical_name) VALUES (4, 'Foe')")
        self._add_match(1, 1, 3, 4, 4)
        self._add_match(2, 2, 3, 4, 4)
        self.conn.commit()

        merged = players.merge_case_duplicates(self.conn)
        self.assertEqual(len(merged), 1)
        winner_name, loser_names = merged[0]
        self.assertEqual(winner_name, "Kurt Carabott")
        self.assertEqual(loser_names, ["KURT CARABOTT"])

        # Re-running finds nothing
        again = players.merge_case_duplicates(self.conn)
        self.assertEqual(again, [])


if __name__ == "__main__":
    unittest.main()
