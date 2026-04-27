"""Tests for the 4-verdict review workflow (T-P0.5-018).

Covers:
  * `players.unmerge_player` — reverses a merge cleanly using the
    `match_sides` snapshot recorded in `audit_log.before_jsonb`
  * `players.record_defer` + `load_active_defers` — "Don't know" persistence
    with TTL
  * `pending_changes` — JSONL accumulator + threshold logic for the
    auto-reprocess daemon
  * `reprocess._step_apply_aliases` — synchronous step harness

Run from repo root:
    python -m unittest scripts.phase0.test_review_workflow
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import db  # noqa: E402
import pending_changes as pc  # noqa: E402
import players  # noqa: E402


def _conn():
    return db.init_db(":memory:")


def _add_club_and_run(conn):
    club = conn.execute(
        "INSERT INTO clubs (name, slug) VALUES ('Test', 'test')"
    ).lastrowid
    sf = conn.execute(
        "INSERT INTO source_files (club_id, original_filename, sha256) "
        "VALUES (?, ?, ?)", (club, "synth.xlsx", "abc"),
    ).lastrowid
    run = conn.execute(
        "INSERT INTO ingestion_runs (source_file_id, status) VALUES (?, ?)",
        (sf, "completed"),
    ).lastrowid
    return club, run


def _add_match(conn, run, p1, p2, *, played="2026-01-01"):
    """Insert a singles match with p1 on side A and p2 on side B."""
    club_row = conn.execute("SELECT id FROM clubs LIMIT 1").fetchone()
    tour = conn.execute(
        "INSERT INTO tournaments (club_id, name, year, format) "
        "VALUES (?, 'Synth', 2026, 'doubles_division')",
        (club_row[0],),
    ).lastrowid
    mid = conn.execute(
        "INSERT INTO matches (tournament_id, played_on, ingestion_run_id) "
        "VALUES (?, ?, ?)", (tour, played, run),
    ).lastrowid
    for side, p in (("A", p1), ("B", p2)):
        conn.execute(
            "INSERT INTO match_sides (match_id, side, player1_id, won) "
            "VALUES (?, ?, ?, ?)",
            (mid, side, p, 1 if side == "A" else 0),
        )
    return mid


# --- 1. unmerge_player ------------------------------------------------------


class TestUnmergePlayer(unittest.TestCase):
    def test_round_trip_restores_match_sides(self):
        conn = _conn()
        try:
            _, run = _add_club_and_run(conn)
            winner = conn.execute(
                "INSERT INTO players (canonical_name) VALUES ('Winner')"
            ).lastrowid
            loser = conn.execute(
                "INSERT INTO players (canonical_name) VALUES ('Loser')"
            ).lastrowid
            other = conn.execute(
                "INSERT INTO players (canonical_name) VALUES ('Other')"
            ).lastrowid
            mid_loser = _add_match(conn, run, loser, other)
            mid_winner = _add_match(conn, run, winner, other,
                                    played="2026-02-01")
            conn.commit()

            players.merge_player_into(
                conn, loser_id=loser, winner_id=winner, reason="oops",
            )
            conn.commit()

            # After merge: loser's match now points at winner.
            row = conn.execute(
                "SELECT player1_id FROM match_sides WHERE match_id = ? "
                "AND side = 'A'", (mid_loser,),
            ).fetchone()
            self.assertEqual(row[0], winner)

            audit_id = conn.execute(
                "SELECT id FROM audit_log WHERE action = 'player.merged' "
                "AND entity_id = ?", (loser,),
            ).fetchone()[0]

            result = players.unmerge_player(conn, audit_id, reason="test")
            conn.commit()

            self.assertEqual(result["loser_id"], loser)
            self.assertEqual(result["winner_id"], winner)
            # Snapshot present → match_sides_redirected reflects only the
            # loser's original side, not winner's pre-existing one.
            self.assertEqual(result["match_sides_redirected"], 1)
            self.assertFalse(result["legacy"])

            # Loser's match restored.
            row = conn.execute(
                "SELECT player1_id FROM match_sides WHERE match_id = ? "
                "AND side = 'A'", (mid_loser,),
            ).fetchone()
            self.assertEqual(row[0], loser)
            # Winner's own match still on winner.
            row = conn.execute(
                "SELECT player1_id FROM match_sides WHERE match_id = ? "
                "AND side = 'A'", (mid_winner,),
            ).fetchone()
            self.assertEqual(row[0], winner)
            # merged_into_id cleared.
            mi = conn.execute(
                "SELECT merged_into_id FROM players WHERE id = ?", (loser,),
            ).fetchone()[0]
            self.assertIsNone(mi)
        finally:
            conn.close()

    def test_writes_unmerged_audit_entry(self):
        conn = _conn()
        try:
            _, run = _add_club_and_run(conn)
            w = conn.execute(
                "INSERT INTO players (canonical_name) VALUES ('W')"
            ).lastrowid
            l = conn.execute(
                "INSERT INTO players (canonical_name) VALUES ('L')"
            ).lastrowid
            o = conn.execute(
                "INSERT INTO players (canonical_name) VALUES ('O')"
            ).lastrowid
            _add_match(conn, run, l, o)
            players.merge_player_into(conn, loser_id=l, winner_id=w)
            conn.commit()
            audit_id = conn.execute(
                "SELECT id FROM audit_log WHERE action = 'player.merged'"
            ).fetchone()[0]
            players.unmerge_player(conn, audit_id, reason="test")
            conn.commit()

            row = conn.execute(
                "SELECT after_jsonb FROM audit_log "
                "WHERE action = 'player.unmerged'"
            ).fetchone()
            self.assertIsNotNone(row)
            after = json.loads(row[0])
            self.assertIsNone(after["merged_into_id"])
            self.assertEqual(after["reason"], "test")
            self.assertFalse(after["legacy"])
        finally:
            conn.close()

    def test_legacy_audit_without_snapshot_marks_legacy_true(self):
        conn = _conn()
        try:
            _, run = _add_club_and_run(conn)
            w = conn.execute(
                "INSERT INTO players (canonical_name) VALUES ('W')"
            ).lastrowid
            l = conn.execute(
                "INSERT INTO players (canonical_name) VALUES ('L')"
            ).lastrowid
            # Hand-craft an OLD-style merge: redirect manually, write the
            # legacy-shaped audit entry (no `match_sides` field).
            o = conn.execute(
                "INSERT INTO players (canonical_name) VALUES ('O')"
            ).lastrowid
            mid = _add_match(conn, run, l, o)
            conn.execute(
                "UPDATE match_sides SET player1_id = ? WHERE match_id = ? "
                "AND side = 'A'", (w, mid),
            )
            conn.execute(
                "UPDATE players SET merged_into_id = ? WHERE id = ?", (w, l),
            )
            audit_id = conn.execute(
                "INSERT INTO audit_log (action, entity_type, entity_id, "
                "before_jsonb, after_jsonb) VALUES "
                "('player.merged', 'players', ?, ?, ?)",
                (l, json.dumps({"id": l, "canonical_name": "L"}),
                 json.dumps({"merged_into_id": w,
                             "winner_canonical_name": "W"})),
            ).lastrowid
            conn.commit()

            result = players.unmerge_player(conn, audit_id, reason="legacy")
            conn.commit()
            self.assertTrue(result["legacy"])
            self.assertEqual(result["match_sides_redirected"], 0)
            # merged_into_id still cleared
            self.assertIsNone(
                conn.execute(
                    "SELECT merged_into_id FROM players WHERE id = ?", (l,),
                ).fetchone()[0],
            )
        finally:
            conn.close()

    def test_refuses_when_loser_currently_merged_elsewhere(self):
        conn = _conn()
        try:
            _, run = _add_club_and_run(conn)
            w1 = conn.execute(
                "INSERT INTO players (canonical_name) VALUES ('W1')"
            ).lastrowid
            w2 = conn.execute(
                "INSERT INTO players (canonical_name) VALUES ('W2')"
            ).lastrowid
            l = conn.execute(
                "INSERT INTO players (canonical_name) VALUES ('L')"
            ).lastrowid
            o = conn.execute(
                "INSERT INTO players (canonical_name) VALUES ('O')"
            ).lastrowid
            _add_match(conn, run, l, o)
            players.merge_player_into(conn, loser_id=l, winner_id=w1)
            conn.commit()
            audit_id = conn.execute(
                "SELECT id FROM audit_log WHERE action = 'player.merged'"
            ).fetchone()[0]
            # Now manually move l to merge into w2 instead — simulates a
            # later operation taking the loser somewhere new.
            conn.execute(
                "UPDATE players SET merged_into_id = ? WHERE id = ?", (w2, l),
            )
            conn.commit()

            with self.assertRaises(ValueError) as cm:
                players.unmerge_player(conn, audit_id)
            self.assertIn("currently merged into", str(cm.exception))
        finally:
            conn.close()

    def test_unknown_audit_id_raises(self):
        conn = _conn()
        try:
            with self.assertRaises(ValueError):
                players.unmerge_player(conn, 99999)
        finally:
            conn.close()


# --- 2. record_defer / load_active_defers -----------------------------------


class TestDeferRecorder(unittest.TestCase):
    def test_records_pair_with_revisit_after(self):
        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w", encoding="utf-8",
        ) as f:
            json.dump({"pairs": []}, f)
            path = f.name
        try:
            self.assertTrue(players.record_defer(
                path, "Alice", "Bob", days=14, reason="not sure",
            ))
            data = json.loads(Path(path).read_text())
            self.assertEqual(len(data["pairs"]), 1)
            entry = data["pairs"][0]
            self.assertEqual({entry["a"], entry["b"]}, {"Alice", "Bob"})
            self.assertEqual(entry["reason"], "not sure")
            self.assertIn("revisit_after", entry)
        finally:
            Path(path).unlink()

    def test_re_deferring_refreshes_existing_entry(self):
        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w", encoding="utf-8",
        ) as f:
            json.dump({"pairs": []}, f)
            path = f.name
        try:
            players.record_defer(path, "A", "B", days=7)
            data1 = json.loads(Path(path).read_text())
            old_revisit = data1["pairs"][0]["revisit_after"]
            # Re-defer with longer window — should not append a new row.
            players.record_defer(path, "B", "A", days=30)  # order swapped
            data2 = json.loads(Path(path).read_text())
            self.assertEqual(len(data2["pairs"]), 1)
            self.assertGreater(data2["pairs"][0]["revisit_after"], old_revisit)
        finally:
            Path(path).unlink()

    def test_load_active_defers_filters_expired(self):
        # Build a synthetic file with one expired and one active deferral.
        now = datetime.now(timezone.utc)
        expired_ts = (now - timedelta(days=1)).isoformat(timespec="seconds")
        future_ts = (now + timedelta(days=7)).isoformat(timespec="seconds")
        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w", encoding="utf-8",
        ) as f:
            json.dump({"pairs": [
                {"a": "Old1", "b": "Old2", "revisit_after": expired_ts},
                {"a": "New1", "b": "New2", "revisit_after": future_ts},
            ]}, f)
            path = f.name
        try:
            active = players.load_active_defers(path)
            self.assertIn(frozenset({"New1", "New2"}), active)
            self.assertNotIn(frozenset({"Old1", "Old2"}), active)
        finally:
            Path(path).unlink()

    def test_missing_file_returns_empty_set(self):
        self.assertEqual(
            players.load_active_defers("/nonexistent/defer.json"),
            set(),
        )


# --- 3. suggest_fuzzy_matches filters defers --------------------------------


class TestSuggesterFiltersDefers(unittest.TestCase):
    def test_deferred_pair_excluded_from_results(self):
        conn = _conn()
        try:
            _, run = _add_club_and_run(conn)
            # Create two players with a typo-distance name pair so they'd
            # normally surface above the default threshold.
            for name in ("Lillian Baldacchino", "Lillian Badacchino"):
                pid = conn.execute(
                    "INSERT INTO players (canonical_name, gender) "
                    "VALUES (?, 'F')", (name,),
                ).lastrowid
                # Each needs ≥1 active match
                other = conn.execute(
                    "INSERT INTO players (canonical_name) VALUES (?)",
                    (f"Opp for {name}",),
                ).lastrowid
                _add_match(conn, run, pid, other)
            conn.commit()

            # Without defer filter, both surface.
            suggestions = players.suggest_fuzzy_matches(
                conn, threshold=0.78, min_matches=1,
            )
            self.assertGreaterEqual(len(suggestions), 1)

            # Defer the pair → suggester returns nothing.
            deferred = {frozenset({"Lillian Baldacchino", "Lillian Badacchino"})}
            suggestions = players.suggest_fuzzy_matches(
                conn, threshold=0.78, min_matches=1, deferred=deferred,
            )
            for s in suggestions:
                names = {s["a"]["name"], s["b"]["name"]}
                self.assertNotEqual(
                    names, {"Lillian Baldacchino", "Lillian Badacchino"},
                )
        finally:
            conn.close()


# --- 4. pending_changes accumulator -----------------------------------------


class TestPendingChanges(unittest.TestCase):
    def setUp(self):
        # Use a per-test tempfile to avoid touching the real
        # pending_changes.jsonl during testing.
        self._tf = tempfile.NamedTemporaryFile(
            suffix=".jsonl", delete=False, mode="w", encoding="utf-8",
        )
        self._tf.close()
        self.path = self._tf.name
        Path(self.path).unlink()  # start with no file at all

    def tearDown(self):
        Path(self.path).unlink(missing_ok=True)

    def test_record_appends_one_row(self):
        row = pc.record("merge", "A", "B", path=self.path,
                        extra={"reason": "spelling"})
        self.assertEqual(row["verdict"], "merge")
        rows = pc.iter_rows(self.path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["a_name"], "A")
        self.assertEqual(rows[0]["extra"]["reason"], "spelling")

    def test_unknown_verdict_raises(self):
        with self.assertRaises(ValueError):
            pc.record("invalid", "A", "B", path=self.path)

    def test_summary_counts_by_verdict(self):
        for v in ("merge", "merge", "distinct", "defer"):
            pc.record(v, "A", "B", path=self.path)
        s = pc.summary(self.path)
        self.assertEqual(s["count"], 4)
        self.assertEqual(s["by_verdict"], {
            "merge": 2, "distinct": 1, "defer": 1,
        })
        self.assertIsNotNone(s["first_change_ts"])
        self.assertIsNotNone(s["last_change_ts"])

    def test_summary_empty_when_no_rows(self):
        s = pc.summary(self.path)
        self.assertEqual(s["count"], 0)
        self.assertIsNone(s["first_change_ts"])

    def test_archive_renames_file_with_marker(self):
        pc.record("merge", "A", "B", path=self.path)
        archive_path = pc.archive(reason="test reprocess",
                                  path=self.path)
        self.assertIsNotNone(archive_path)
        self.assertFalse(Path(self.path).exists())
        # Archive contains both rows
        archive_rows = pc.iter_rows(archive_path)
        self.assertEqual(len(archive_rows), 2)  # original + archive marker
        markers = [r for r in archive_rows
                   if r.get("verdict") == "_archive_marker"]
        self.assertEqual(len(markers), 1)
        self.assertEqual(markers[0]["reason"], "test reprocess")
        # Cleanup
        Path(archive_path).unlink()

    def test_archive_when_empty_returns_none(self):
        # No file at all
        self.assertIsNone(pc.archive(path=self.path))

    def test_threshold_reached_count(self):
        for _ in range(10):
            pc.record("merge", "A", "B", path=self.path)
        self.assertTrue(
            pc.threshold_reached(max_count=10, max_minutes=1440,
                                 path=self.path),
        )

    def test_threshold_reached_time_with_min_one_change(self):
        # One row with first_change_ts in the past — older than max_minutes.
        old_ts = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(
            timespec="seconds",
        )
        pc.record("merge", "A", "B", path=self.path, ts=old_ts)
        self.assertTrue(
            pc.threshold_reached(max_count=100, max_minutes=30,
                                 path=self.path),
        )

    def test_threshold_not_reached_when_recent_below_count(self):
        pc.record("merge", "A", "B", path=self.path)
        self.assertFalse(
            pc.threshold_reached(max_count=10, max_minutes=120,
                                 path=self.path),
        )


# --- 5. reprocess pipeline --------------------------------------------------


class TestReprocessPipeline(unittest.TestCase):
    def test_module_exposes_expected_steps(self):
        import reprocess
        self.assertTrue(hasattr(reprocess, "run"))
        self.assertTrue(hasattr(reprocess, "_step_apply_aliases"))
        self.assertTrue(hasattr(reprocess, "_step_generate_site"))
        self.assertTrue(hasattr(reprocess, "_step_rate"))
        self.assertTrue(hasattr(reprocess, "_step_deploy"))

    def test_apply_aliases_step_against_empty_db(self):
        # Patch db.init_db to use an in-memory schema so the step doesn't
        # touch the real phase0.sqlite.
        import db, reprocess
        original = db.init_db
        db.init_db = lambda path=":memory:", **kw: original(":memory:", **kw)
        try:
            with tempfile.NamedTemporaryFile(
                suffix=".json", delete=False, mode="w", encoding="utf-8",
            ) as f:
                json.dump({"merges": []}, f)
                aliases_path = f.name
            try:
                result = reprocess._step_apply_aliases(aliases_path)
                self.assertEqual(result["step"], "apply_aliases")
                self.assertEqual(result["merges_applied"], 0)
            finally:
                Path(aliases_path).unlink()
        finally:
            db.init_db = original


# --- 6. review_server integration -------------------------------------------


class TestReviewServerEndpoints(unittest.TestCase):
    """Spin the actual `ReviewHandler` against a `ThreadingHTTPServer` on an
    ephemeral port and hit every endpoint with `urllib.request`. Catches
    handler-level regressions and pulls review_server.py into coverage."""

    @classmethod
    def setUpClass(cls):
        import importlib
        import socket
        import threading
        from http.server import ThreadingHTTPServer

        # Repoint review_server's module-level paths to per-test tempfiles
        # so the smoke run doesn't touch the real repo files.
        cls._tmpdir = tempfile.mkdtemp()
        cls._aliases = Path(cls._tmpdir, "manual_aliases.json")
        cls._aliases.write_text(json.dumps({"merges": []}))
        cls._distinct = Path(cls._tmpdir, "known_distinct.json")
        cls._distinct.write_text(json.dumps({"pairs": []}))
        cls._defer = Path(cls._tmpdir, "defer.json")
        cls._defer.write_text(json.dumps({"pairs": []}))
        cls._pending = Path(cls._tmpdir, "pending_changes.jsonl")

        cls._review_mod = importlib.import_module("review_server")
        cls._review_mod.ALIASES_PATH = cls._aliases
        cls._review_mod.DISTINCT_PATH = cls._distinct
        cls._review_mod.DEFER_PATH = cls._defer
        # Also redirect pending_changes — write to per-test path
        cls._pc_mod = importlib.import_module("pending_changes")
        cls._pc_mod.PENDING_PATH = cls._pending

        # The handler reads from a real DB — point at the project DB if it
        # exists; otherwise skip endpoints that need it.
        repo_root = Path(__file__).resolve().parent.parent.parent
        project_db = repo_root / "phase0.sqlite"
        cls.have_db = project_db.exists()
        if cls.have_db:
            cls._review_mod.DB_PATH = project_db

        # Bind to an ephemeral port so two parallel test runners don't
        # collide.
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            cls.port = s.getsockname()[1]

        cls.server = ThreadingHTTPServer(
            ("127.0.0.1", cls.port), cls._review_mod.ReviewHandler,
        )
        cls.thread = threading.Thread(target=cls.server.serve_forever)
        cls.thread.daemon = True
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        import shutil
        cls.server.shutdown()
        cls.thread.join(timeout=2)
        cls.server.server_close()
        shutil.rmtree(cls._tmpdir, ignore_errors=True)

    def _request(self, method, path, body=None):
        import urllib.request
        url = f"http://127.0.0.1:{self.port}{path}"
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            req = urllib.request.Request(
                url, data=data, method=method,
                headers={"Content-Type": "application/json"},
            )
        else:
            req = urllib.request.Request(url, method=method)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8") or "{}")

    def test_root_html_page(self):
        import urllib.request
        url = f"http://127.0.0.1:{self.port}/"
        with urllib.request.urlopen(url, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            body = resp.read().decode("utf-8")
        self.assertIn("Review queue", body)
        self.assertIn("Reprocess", body)

    def test_pending_changes_endpoint(self):
        status, body = self._request("GET", "/api/pending_changes")
        self.assertEqual(status, 200)
        self.assertIn("count", body)
        self.assertIn("by_verdict", body)

    def test_defer_endpoint_writes_to_defer_json(self):
        status, body = self._request("POST", "/api/defer", {
            "a_name": "Foo", "b_name": "Bar", "days": 5, "reason": "test",
        })
        self.assertEqual(status, 200)
        self.assertTrue(body["deferred"])
        # Defer file now contains the pair
        with open(self._defer, "r") as f:
            data = json.load(f)
        self.assertTrue(any(
            {p["a"], p["b"]} == {"Foo", "Bar"} for p in data["pairs"]
        ))

    def test_distinct_endpoint_validates_input(self):
        status, body = self._request("POST", "/api/distinct", {})
        self.assertEqual(status, 400)
        self.assertIn("required", body["error"])

    def test_same_endpoint_validates_winner_loser_distinct(self):
        status, body = self._request("POST", "/api/same", {
            "winner_name": "X", "loser_name": "X",
        })
        self.assertEqual(status, 400)

    def test_unmerge_unknown_id_returns_409(self):
        status, body = self._request("POST", "/api/unmerge", {
            "audit_id": 99999999,
        })
        self.assertEqual(status, 409)
        self.assertIn("audit", body["error"].lower())

    def test_unknown_path_returns_404(self):
        status, _ = self._request("GET", "/api/no_such_thing")
        self.assertEqual(status, 404)

    def test_recent_merges_endpoint(self):
        if not self.have_db:
            self.skipTest("phase0.sqlite not present")
        status, body = self._request("GET", "/api/recent_merges")
        self.assertEqual(status, 200)
        self.assertIsInstance(body, list)

    def test_same_endpoint_records_to_aliases_json(self):
        # Reset the file so we can assert the new entry cleanly.
        self._aliases.write_text(json.dumps({"merges": []}))
        status, body = self._request("POST", "/api/same", {
            "winner_name": "WinnerX", "loser_name": "LoserX",
            "reason": "test merge",
        })
        self.assertEqual(status, 200)
        self.assertTrue(body["added"])
        with open(self._aliases) as f:
            data = json.load(f)
        self.assertTrue(any(
            e["winner"] == "WinnerX" and "LoserX" in e["losers"]
            for e in data["merges"]
        ))

    def test_distinct_endpoint_records_to_distinct_json(self):
        self._distinct.write_text(json.dumps({"pairs": []}))
        status, body = self._request("POST", "/api/distinct", {
            "a_name": "X", "b_name": "Y",
        })
        self.assertEqual(status, 200)
        with open(self._distinct) as f:
            data = json.load(f)
        self.assertTrue(any(
            {p["a"], p["b"]} == {"X", "Y"} for p in data["pairs"]
        ))

    def test_defer_missing_field_returns_400(self):
        status, _ = self._request("POST", "/api/defer", {"a_name": "X"})
        self.assertEqual(status, 400)

    def test_unmerge_missing_audit_id_returns_400(self):
        status, _ = self._request("POST", "/api/unmerge", {})
        self.assertEqual(status, 400)

    def test_pending_changes_increments_after_verdict(self):
        # Snapshot count, post a defer, expect count + 1.
        _, before = self._request("GET", "/api/pending_changes")
        before_count = before["count"]
        self._request("POST", "/api/defer", {
            "a_name": "Aa", "b_name": "Bb", "days": 1,
        })
        _, after = self._request("GET", "/api/pending_changes")
        self.assertEqual(after["count"], before_count + 1)


# --- 7. CLI subcommand smoke ------------------------------------------------


class TestCliEvalIdentitySubcommand(unittest.TestCase):
    """Drives `cmd_eval_identity` directly to lock its argparse contract."""

    def test_help_exits_zero(self):
        import cli
        with self.assertRaises(SystemExit) as cm:
            cli.main(["eval-identity", "--help"])
        self.assertEqual(cm.exception.code, 0)

    def test_runs_against_temp_synthetic_files(self):
        import cli, db
        # Build minimal synthetic ground-truth files.
        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w", encoding="utf-8",
        ) as f:
            json.dump({"merges": [{"winner": "W", "losers": ["W"]}]}, f)
            aliases_path = f.name
        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w", encoding="utf-8",
        ) as f:
            json.dump({"pairs": []}, f)
            distinct_path = f.name
        # Patch db.init_db to return an in-memory schema instead of touching
        # the project DB.
        original = db.init_db
        db.init_db = lambda path=":memory:", **kw: original(":memory:", **kw)
        import io
        import contextlib
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                rc = cli.main([
                    "eval-identity",
                    "--aliases", aliases_path,
                    "--distinct", distinct_path,
                ])
            self.assertEqual(rc, 0)
            self.assertIn("Identity-eval", buf.getvalue())
        finally:
            db.init_db = original
            Path(aliases_path).unlink(missing_ok=True)
            Path(distinct_path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
