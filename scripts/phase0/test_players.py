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

    def test_merged_player_resolves_to_canonical_id(self):
        # Bug T-P0.5-025: re-ingesting a name whose canonical_name belongs to
        # a merged-out player must return the surviving canonical id, NOT
        # the ghost. Otherwise the rating engine splits the player's history.
        pid_a = players.get_or_create_player(self.conn, "Alice Aaaaaaaa", 1)
        pid_b = players.get_or_create_player(self.conn, "Beatrice Bbbbbbbb", 1)
        self.assertNotEqual(pid_a, pid_b)
        players.merge_player_into(self.conn, loser_id=pid_a, winner_id=pid_b)
        # Now the canonical_name "Alice Aaaaaaaa" belongs to a merged-out row.
        # A re-ingest should resolve the merge chain and return pid_b.
        resolved = players.get_or_create_player(self.conn, "Alice Aaaaaaaa", 1)
        self.assertEqual(resolved, pid_b)
        # And it must not have created a new players row to hide the bug.
        self.assertEqual(self._count("players"), 2)

    def test_multi_hop_merge_chain_resolves_to_terminal_id(self):
        # A → B → C: re-ingesting A's name must return C, not B.
        pid_a = players.get_or_create_player(self.conn, "Alpha Aaaaaa", 1)
        pid_b = players.get_or_create_player(self.conn, "Bravo Bbbbbb", 1)
        pid_c = players.get_or_create_player(self.conn, "Charlie Cccccc", 1)
        players.merge_player_into(self.conn, loser_id=pid_a, winner_id=pid_b)
        players.merge_player_into(self.conn, loser_id=pid_b, winner_id=pid_c)
        resolved = players.get_or_create_player(self.conn, "Alpha Aaaaaa", 1)
        self.assertEqual(resolved, pid_c)

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


class TestIsTypoPair(unittest.TestCase):
    """Gate logic for the typo auto-merger / fuzzy suggester boost.

    These cases are the actual discriminator between "1-char typo of the same
    person" and "two distinct players who share a first name". If either side
    of this gate drifts, the suggester (HIGH/VERY HIGH bucketing) and the
    auto-merger (which fires without human review) will disagree.
    """

    def test_canonical_typos_pass(self):
        cases = [
            ("Borg Reuben", "Borg Ruben"),                  # 1 deletion
            ("Mariska Steenkamer", "Mariska Stennkamer"),    # 1 substitution
            ("Jonathan Martinelli", "Jonathan Maritnelli"),  # transposition
            ("Stephanie Farrugia", "Stephania Farrugia"),    # last-char sub
            ("Karolina Papiernik", "Karolina Paperniek"),    # transposition
            ("Clayton Zammit Cesare", "Calyton Zammit Cesare"),  # 3-token typo
            ("Jin Attard", "Jin Atard"),                     # 9-char min boundary
        ]
        for a, b in cases:
            with self.subTest(a=a, b=b):
                self.assertTrue(players._is_typo_pair(a, b), f"{a!r} vs {b!r}")

    def test_distinct_people_with_similar_names_fail(self):
        # These MUST NOT auto-merge — they're real false positives in the data.
        cases = [
            ("Mike Smith", "Mark Smith"),
            ("John Smith", "Jane Smith"),
            ("Cachia Ivan", "Cachia Sean"),
            ("Christine Schembri", "Christine Scerri"),
            ("Jurgen Farrugia", "Owen Farrugia"),
        ]
        for a, b in cases:
            with self.subTest(a=a, b=b):
                self.assertFalse(players._is_typo_pair(a, b), f"{a!r} vs {b!r}")

    def test_short_names_fail_length_gate(self):
        # Names < 9 chars are too short for ratio-based discrimination.
        self.assertFalse(players._is_typo_pair("Jo Smith", "Jo Smyth"))

    def test_length_diff_gt_one_fails(self):
        # An extra word or 2-char difference is not a 1-char typo.
        self.assertFalse(
            players._is_typo_pair("Mark Gatt", "Mark Anthony Gatt")
        )


class TestTypoAutoMerger(unittest.TestCase):
    """End-to-end behavior of the lopsided-typo auto-merger.

    Sets up a tiny realistic DB (with clubs + tournaments + matches) so the
    merger's club-overlap and match-count gates have real data to read.
    """

    def setUp(self):
        self.conn = db.init_db(":memory:")
        self.conn.execute("INSERT INTO clubs (id, name, slug) VALUES (1, 'VLTC', 'vltc')")
        self.conn.execute("INSERT INTO clubs (id, name, slug) VALUES (2, 'TCK', 'tck')")
        self.conn.execute(
            "INSERT INTO source_files (id, club_id, original_filename, sha256) "
            "VALUES (1, 1, 'fix.xlsx', 'sha1')"
        )
        self.conn.execute(
            "INSERT INTO ingestion_runs (id, source_file_id, status, started_at) "
            "VALUES (1, 1, 'completed', '2025-01-01')"
        )
        self.conn.execute(
            "INSERT INTO tournaments (id, club_id, name, year, format, source_file_id) "
            "VALUES (1, 1, 'VLTC Cup', 2025, 'doubles_division', 1)"
        )
        self.conn.execute(
            "INSERT INTO tournaments (id, club_id, name, year, format) "
            "VALUES (2, 2, 'TCK Cup', 2025, 'doubles_division')"
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _add_player(self, pid, name, gender=None):
        self.conn.execute(
            "INSERT INTO players (id, canonical_name, gender) VALUES (?, ?, ?)",
            (pid, name, gender),
        )

    def _add_match(self, mid, tournament_id, p_a1, p_a2, p_b1, p_b2):
        self.conn.execute(
            "INSERT INTO matches (id, tournament_id, played_on, ingestion_run_id) "
            "VALUES (?, ?, '2025-06-01', 1)", (mid, tournament_id),
        )
        self.conn.execute(
            "INSERT INTO match_sides (match_id, side, player1_id, player2_id, games_won, won) "
            "VALUES (?, 'A', ?, ?, 6, 1)", (mid, p_a1, p_a2),
        )
        self.conn.execute(
            "INSERT INTO match_sides (match_id, side, player1_id, player2_id, games_won, won) "
            "VALUES (?, 'B', ?, ?, 3, 0)", (mid, p_b1, p_b2),
        )

    def test_lopsided_typo_pair_merges(self):
        # Established player (5 matches) + ghost record (1 match), 1-char typo,
        # same gender, shared club. Expected: auto-merge ghost into established.
        self._add_player(1, "Mariska Steenkamer", "F")
        self._add_player(2, "Mariska Stennkamer", "F")  # 1-char typo
        self._add_player(3, "Partner", "F")
        self._add_player(4, "Foe1", "F"); self._add_player(5, "Foe2", "F")
        for mid in range(1, 6):
            self._add_match(mid, 1, 1, 3, 4, 5)
        self._add_match(6, 1, 2, 3, 4, 5)
        self.conn.commit()

        result = players.merge_typo_duplicates(self.conn)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["winner"]["id"], 1)
        self.assertEqual(result[0]["loser"]["id"], 2)
        # Ghost row has merged_into_id set
        merged_into = self.conn.execute(
            "SELECT merged_into_id FROM players WHERE id = 2"
        ).fetchone()[0]
        self.assertEqual(merged_into, 1)

    def test_same_n_pair_does_not_auto_merge(self):
        # Two records with 3 matches each — neither looks like a "ghost".
        # Auto-merger leaves these for human review via suggest-merges.
        self._add_player(1, "Christina Bonnet", "F")
        self._add_player(2, "Christina Bonett", "F")
        self._add_player(3, "Partner", "F")
        self._add_player(4, "Foe1", "F"); self._add_player(5, "Foe2", "F")
        for mid in range(1, 4):
            self._add_match(mid, 1, 1, 3, 4, 5)
        for mid in range(4, 7):
            self._add_match(mid, 1, 2, 3, 4, 5)
        self.conn.commit()

        result = players.merge_typo_duplicates(self.conn)
        self.assertEqual(result, [])

    def test_no_shared_club_does_not_merge(self):
        # Two clubs, established at one, ghost at the other. Same name typo.
        # Cross-club homonym safety net — leaves it for human.
        self._add_player(1, "Andrea Magaldi", "F")
        self._add_player(2, "Andrea Magalgi", "F")
        self._add_player(3, "Partner", "F")
        self._add_player(4, "Foe1", "F"); self._add_player(5, "Foe2", "F")
        for mid in range(1, 6):
            self._add_match(mid, 1, 1, 3, 4, 5)  # club 1
        self._add_match(6, 2, 2, 3, 4, 5)         # club 2
        self.conn.commit()

        result = players.merge_typo_duplicates(self.conn)
        self.assertEqual(result, [])

    def test_different_gender_does_not_merge(self):
        # Maria (F) vs Mario (M) — same surname, 1-char first-name diff,
        # but explicit different gender → leave it alone.
        self._add_player(1, "Maria Abdilla", "F")
        self._add_player(2, "Mario Abdilla", "M")
        self._add_player(3, "Partner", "F")
        self._add_player(4, "Foe1", "F"); self._add_player(5, "Foe2", "F")
        for mid in range(1, 6):
            self._add_match(mid, 1, 1, 3, 4, 5)
        self._add_match(6, 1, 2, 3, 4, 5)
        self.conn.commit()

        result = players.merge_typo_duplicates(self.conn)
        self.assertEqual(result, [])

    def test_dry_run_does_not_modify_db(self):
        self._add_player(1, "Mariska Steenkamer", "F")
        self._add_player(2, "Mariska Stennkamer", "F")
        self._add_player(3, "Partner", "F")
        self._add_player(4, "Foe1", "F"); self._add_player(5, "Foe2", "F")
        for mid in range(1, 6):
            self._add_match(mid, 1, 1, 3, 4, 5)
        self._add_match(6, 1, 2, 3, 4, 5)
        self.conn.commit()

        result = players.merge_typo_duplicates(self.conn, dry_run=True)
        self.assertEqual(len(result), 1)
        self.assertFalse(result[0]["merged"])
        # Loser still independent
        merged_into = self.conn.execute(
            "SELECT merged_into_id FROM players WHERE id = 2"
        ).fetchone()[0]
        self.assertIsNone(merged_into)


class TestKnownDistinctAndRecorders(unittest.TestCase):
    """Persistence helpers for the human-review verdict files.

    These wire into the suggester so a 'different people' verdict actually
    sticks across runs. If load/record drift, the suggester silently stops
    respecting human decisions — a quiet, hard-to-debug failure mode.
    """

    def setUp(self):
        import tempfile
        self.tmpdir = tempfile.TemporaryDirectory()
        self.distinct_path = str(Path(self.tmpdir.name) / "known_distinct.json")
        self.aliases_path = str(Path(self.tmpdir.name) / "manual_aliases.json")

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_load_known_distinct_missing_file_returns_empty(self):
        self.assertEqual(players.load_known_distinct(self.distinct_path), set())

    def test_record_distinct_creates_file_and_reloads(self):
        ok = players.record_distinct(
            self.distinct_path, "Christine Schembri", "Christine Scerri",
            reason="different people"
        )
        self.assertTrue(ok)
        loaded = players.load_known_distinct(self.distinct_path)
        self.assertEqual(loaded, {frozenset({"Christine Schembri", "Christine Scerri"})})

    def test_record_distinct_is_idempotent_unordered(self):
        players.record_distinct(self.distinct_path, "A Smith", "B Jones", reason="x")
        # Same pair, names swapped — should NOT create a duplicate entry
        ok = players.record_distinct(self.distinct_path, "B Jones", "A Smith", reason="y")
        self.assertFalse(ok)
        loaded = players.load_known_distinct(self.distinct_path)
        self.assertEqual(len(loaded), 1)

    def test_record_same_person_creates_alias_entry(self):
        ok = players.record_same_person(
            self.aliases_path, "Pretty Name", "TYPO Name", reason="auto"
        )
        self.assertTrue(ok)
        loaded = players.load_known_distinct  # sanity
        with open(self.aliases_path) as f:
            data = __import__("json").loads(f.read())
        self.assertEqual(data["merges"][0]["winner"], "Pretty Name")
        self.assertEqual(data["merges"][0]["losers"], ["TYPO Name"])

    def test_record_same_person_appends_loser_to_existing_winner(self):
        players.record_same_person(self.aliases_path, "Real", "Fake1", reason="r1")
        players.record_same_person(self.aliases_path, "Real", "Fake2", reason="r2")
        with open(self.aliases_path) as f:
            data = __import__("json").loads(f.read())
        self.assertEqual(len(data["merges"]), 1)
        self.assertEqual(data["merges"][0]["losers"], ["Fake1", "Fake2"])

    def test_record_same_person_is_idempotent(self):
        players.record_same_person(self.aliases_path, "Real", "Fake", reason="r")
        ok = players.record_same_person(self.aliases_path, "Real", "Fake", reason="r")
        self.assertFalse(ok)


class TestSuggesterFiltersKnownDistinct(unittest.TestCase):
    """The suggester must drop pairs in the known-distinct set BEFORE scoring,
    otherwise the human review queue keeps re-surfacing already-decided pairs.
    """

    def setUp(self):
        self.conn = db.init_db(":memory:")
        self.conn.execute("INSERT INTO clubs (id, name, slug) VALUES (1, 'VLTC', 'vltc')")
        self.conn.execute(
            "INSERT INTO source_files (id, club_id, original_filename, sha256) "
            "VALUES (1, 1, 'fix.xlsx', 'sha1')"
        )
        self.conn.execute(
            "INSERT INTO ingestion_runs (id, source_file_id, status, started_at) "
            "VALUES (1, 1, 'completed', '2025-01-01')"
        )
        self.conn.execute(
            "INSERT INTO tournaments (id, club_id, name, year, format, source_file_id) "
            "VALUES (1, 1, 'Cup', 2025, 'doubles_division', 1)"
        )
        # Two near-identical names in the same club to ensure a fuzzy hit
        self.conn.execute(
            "INSERT INTO players (id, canonical_name, gender) VALUES (1, 'Christine Schembri', 'F')"
        )
        self.conn.execute(
            "INSERT INTO players (id, canonical_name, gender) VALUES (2, 'Christine Scerri', 'F')"
        )
        self.conn.execute("INSERT INTO players (id, canonical_name, gender) VALUES (3, 'Partner', 'F')")
        self.conn.execute("INSERT INTO players (id, canonical_name, gender) VALUES (4, 'F1', 'F')")
        self.conn.execute("INSERT INTO players (id, canonical_name, gender) VALUES (5, 'F2', 'F')")
        # Give both players matches so they aren't filtered by min_matches
        for mid in range(1, 4):
            self.conn.execute(
                "INSERT INTO matches (id, tournament_id, played_on, ingestion_run_id) "
                "VALUES (?, 1, '2025-06-01', 1)", (mid,)
            )
            self.conn.execute(
                "INSERT INTO match_sides (match_id, side, player1_id, player2_id, games_won, won) "
                "VALUES (?, 'A', 1, 3, 6, 1)", (mid,)
            )
            self.conn.execute(
                "INSERT INTO match_sides (match_id, side, player1_id, player2_id, games_won, won) "
                "VALUES (?, 'B', 4, 5, 3, 0)", (mid,)
            )
        for mid in range(4, 7):
            self.conn.execute(
                "INSERT INTO matches (id, tournament_id, played_on, ingestion_run_id) "
                "VALUES (?, 1, '2025-06-01', 1)", (mid,)
            )
            self.conn.execute(
                "INSERT INTO match_sides (match_id, side, player1_id, player2_id, games_won, won) "
                "VALUES (?, 'A', 2, 3, 6, 1)", (mid,)
            )
            self.conn.execute(
                "INSERT INTO match_sides (match_id, side, player1_id, player2_id, games_won, won) "
                "VALUES (?, 'B', 4, 5, 3, 0)", (mid,)
            )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_pair_appears_without_filter(self):
        # No known_distinct: the pair should surface (low confidence is fine).
        results = players.suggest_fuzzy_matches(self.conn, threshold=0.80)
        names = {frozenset({s["a"]["name"], s["b"]["name"]}) for s in results}
        self.assertIn(
            frozenset({"Christine Schembri", "Christine Scerri"}), names
        )

    def test_pair_filtered_when_in_known_distinct(self):
        kd = {frozenset({"Christine Schembri", "Christine Scerri"})}
        results = players.suggest_fuzzy_matches(
            self.conn, threshold=0.80, known_distinct=kd
        )
        names = {frozenset({s["a"]["name"], s["b"]["name"]}) for s in results}
        self.assertNotIn(
            frozenset({"Christine Schembri", "Christine Scerri"}), names
        )


if __name__ == "__main__":
    unittest.main()
