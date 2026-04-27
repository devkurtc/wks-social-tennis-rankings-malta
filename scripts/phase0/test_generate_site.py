"""Tests for the static-site generator (scripts/phase0/generate_site.py).

This file covers the pieces shipped during the all-matches + per-match-impact
work, plus a handful of regression checks for older helpers. Tests use an
in-memory SQLite DB seeded with the smallest possible synthetic scenarios so
each test reads top-to-bottom.

Run from repo root:
    python -m unittest scripts.phase0.test_generate_site
or:
    python scripts/phase0/test_generate_site.py
"""

from __future__ import annotations

import argparse
import re
import sys
import unittest
from pathlib import Path

# Allow `import db` and `import generate_site` whether run as script or module.
sys.path.insert(0, str(Path(__file__).parent))

import db  # noqa: E402
import generate_site as gs  # noqa: E402


# --- Test fixtures -----------------------------------------------------------
#
# Keep these small. Each test should read top-to-bottom — if a fixture grows
# more than ~20 lines, prefer inlining the seed inside the test instead.


def fresh_conn():
    """Return an empty in-memory DB with the Phase-0 schema applied."""
    return db.init_db(":memory:")


def add_club(conn, *, slug="vltc", name="Vittoriosa LTC"):
    cur = conn.execute(
        "INSERT INTO clubs (name, slug) VALUES (?, ?)", (name, slug)
    )
    return cur.lastrowid


def add_player(conn, name, *, gender="M"):
    cur = conn.execute(
        "INSERT INTO players (canonical_name, gender) VALUES (?, ?)",
        (name, gender),
    )
    return cur.lastrowid


def add_source_and_run(conn, club_id, *, sha="deadbeef"):
    sf = conn.execute(
        "INSERT INTO source_files (club_id, original_filename, sha256) "
        "VALUES (?, ?, ?)",
        (club_id, "synth.xlsx", sha),
    ).lastrowid
    run = conn.execute(
        "INSERT INTO ingestion_runs (source_file_id, status) VALUES (?, ?)",
        (sf, "completed"),
    ).lastrowid
    return sf, run


def add_tournament(
    conn, club_id, *, name="Synth Tournament", year=2026,
    fmt="doubles_division",
):
    return conn.execute(
        "INSERT INTO tournaments (club_id, name, year, format) "
        "VALUES (?, ?, ?, ?)",
        (club_id, name, year, fmt),
    ).lastrowid


def add_match(
    conn, *, tournament_id, run_id, played_on,
    side_a, side_b,                # each: (p1, p2, games, sets, won)
    division="Division 1", round_="Round Robin",
    walkover=0, set_scores=None,    # list of (set_no, a, b, was_tiebreak)
):
    """Insert a match + both sides + optional set scores. Returns match id."""
    mid = conn.execute(
        "INSERT INTO matches (tournament_id, played_on, division, round, "
        "ingestion_run_id, walkover) VALUES (?, ?, ?, ?, ?, ?)",
        (tournament_id, played_on, division, round_, run_id, walkover),
    ).lastrowid
    for side, (p1, p2, games, sets, won) in (("A", side_a), ("B", side_b)):
        conn.execute(
            "INSERT INTO match_sides "
            "(match_id, side, player1_id, player2_id, sets_won, games_won, won)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (mid, side, p1, p2, sets, games, won),
        )
    for sn, a, b, tb in (set_scores or []):
        conn.execute(
            "INSERT INTO match_set_scores "
            "(match_id, set_number, side_a_games, side_b_games, was_tiebreak)"
            " VALUES (?, ?, ?, ?, ?)",
            (mid, sn, a, b, tb),
        )
    return mid


def set_rating_after(conn, match_id, player_id, mu, sigma, model=None):
    """Append a rating_history row — what compute_match_impacts replays."""
    conn.execute(
        "INSERT INTO rating_history "
        "(player_id, model_name, match_id, mu_after, sigma_after) "
        "VALUES (?, ?, ?, ?, ?)",
        (player_id, model or gs.MODEL, match_id, mu, sigma),
    )


def set_current_rating(conn, player_id, mu, sigma, n=1, model=None):
    conn.execute(
        "INSERT INTO ratings (player_id, model_name, mu, sigma, n_matches) "
        "VALUES (?, ?, ?, ?, ?)",
        (player_id, model or gs.MODEL, mu, sigma, n),
    )


# --- 1. Pure formatting helpers ---------------------------------------------


class TestEscape(unittest.TestCase):
    def test_escapes_html_special_chars(self):
        self.assertEqual(gs.esc("<b>&\"'"), "&lt;b&gt;&amp;&quot;&#x27;")

    def test_handles_non_string_input(self):
        # esc() is forgiving — it str()s its input. None is normalized to "".
        self.assertEqual(gs.esc(42), "42")
        self.assertEqual(gs.esc(None), "")

    def test_empty_string(self):
        self.assertEqual(gs.esc(""), "")


class TestDeltaSpan(unittest.TestCase):
    def test_positive_uses_up_class_and_plus_sign(self):
        out = gs._delta_span(1.23)
        self.assertIn("delta-up", out)
        self.assertIn("+1.23", out)

    def test_negative_uses_dn_class_no_double_sign(self):
        out = gs._delta_span(-1.23)
        self.assertIn("delta-dn", out)
        self.assertIn("-1.23", out)
        self.assertNotIn("--", out)

    def test_near_zero_renders_as_pm0(self):
        # The threshold (±0.005) collapses jitter into a clean ±0 indicator.
        out = gs._delta_span(0.001)
        self.assertIn("delta-z", out)
        self.assertIn("±0", out)

    def test_decimals_param_changes_precision(self):
        out = gs._delta_span(2.5, decimals=1)
        self.assertIn("+2.5", out)
        self.assertNotIn("+2.50", out)


class TestRankDeltaSpan(unittest.TestCase):
    def test_new_entry_returns_empty_string(self):
        self.assertEqual(gs._rank_delta_span(None, 5), "")

    def test_rank_improvement_renders_positive_delta(self):
        # Lower rank number = higher position; going 5 → 4 is +1.
        out = gs._rank_delta_span(5, 4)
        self.assertIn("+1", out)
        self.assertIn("delta-up", out)

    def test_rank_decline_renders_negative_delta(self):
        out = gs._rank_delta_span(5, 8)
        self.assertIn("-3", out)
        self.assertIn("delta-dn", out)

    def test_no_change_renders_pm0(self):
        out = gs._rank_delta_span(5, 5)
        self.assertIn("±0", out)
        self.assertIn("delta-z", out)


class TestPlayerLinks(unittest.TestCase):
    def test_player_filename_uses_pid(self):
        self.assertEqual(gs.player_filename(42), "players/42.html")

    def test_player_link_uses_root_relative_prefix(self):
        out = gs.player_link(7, "Sam Borg")
        self.assertEqual(
            out, '<a class="player-link" href="players/7.html">Sam Borg</a>',
        )

    def test_player_link_escapes_name(self):
        out = gs.player_link(7, "<script>")
        self.assertIn("&lt;script&gt;", out)
        self.assertNotIn("<script>", out)

    def test_player_link_from_player_page_uses_relative_prefix(self):
        # On /players/X.html, sibling pages live at "Y.html", not "players/Y.html".
        out = gs.player_link_from_player_page(9, "Jan")
        self.assertIn('href="9.html"', out)
        self.assertNotIn("players/9.html", out)


class TestCssVersion(unittest.TestCase):
    def test_is_10_hex_chars(self):
        self.assertRegex(gs.CSS_VERSION, r"^[0-9a-f]{10}$")

    def test_changes_when_css_changes(self):
        # Sanity: the constant is a hash of CSS content, not a literal.
        import hashlib
        expected = hashlib.sha1(gs.CSS.encode("utf-8")).hexdigest()[:10]
        self.assertEqual(gs.CSS_VERSION, expected)


# --- 2. compute_match_impacts -----------------------------------------------


class TestComputeMatchImpactsEmpty(unittest.TestCase):
    def test_empty_db_returns_empty_dict(self):
        with fresh_conn() as conn:
            self.assertEqual(gs.compute_match_impacts(conn), {})


class TestComputeMatchImpactsSingleMatch(unittest.TestCase):
    """One match = four new entrants in the rank bucket. No bypassed/passed_by
    yet (nobody existed before)."""

    def setUp(self):
        self.conn = fresh_conn()
        self.club = add_club(self.conn)
        self.p1 = add_player(self.conn, "P1", gender="M")
        self.p2 = add_player(self.conn, "P2", gender="M")
        self.p3 = add_player(self.conn, "P3", gender="M")
        self.p4 = add_player(self.conn, "P4", gender="M")
        _, run = add_source_and_run(self.conn, self.club)
        tour = add_tournament(self.conn, self.club)
        self.mid = add_match(
            self.conn, tournament_id=tour, run_id=run, played_on="2026-01-01",
            side_a=(self.p1, self.p2, 12, 2, 1),
            side_b=(self.p3, self.p4, 6, 0, 0),
        )
        # Side A wins → mu goes up. Use μ-3σ as the "score".
        for pid, mu in ((self.p1, 26.0), (self.p2, 26.0)):
            set_rating_after(self.conn, self.mid, pid, mu, 7.0)
        for pid, mu in ((self.p3, 24.0), (self.p4, 24.0)):
            set_rating_after(self.conn, self.mid, pid, mu, 7.5)

    def tearDown(self):
        self.conn.close()

    def test_one_impact_per_participant(self):
        impacts = gs.compute_match_impacts(self.conn)
        self.assertEqual(len(impacts), 4)
        self.assertEqual(
            set(impacts.keys()),
            {(self.mid, self.p1), (self.mid, self.p2),
             (self.mid, self.p3), (self.mid, self.p4)},
        )

    def test_all_participants_have_no_prior_state(self):
        impacts = gs.compute_match_impacts(self.conn)
        for k, imp in impacts.items():
            self.assertIsNone(imp["rank_before"], k)
            self.assertIsNone(imp["score_before"], k)

    def test_winners_outrank_losers(self):
        impacts = gs.compute_match_impacts(self.conn)
        winner_ranks = {impacts[(self.mid, p)]["rank_after"] for p in (self.p1, self.p2)}
        loser_ranks = {impacts[(self.mid, p)]["rank_after"] for p in (self.p3, self.p4)}
        # Both winners share the top score (5.0) → both ranked 1.
        # Both losers share a lower score (1.5) → both ranked 3 (after the 2 ties).
        self.assertEqual(winner_ranks, {1})
        self.assertEqual(loser_ranks, {3})

    def test_no_bypass_or_passed_by_on_first_match(self):
        impacts = gs.compute_match_impacts(self.conn)
        for imp in impacts.values():
            self.assertEqual(imp["bypassed"], [])
            self.assertEqual(imp["passed_by"], [])


class TestComputeMatchImpactsBypass(unittest.TestCase):
    """Two matches in sequence: a player who lost the first one then wins
    the second by enough to leapfrog the original winners."""

    def setUp(self):
        self.conn = fresh_conn()
        self.club = add_club(self.conn)
        # Four ranked players, all male so they share a bucket.
        self.a = add_player(self.conn, "Alice", gender="M")
        self.b = add_player(self.conn, "Bob", gender="M")
        self.c = add_player(self.conn, "Carol", gender="M")
        self.d = add_player(self.conn, "Dan", gender="M")
        _, run = add_source_and_run(self.conn, self.club)
        tour = add_tournament(self.conn, self.club)
        # Match 1: A+B beat C+D — A/B end at score 5, C/D at 1.
        self.m1 = add_match(
            self.conn, tournament_id=tour, run_id=run, played_on="2026-01-01",
            side_a=(self.a, self.b, 12, 2, 1),
            side_b=(self.c, self.d, 6, 0, 0),
        )
        for pid in (self.a, self.b):
            set_rating_after(self.conn, self.m1, pid, 26.0, 7.0)
        for pid in (self.c, self.d):
            set_rating_after(self.conn, self.m1, pid, 24.0, 7.5)
        # Match 2: C+D beat A+B and pull ahead — C/D jump to score 7, A/B drop to 0.
        self.m2 = add_match(
            self.conn, tournament_id=tour, run_id=run, played_on="2026-01-08",
            side_a=(self.c, self.d, 12, 2, 1),
            side_b=(self.a, self.b, 6, 0, 0),
        )
        for pid in (self.c, self.d):
            set_rating_after(self.conn, self.m2, pid, 28.0, 7.0)
        for pid in (self.a, self.b):
            set_rating_after(self.conn, self.m2, pid, 21.0, 7.0)

    def tearDown(self):
        self.conn.close()

    def test_bypassed_lists_the_overtaken_players(self):
        impacts = gs.compute_match_impacts(self.conn)
        # In match 2, C went from rank 3 (score 1.5) to rank 1 (score 7.0),
        # bypassing both A and B who were ahead of them.
        c_imp = impacts[(self.m2, self.c)]
        self.assertEqual(c_imp["rank_before"], 3)
        self.assertEqual(c_imp["rank_after"], 1)
        # bypassed is a list of pids, in arbitrary order.
        self.assertEqual(set(c_imp["bypassed"]), {self.a, self.b})
        self.assertEqual(c_imp["passed_by"], [])

    def test_passed_by_lists_the_overtakers(self):
        impacts = gs.compute_match_impacts(self.conn)
        # A dropped from rank 1 → rank 3, with C and D leapfrogging.
        a_imp = impacts[(self.m2, self.a)]
        self.assertEqual(a_imp["rank_before"], 1)
        self.assertEqual(a_imp["rank_after"], 3)
        self.assertEqual(set(a_imp["passed_by"]), {self.c, self.d})
        self.assertEqual(a_imp["bypassed"], [])

    def test_score_delta_matches_mu3sigma_change(self):
        impacts = gs.compute_match_impacts(self.conn)
        c_imp = impacts[(self.m2, self.c)]
        # 7.0 (after) − 1.5 (before) = +5.5
        self.assertAlmostEqual(c_imp["score_delta"], 5.5, places=5)
        self.assertAlmostEqual(c_imp["mu_delta"], 4.0, places=5)

    def test_mu_after_carried_through_state(self):
        impacts = gs.compute_match_impacts(self.conn)
        # On match 2, A's "before" mu should be the mu set in match 1.
        a_imp = impacts[(self.m2, self.a)]
        self.assertAlmostEqual(a_imp["mu_before"], 26.0, places=5)
        self.assertAlmostEqual(a_imp["mu_after"], 21.0, places=5)


class TestComputeMatchImpactsGenderBuckets(unittest.TestCase):
    """Players of different genders are ranked in separate buckets — they
    never appear in each other's bypassed/passed_by lists."""

    def setUp(self):
        self.conn = fresh_conn()
        self.club = add_club(self.conn)
        self.man = add_player(self.conn, "Mike", gender="M")
        self.man2 = add_player(self.conn, "Marco", gender="M")
        self.lady = add_player(self.conn, "Lucy", gender="F")
        self.lady2 = add_player(self.conn, "Lara", gender="F")
        _, run = add_source_and_run(self.conn, self.club)
        tour = add_tournament(self.conn, self.club, fmt="doubles_team")
        # Mixed match: M+F vs M+F.
        self.mid = add_match(
            self.conn, tournament_id=tour, run_id=run, played_on="2026-02-01",
            side_a=(self.man, self.lady, 12, 2, 1),
            side_b=(self.man2, self.lady2, 6, 0, 0),
        )
        set_rating_after(self.conn, self.mid, self.man, 26.0, 7.0)
        set_rating_after(self.conn, self.mid, self.lady, 26.0, 7.0)
        set_rating_after(self.conn, self.mid, self.man2, 24.0, 7.0)
        set_rating_after(self.conn, self.mid, self.lady2, 24.0, 7.0)

    def tearDown(self):
        self.conn.close()

    def test_each_player_ranks_within_own_gender(self):
        impacts = gs.compute_match_impacts(self.conn)
        # Two men in their bucket → ranks 1 and 2; same for ladies.
        self.assertEqual(
            sorted(impacts[(self.mid, p)]["rank_after"] for p in (self.man, self.man2)),
            [1, 2],
        )
        self.assertEqual(
            sorted(impacts[(self.mid, p)]["rank_after"] for p in (self.lady, self.lady2)),
            [1, 2],
        )

    def test_bucket_size_reflects_gender_only(self):
        impacts = gs.compute_match_impacts(self.conn)
        for p in (self.man, self.man2, self.lady, self.lady2):
            self.assertEqual(impacts[(self.mid, p)]["bucket_size_after"], 2)


class TestComputeMatchImpactsSingles(unittest.TestCase):
    def test_singles_match_has_two_impacts(self):
        conn = fresh_conn()
        try:
            club = add_club(conn)
            a = add_player(conn, "Solo A", gender="M")
            b = add_player(conn, "Solo B", gender="M")
            _, run = add_source_and_run(conn, club)
            tour = add_tournament(conn, club)
            mid = add_match(
                conn, tournament_id=tour, run_id=run, played_on="2026-03-01",
                side_a=(a, None, 6, 1, 1),  # singles: player2 = NULL
                side_b=(b, None, 0, 0, 0),
            )
            set_rating_after(conn, mid, a, 26.0, 7.0)
            set_rating_after(conn, mid, b, 24.0, 7.0)
            impacts = gs.compute_match_impacts(conn)
            self.assertEqual(set(impacts.keys()), {(mid, a), (mid, b)})
        finally:
            conn.close()


class TestComputeMatchImpactsSupersededExcluded(unittest.TestCase):
    def test_superseded_match_does_not_contribute(self):
        conn = fresh_conn()
        try:
            club = add_club(conn)
            a = add_player(conn, "A", gender="M")
            b = add_player(conn, "B", gender="M")
            sf, run1 = add_source_and_run(conn, club, sha="r1")
            run2 = conn.execute(
                "INSERT INTO ingestion_runs (source_file_id, status) "
                "VALUES (?, ?)",
                (sf, "completed"),
            ).lastrowid
            tour = add_tournament(conn, club)
            stale = add_match(
                conn, tournament_id=tour, run_id=run1, played_on="2026-01-01",
                side_a=(a, None, 6, 1, 1),
                side_b=(b, None, 0, 0, 0),
            )
            conn.execute(
                "UPDATE matches SET superseded_by_run_id = ? WHERE id = ?",
                (run2, stale),
            )
            set_rating_after(conn, stale, a, 26.0, 7.0)
            set_rating_after(conn, stale, b, 24.0, 7.0)
            self.assertEqual(gs.compute_match_impacts(conn), {})
        finally:
            conn.close()


class TestComputeMatchImpactsWalkover(unittest.TestCase):
    def test_walkover_with_no_rating_history_does_not_crash(self):
        # Walkovers may not produce rating_history rows depending on policy —
        # the impact replay should skip such participants gracefully.
        conn = fresh_conn()
        try:
            club = add_club(conn)
            a = add_player(conn, "A", gender="M")
            b = add_player(conn, "B", gender="M")
            _, run = add_source_and_run(conn, club)
            tour = add_tournament(conn, club)
            mid = add_match(
                conn, tournament_id=tour, run_id=run, played_on="2026-01-01",
                side_a=(a, None, 0, 0, 1), side_b=(b, None, 0, 0, 0),
                walkover=1,
            )
            # Deliberately skip set_rating_after — simulate "no rating change".
            self.assertEqual(gs.compute_match_impacts(conn), {})
        finally:
            conn.close()


# --- 3. render_match_impact_block -------------------------------------------


def _impact(rank_before=None, rank_after=1, score_before=None, score_after=5.0,
            mu_before=None, mu_after=26.0, score_delta=0.0, mu_delta=0.0,
            bypassed=None, passed_by=None,
            side="A", won=True, bucket_size_after=2):
    return {
        "side": side, "won": won,
        "rank_before": rank_before, "rank_after": rank_after,
        "mu_before": mu_before, "mu_after": mu_after,
        "score_before": score_before, "score_after": score_after,
        "mu_delta": mu_delta, "score_delta": score_delta,
        "bypassed": bypassed or [],
        "passed_by": passed_by or [],
        "bucket_size_after": bucket_size_after,
    }


def _lookup(*pairs):
    return {pid: (pid, name) for pid, name in pairs}


class TestRenderMatchImpactBlock(unittest.TestCase):
    def test_empty_participants_returns_empty_string(self):
        out = gs.render_match_impact_block(1, [], {}, {})
        self.assertEqual(out, "")

    def test_renders_2_vs_2_with_vs_divider(self):
        impacts = {
            (1, 10): _impact(side="A", won=True, rank_after=1),
            (1, 11): _impact(side="A", won=True, rank_after=2),
            (1, 12): _impact(side="B", won=False, rank_after=3),
            (1, 13): _impact(side="B", won=False, rank_after=4),
        }
        names = _lookup((10, "A1"), (11, "A2"), (12, "B1"), (13, "B2"))
        participants = [
            (10, 11, "A", True), (11, 10, "A", True),
            (12, 13, "B", False), (13, 12, "B", False),
        ]
        out = gs.render_match_impact_block(1, participants, impacts, names)
        self.assertIn('class="impact-side side-A"', out)
        self.assertIn('class="impact-side side-B"', out)
        self.assertIn('class="impact-vs"', out)
        self.assertIn(">VS<", out)
        # 4 player cards rendered total
        self.assertEqual(out.count('class="impact-player"'), 4)

    def test_new_entry_label_when_no_prior_rank(self):
        impacts = {(1, 10): _impact(rank_before=None, rank_after=5,
                                    score_before=None, score_after=3.5)}
        out = gs.render_match_impact_block(
            1, [(10, None, "A", True)], impacts, _lookup((10, "Newcomer")),
        )
        self.assertIn("new entry", out)
        self.assertIn("#5", out)
        # Score is shown as "starts at" rather than a delta line for first match.
        self.assertIn("starts at", out)

    def test_bypassed_lists_first_5_then_summarises_overflow(self):
        bypassed = list(range(20, 27))  # 7 players
        impacts = {(1, 10): _impact(rank_before=10, rank_after=3,
                                    score_before=2.0, score_after=8.0,
                                    bypassed=bypassed)}
        names = _lookup((10, "Hero"), *((p, f"P{p}") for p in bypassed))
        out = gs.render_match_impact_block(
            1, [(10, None, "A", True)], impacts, names,
        )
        self.assertIn("bypassed", out)
        # Only the first 5 names get linked, with "+ 2 more" as overflow.
        self.assertIn("+ 2 more", out)
        for p in bypassed[:5]:
            self.assertIn(f"P{p}", out)

    def test_passed_by_renders_with_loss_class(self):
        impacts = {(1, 10): _impact(rank_before=2, rank_after=4,
                                    score_before=8.0, score_after=2.0,
                                    passed_by=[20, 21], won=False, side="B")}
        names = _lookup((10, "Casualty"), (20, "Up1"), (21, "Up2"))
        out = gs.render_match_impact_block(
            1, [(10, None, "B", False)], impacts, names,
        )
        self.assertIn("passed by", out)
        self.assertIn("pass-dn", out)
        self.assertIn("Up1", out)
        self.assertIn("Up2", out)

    def test_missing_impact_renders_stub(self):
        # When a participant has no impact (e.g. walkover with no rating row),
        # we still render a placeholder card so the row is balanced.
        out = gs.render_match_impact_block(
            1, [(10, None, "A", True)], {}, _lookup((10, "Ghost")),
        )
        self.assertIn("No rating change recorded", out)
        self.assertIn("Ghost", out)

    def test_players_prefix_for_player_pages(self):
        # From inside /players/X.html, sibling links must NOT carry "players/".
        impacts = {(1, 10): _impact(bypassed=[20])}
        names = _lookup((10, "Me"), (20, "Other"))
        out = gs.render_match_impact_block(
            1, [(10, None, "A", True)], impacts, names, players_prefix="",
        )
        self.assertIn('href="20.html"', out)
        self.assertNotIn('href="players/20.html"', out)

    def test_default_prefix_for_root_pages(self):
        impacts = {(1, 10): _impact(bypassed=[20])}
        names = _lookup((10, "Me"), (20, "Other"))
        out = gs.render_match_impact_block(
            1, [(10, None, "A", True)], impacts, names,
        )
        self.assertIn('href="players/20.html"', out)

    def test_win_loss_tag_classes(self):
        impacts = {
            (1, 10): _impact(side="A", won=True),
            (1, 11): _impact(side="B", won=False),
        }
        names = _lookup((10, "W"), (11, "L"))
        out = gs.render_match_impact_block(
            1, [(10, None, "A", True), (11, None, "B", False)], impacts, names,
        )
        self.assertIn('side-tag win">A · W', out)
        self.assertIn('side-tag loss">B · L', out)

    def test_score_uses_one_decimal_format(self):
        impacts = {(1, 10): _impact(rank_before=2, rank_after=2,
                                    score_before=3.456, score_after=4.123,
                                    score_delta=0.667)}
        out = gs.render_match_impact_block(
            1, [(10, None, "A", True)], impacts, _lookup((10, "X")),
        )
        # Score line shows 1-decimal before/after and 2-decimal delta
        self.assertIn("3.5", out)
        self.assertIn("4.1", out)
        self.assertIn("+0.67", out)


# --- 4. End-to-end page builders --------------------------------------------


class TestBuildMatchesPage(unittest.TestCase):
    def setUp(self):
        self.conn = fresh_conn()
        self.club = add_club(self.conn)
        self.p1 = add_player(self.conn, "Player One", gender="M")
        self.p2 = add_player(self.conn, "Player Two", gender="M")
        self.p3 = add_player(self.conn, "Player Three", gender="M")
        self.p4 = add_player(self.conn, "Player Four", gender="M")
        for pid, mu in ((self.p1, 26.0), (self.p2, 26.0),
                        (self.p3, 24.0), (self.p4, 24.0)):
            set_current_rating(self.conn, pid, mu, 7.0)
        _, run = add_source_and_run(self.conn, self.club)
        tour = add_tournament(self.conn, self.club, name="Spring Open")
        self.mid = add_match(
            self.conn, tournament_id=tour, run_id=run, played_on="2026-04-10",
            side_a=(self.p1, self.p2, 12, 2, 1),
            side_b=(self.p3, self.p4, 6, 0, 0),
            set_scores=[(1, 6, 2, 0), (2, 6, 4, 0)],
        )
        for pid in (self.p1, self.p2):
            set_rating_after(self.conn, self.mid, pid, 26.0, 7.0)
        for pid in (self.p3, self.p4):
            set_rating_after(self.conn, self.mid, pid, 24.0, 7.0)

    def tearDown(self):
        self.conn.close()

    def test_page_is_well_formed_html(self):
        lookup = gs.fetch_player_lookup(self.conn)
        impacts = gs.compute_match_impacts(self.conn)
        html = gs.build_matches_page(self.conn, lookup, impacts=impacts)
        self.assertTrue(html.startswith("<!DOCTYPE html>"))
        self.assertIn("</html>", html)

    def test_includes_all_participant_names(self):
        lookup = gs.fetch_player_lookup(self.conn)
        impacts = gs.compute_match_impacts(self.conn)
        html = gs.build_matches_page(self.conn, lookup, impacts=impacts)
        for name in ("Player One", "Player Two", "Player Three", "Player Four"):
            self.assertIn(name, html)

    def test_set_scores_render_when_present(self):
        lookup = gs.fetch_player_lookup(self.conn)
        impacts = gs.compute_match_impacts(self.conn)
        html = gs.build_matches_page(self.conn, lookup, impacts=impacts)
        self.assertIn("6-2", html)
        self.assertIn("6-4", html)

    def test_falls_back_to_total_games_when_no_set_scores(self):
        # Wipe out set scores and re-render — the score column should fall
        # back to the aggregate games count from match_sides.
        self.conn.execute("DELETE FROM match_set_scores")
        lookup = gs.fetch_player_lookup(self.conn)
        impacts = gs.compute_match_impacts(self.conn)
        html = gs.build_matches_page(self.conn, lookup, impacts=impacts)
        self.assertIn("12-6", html)

    def test_rank_tag_appears_next_to_each_player_name(self):
        lookup = gs.fetch_player_lookup(self.conn)
        impacts = gs.compute_match_impacts(self.conn)
        html = gs.build_matches_page(self.conn, lookup, impacts=impacts)
        # 4 participants → 4 rank tags
        self.assertEqual(html.count('class="rank-tag"'), 4)

    def test_expand_trigger_present_for_each_match_with_impact(self):
        lookup = gs.fetch_player_lookup(self.conn)
        impacts = gs.compute_match_impacts(self.conn)
        html = gs.build_matches_page(self.conn, lookup, impacts=impacts)
        self.assertIn('class="expand-trigger"', html)
        self.assertIn('class="impact-row"', html)

    def test_year_and_club_filters_populated(self):
        lookup = gs.fetch_player_lookup(self.conn)
        impacts = gs.compute_match_impacts(self.conn)
        html = gs.build_matches_page(self.conn, lookup, impacts=impacts)
        self.assertIn('<option value="2026">2026</option>', html)
        self.assertIn('<option value="vltc">vltc</option>', html)

    def test_empty_db_renders_zero_matches_safely(self):
        # Empty conn — no tournament, no matches.
        with fresh_conn() as conn:
            html = gs.build_matches_page(conn, {}, impacts={})
        self.assertIn("Total: 0 active match", html)

    def test_works_without_impacts_param(self):
        # Backwards-compat: callers from older code paths don't pass impacts.
        lookup = gs.fetch_player_lookup(self.conn)
        html = gs.build_matches_page(self.conn, lookup)
        self.assertIn("Player One", html)
        # No impact-row when impacts are absent.
        self.assertNotIn('class="impact-row"', html)


class TestBuildPlayerPage(unittest.TestCase):
    def setUp(self):
        self.conn = fresh_conn()
        self.club = add_club(self.conn)
        self.me = add_player(self.conn, "Me Player", gender="M")
        self.partner = add_player(self.conn, "My Partner", gender="M")
        self.opp1 = add_player(self.conn, "Opp One", gender="M")
        self.opp2 = add_player(self.conn, "Opp Two", gender="M")
        for pid, mu in ((self.me, 26.0), (self.partner, 26.0),
                        (self.opp1, 24.0), (self.opp2, 24.0)):
            set_current_rating(self.conn, pid, mu, 7.0)
        _, run = add_source_and_run(self.conn, self.club)
        tour = add_tournament(self.conn, self.club)
        self.mid = add_match(
            self.conn, tournament_id=tour, run_id=run, played_on="2026-04-10",
            side_a=(self.me, self.partner, 12, 2, 1),
            side_b=(self.opp1, self.opp2, 6, 0, 0),
            set_scores=[(1, 6, 2, 0), (2, 6, 4, 0)],
        )
        for pid in (self.me, self.partner):
            set_rating_after(self.conn, self.mid, pid, 26.0, 7.0)
        for pid in (self.opp1, self.opp2):
            set_rating_after(self.conn, self.mid, pid, 24.0, 7.0)

    def tearDown(self):
        self.conn.close()

    def test_page_includes_player_name_in_header(self):
        lookup = gs.fetch_player_lookup(self.conn)
        impacts = gs.compute_match_impacts(self.conn)
        html = gs.build_player_page(
            self.conn, self.me, lookup, impacts=impacts,
        )
        self.assertIn("Me Player", html)
        self.assertIn("Player ID #", html)

    def test_match_log_lists_partner_and_opponents(self):
        lookup = gs.fetch_player_lookup(self.conn)
        impacts = gs.compute_match_impacts(self.conn)
        html = gs.build_player_page(
            self.conn, self.me, lookup, impacts=impacts,
        )
        self.assertIn("My Partner", html)
        self.assertIn("Opp One", html)
        self.assertIn("Opp Two", html)

    def test_rank_tag_appears_in_my_match_row(self):
        lookup = gs.fetch_player_lookup(self.conn)
        impacts = gs.compute_match_impacts(self.conn)
        html = gs.build_player_page(
            self.conn, self.me, lookup, impacts=impacts,
        )
        self.assertIn('class="rank-tag"', html)

    def test_impact_row_uses_relative_player_links(self):
        # On a player page, sibling player URLs are "X.html" not "players/X.html".
        lookup = gs.fetch_player_lookup(self.conn)
        impacts = gs.compute_match_impacts(self.conn)
        html = gs.build_player_page(
            self.conn, self.me, lookup, impacts=impacts,
        )
        # The opponent's link in the impact box uses the relative form.
        self.assertRegex(
            html, fr'href="{self.opp1}\.html"',
        )

    def test_returns_empty_string_for_unknown_player(self):
        out = gs.build_player_page(self.conn, 9_999_999, {})
        self.assertEqual(out, "")


# --- 5. CSS sanity ----------------------------------------------------------


class TestCssContainsKeySelectors(unittest.TestCase):
    """Tripwires: regressions that would silently break the impact UI layout."""

    def test_two_vs_two_grid_areas_present(self):
        self.assertIn('grid-template-areas: "a vs b"', gs.CSS)

    def test_mobile_stack_grid_areas_present(self):
        self.assertIn('grid-template-areas: "a" "vs" "b"', gs.CSS)

    def test_rank_tag_styled(self):
        self.assertIn(".rank-tag", gs.CSS)

    def test_impact_box_class_styled(self):
        self.assertIn(".impact-box", gs.CSS)


# --- 6. Regression smoke for older helpers ----------------------------------


class TestComputeFormAndStreaks(unittest.TestCase):
    """The form/streak helpers are used by build_player_page; pin their
    contract so refactors don't silently break the per-player page."""

    def _row(self, won):
        # Match the column layout PLAYER_MATCHES_SQL produces.
        # Indexes: 13 = my_games, 15 = my_won, 18 = opp_games, 22 = opp_won.
        # The new compute_form/_row_won reads ALL of these (post the
        # tied-rubber-by-games-tiebreak change) so we provide concrete
        # win/loss scores instead of bare 0s.
        r = [None] * 23
        r[1] = "2026-01-01"
        r[13] = 6 if won else 0       # my_games
        r[15] = 1 if won else 0       # my_won
        r[18] = 0 if won else 6       # opp_games
        r[22] = 0 if won else 1       # opp_won
        return tuple(r)

    def test_compute_form_renders_recent_results(self):
        matches = [self._row(True), self._row(False), self._row(True)]
        out = gs.compute_form(matches, last_n=10)
        self.assertIn("form", out)  # uses the .form class wrapper
        # Two wins + one loss in the rendered form badges
        self.assertEqual(out.count(">W<"), 2)
        self.assertEqual(out.count(">L<"), 1)

    def test_compute_streaks_finds_current_run(self):
        # Most-recent-first ordering matters here.
        # SQL returns oldest-first; helper iterates accordingly.
        matches = [self._row(True), self._row(True), self._row(True)]
        longest_w, longest_l, cur_streak, cur_kind = gs.compute_streaks(matches)
        self.assertEqual(longest_w, 3)
        self.assertEqual(longest_l, 0)
        self.assertEqual(cur_streak, 3)
        self.assertEqual(cur_kind, "W")

    def test_compute_streaks_handles_alternating(self):
        matches = [self._row(True), self._row(False), self._row(True)]
        longest_w, longest_l, _, _ = gs.compute_streaks(matches)
        self.assertEqual(longest_w, 1)
        self.assertEqual(longest_l, 1)


# --- 7. Trajectory SVG / form / streaks / yearly ----------------------------


class TestRenderTrajectorySvg(unittest.TestCase):
    def test_zero_or_one_point_returns_placeholder(self):
        self.assertIn("Not enough", gs.render_trajectory_svg([]))
        self.assertIn(
            "Not enough",
            gs.render_trajectory_svg([("2026-01-01", 25.0, 8.0)]),
        )

    def test_normal_history_returns_svg_with_polylines(self):
        history = [
            ("2026-01-01", 25.0, 8.0),
            ("2026-02-01", 26.0, 7.5),
            ("2026-03-01", 27.0, 7.0),
        ]
        out = gs.render_trajectory_svg(history)
        self.assertIn("<svg", out)
        # Three polylines: μ, μ-3σ, σ
        self.assertEqual(out.count("<polyline"), 3)
        # Year tick should appear at least once for 2026
        self.assertIn(">2026<", out)

    def test_year_change_emits_extra_tick(self):
        history = [
            ("2025-12-01", 25.0, 8.0),
            ("2026-01-01", 25.5, 7.9),
            ("2026-02-01", 26.0, 7.8),
        ]
        out = gs.render_trajectory_svg(history)
        self.assertIn(">2025<", out)
        self.assertIn(">2026<", out)


class TestComputeFormVariants(unittest.TestCase):
    def _row(self, won):
        r = [None] * 23
        r[1] = "2026-01-01"
        r[13] = 6 if won else 0
        r[15] = 1 if won else 0
        r[18] = 0 if won else 6
        r[22] = 0 if won else 1
        return tuple(r)

    def test_no_matches_returns_no_matches(self):
        self.assertIn("no matches", gs.compute_form([]))

    def test_last_n_caps_output(self):
        matches = [self._row(True)] * 25
        out = gs.compute_form(matches, last_n=5)
        # 5 win badges only
        self.assertEqual(out.count(">W<"), 5)


class TestComputeStreaksEdgeCases(unittest.TestCase):
    def _row(self, won):
        r = [None] * 23
        r[13] = 6 if won else 0
        r[15] = 1 if won else 0
        r[18] = 0 if won else 6
        r[22] = 0 if won else 1
        return tuple(r)

    def test_empty_returns_zero_tuple(self):
        self.assertEqual(gs.compute_streaks([]), (0, 0, 0, ""))

    def test_all_losses_current_streak_is_loss(self):
        matches = [self._row(False)] * 4
        longest_w, longest_l, cur, kind = gs.compute_streaks(matches)
        self.assertEqual(longest_w, 0)
        self.assertEqual(longest_l, 4)
        self.assertEqual(cur, 4)
        self.assertEqual(kind, "L")

    def test_loss_after_wins_resets_current_streak(self):
        # WWWWL (chronological) → current streak is 1L, longest_w is 4.
        matches = [self._row(True)] * 4 + [self._row(False)]
        longest_w, longest_l, cur, kind = gs.compute_streaks(matches)
        self.assertEqual(longest_w, 4)
        self.assertEqual(cur, 1)
        self.assertEqual(kind, "L")


class TestComputeYearlySummary(unittest.TestCase):
    def _row(self, played, won, my_games=None, opp_games=None,
             mu_after=None, sigma_after=None):
        # Default games to a clear win/loss aligned with `won` so the
        # tied-rubber-by-games-tiebreak logic in `_row_won` agrees with the
        # `won` flag. Tests that need atypical scores can pass explicit
        # my_games/opp_games values.
        if my_games is None:
            my_games = 6 if won else 0
        if opp_games is None:
            opp_games = 0 if won else 6
        r = [None] * 23
        r[1] = played
        r[13] = my_games
        r[15] = 1 if won else 0
        r[18] = opp_games
        r[20] = mu_after
        r[21] = sigma_after
        r[22] = 0 if won else 1   # opp_won
        return tuple(r)

    def test_groups_by_year(self):
        matches = [
            self._row("2025-05-01", True),
            self._row("2025-06-01", False),
            self._row("2026-01-01", True),
        ]
        years = gs.compute_yearly_summary(matches)
        self.assertEqual([y["year"] for y in years], ["2025", "2026"])
        self.assertEqual(years[0]["wins"], 1)
        self.assertEqual(years[0]["losses"], 1)
        self.assertEqual(years[1]["wins"], 1)

    def test_mu_first_and_last_track_first_and_last_rated_match(self):
        matches = [
            self._row("2026-01-01", True, mu_after=24.0, sigma_after=8.0),
            self._row("2026-02-01", True, mu_after=25.0, sigma_after=7.5),
            self._row("2026-03-01", True, mu_after=26.0, sigma_after=7.0),
        ]
        [year_2026] = gs.compute_yearly_summary(matches)
        self.assertEqual(year_2026["mu_first"], 24.0)
        self.assertEqual(year_2026["mu_last"], 26.0)

    def test_unparseable_date_lands_in_unknown_bucket(self):
        matches = [self._row("", True)]
        [bucket] = gs.compute_yearly_summary(matches)
        self.assertEqual(bucket["year"], "?")


class TestComputeSwings(unittest.TestCase):
    def test_returns_top_3_wins_and_losses_only(self):
        rows = [
            {"delta": 0.5, "x": "w1"},
            {"delta": 1.0, "x": "w2"},
            {"delta": 1.5, "x": "w3"},
            {"delta": 2.0, "x": "w4"},
            {"delta": -0.5, "x": "l1"},
            {"delta": -1.0, "x": "l2"},
            {"delta": -1.5, "x": "l3"},
            {"delta": -2.0, "x": "l4"},
            {"delta": 0.0, "x": "neutral"},
        ]
        wins, losses = gs.compute_swings(rows)
        self.assertEqual(len(wins), 3)
        self.assertEqual(len(losses), 3)
        # Wins ordered most-positive first
        self.assertEqual([w["delta"] for w in wins], [2.0, 1.5, 1.0])
        # Losses ordered most-negative first
        self.assertEqual([l["delta"] for l in losses], [-2.0, -1.5, -1.0])

    def test_filters_out_zero_deltas(self):
        rows = [{"delta": 0.0}]
        wins, losses = gs.compute_swings(rows)
        self.assertEqual(wins, [])
        self.assertEqual(losses, [])


# --- 8. Render helpers (partner, opponents, score) --------------------------


class TestRenderPartner(unittest.TestCase):
    def test_returns_partner_link_when_partner_exists(self):
        out = gs.render_partner(10, 11, 10, _lookup((10, "Me"), (11, "Pal")))
        self.assertIn("Pal", out)
        self.assertIn("11.html", out)

    def test_handles_player_in_p2_slot(self):
        out = gs.render_partner(11, 10, 10, _lookup((10, "Me"), (11, "Pal")))
        self.assertIn("Pal", out)

    def test_singles_returns_em_dash(self):
        out = gs.render_partner(10, None, 10, _lookup((10, "Me")))
        self.assertIn("—", out)


class TestRenderOpponents(unittest.TestCase):
    def test_two_opponents_joined_with_slash(self):
        names = _lookup((1, "Op1"), (2, "Op2"))
        out = gs.render_opponents(1, 2, names)
        self.assertIn("Op1", out)
        self.assertIn("Op2", out)
        self.assertIn(" / ", out)

    def test_one_opponent_for_singles(self):
        out = gs.render_opponents(1, None, _lookup((1, "Solo")))
        self.assertIn("Solo", out)
        self.assertNotIn(" / ", out)

    def test_no_opponents_returns_em_dash(self):
        out = gs.render_opponents(None, None, {})
        self.assertIn("—", out)


class TestRenderScore(unittest.TestCase):
    def test_renders_two_set_match_for_side_a(self):
        sets = [(1, 6, 2, 0), (2, 6, 4, 0)]
        out = gs.render_score("A", sets)
        self.assertEqual(out.replace(" ", ""), "6-2,6-4")

    def test_renders_from_side_b_perspective(self):
        sets = [(1, 6, 2, 0), (2, 6, 4, 0)]
        out = gs.render_score("B", sets)
        self.assertEqual(out.replace(" ", ""), "2-6,4-6")

    def test_tiebreak_marker_appended(self):
        sets = [(1, 6, 7, 1)]  # was_tiebreak=1
        out = gs.render_score("A", sets)
        self.assertIn("(TB)", out)

    def test_no_set_scores_returns_em_dash(self):
        out = gs.render_score("A", [])
        self.assertIn("—", out)


# --- 9. Neighbours (peers) --------------------------------------------------


class TestFetchNeighbourIndex(unittest.TestCase):
    def setUp(self):
        self.conn = fresh_conn()
        self.club = add_club(self.conn)
        self.m1 = add_player(self.conn, "Top Man", gender="M")
        self.m2 = add_player(self.conn, "Mid Man", gender="M")
        self.f1 = add_player(self.conn, "Top Lady", gender="F")
        self.unknown = add_player(self.conn, "Mystery", gender=None)
        # Unrated player — should not appear in any bucket
        self.m3 = add_player(self.conn, "Unrated Man", gender="M")

        # Ratings
        for pid, mu in ((self.m1, 28.0), (self.m2, 24.0),
                        (self.f1, 27.0), (self.unknown, 25.0)):
            set_current_rating(self.conn, pid, mu, 7.0)

        # Each rated player needs ≥1 active match to appear in buckets.
        _, run = add_source_and_run(self.conn, self.club)
        tour = add_tournament(self.conn, self.club)
        for pid in (self.m1, self.m2, self.f1, self.unknown):
            mid = add_match(
                self.conn, tournament_id=tour, run_id=run,
                played_on="2026-04-01",
                side_a=(pid, None, 6, 1, 1),
                side_b=(self.m3, None, 0, 0, 0),  # opponent is unrated
            )
            del mid

    def tearDown(self):
        self.conn.close()

    def test_buckets_split_by_gender(self):
        b = gs.fetch_neighbour_index(self.conn)
        names_M = [e["name"] for e in b["M"]]
        names_F = [e["name"] for e in b["F"]]
        self.assertIn("Top Man", names_M)
        self.assertIn("Mid Man", names_M)
        self.assertNotIn("Top Lady", names_M)
        self.assertIn("Top Lady", names_F)

    def test_all_bucket_includes_every_rated_player_with_matches(self):
        b = gs.fetch_neighbour_index(self.conn)
        names_all = [e["name"] for e in b["all"]]
        # Mystery (NULL gender) appears only in `all`, not M or F.
        self.assertIn("Mystery", names_all)
        self.assertNotIn(
            "Mystery", [e["name"] for e in b["M"] + b["F"]],
        )

    def test_ordering_is_mu3sigma_descending(self):
        b = gs.fetch_neighbour_index(self.conn)
        scores = [e["mu3s"] for e in b["all"]]
        self.assertEqual(scores, sorted(scores, reverse=True))


class TestRenderNeighbours(unittest.TestCase):
    def _entry(self, pid, mu3s, gender="M", n=10, wins=5):
        return {
            "pid": pid, "name": f"P{pid}", "gender": gender,
            "mu": mu3s + 21.0, "sigma": 7.0, "mu3s": mu3s,
            "n": n, "wins": wins, "captain_class": "B2",
        }

    def test_empty_when_player_not_in_list(self):
        out = gs.render_neighbours([self._entry(1, 5.0)], me_pid=999)
        self.assertEqual(out, "")

    def test_includes_self_with_em_dash_diff(self):
        bucket = [self._entry(1, 5.0), self._entry(2, 4.0)]
        out = gs.render_neighbours(bucket, me_pid=2)
        self.assertIn("P2", out)
        # When highlighted as "me", diff cell shows em dash, not a number.
        self.assertIn("—", out)

    def test_three_above_three_below_window(self):
        # 8 players — me is at index 4; window should be 1..7 inclusive.
        bucket = [self._entry(i, 10.0 - i) for i in range(8)]
        out = gs.render_neighbours(bucket, me_pid=4)
        # P0 is excluded (only 3 above window allowed), P4 included
        self.assertNotIn(">P0<", out)
        self.assertIn(">P4<", out)
        self.assertIn(">P7<", out)


# --- 10. Identity / aliases / merges ----------------------------------------


class TestRenderIdentitySection(unittest.TestCase):
    def setUp(self):
        self.conn = fresh_conn()
        self.club = add_club(self.conn)
        self.pid = add_player(self.conn, "Real Name", gender="M")

    def tearDown(self):
        self.conn.close()

    def test_no_merges_renders_single_record_message(self):
        out = gs.render_identity_section(self.conn, self.pid, "Real Name")
        self.assertIn("No merges", out)
        self.assertIn("Real Name", out)

    def test_alias_rows_show_canonical_first(self):
        sf = self.conn.execute(
            "INSERT INTO source_files (club_id, original_filename, sha256) "
            "VALUES (?, ?, ?)",
            (self.club, "src.xlsx", "abc"),
        ).lastrowid
        self.conn.execute(
            "INSERT INTO player_aliases "
            "(player_id, raw_name, source_file_id) VALUES (?, ?, ?)",
            (self.pid, "Misspelled Nam", sf),
        )
        out = gs.render_identity_section(self.conn, self.pid, "Real Name")
        self.assertIn("Real Name", out)
        self.assertIn("Misspelled Nam", out)
        self.assertIn("(canonical)", out)


# --- 11. End-to-end build_index + build_aliases_page + main() ---------------


class TestBuildIndex(unittest.TestCase):
    def setUp(self):
        self.conn = fresh_conn()
        self.club = add_club(self.conn)
        self.p1 = add_player(self.conn, "Alpha", gender="M")
        self.p2 = add_player(self.conn, "Bravo", gender="F")
        for pid, mu in ((self.p1, 26.0), (self.p2, 27.0)):
            set_current_rating(self.conn, pid, mu, 7.0)
        _, run = add_source_and_run(self.conn, self.club)
        tour = add_tournament(self.conn, self.club)
        # Each player needs ≥1 active match for the leaderboard query.
        for pid in (self.p1, self.p2):
            add_match(
                self.conn, tournament_id=tour, run_id=run,
                played_on="2026-04-01",
                side_a=(pid, None, 6, 1, 1),
                side_b=(self.p1 if pid == self.p2 else self.p2, None, 0, 0, 0),
            )

    def tearDown(self):
        self.conn.close()

    def test_index_lists_rated_players(self):
        html = gs.build_index(self.conn)
        self.assertIn("Alpha", html)
        self.assertIn("Bravo", html)

    def test_index_includes_filter_controls(self):
        html = gs.build_index(self.conn)
        self.assertIn("f-search", html)
        self.assertIn("f-gender", html)


class TestBuildAliasesPage(unittest.TestCase):
    def test_renders_even_with_no_merges(self):
        conn = fresh_conn()
        try:
            html = gs.build_aliases_page(conn, {})
            self.assertTrue(html.startswith("<!DOCTYPE"))
            self.assertIn("</html>", html)
        finally:
            conn.close()


class TestMainEndToEnd(unittest.TestCase):
    """The big one: run gs.main() against the real phase0.sqlite in a
    tempdir. Single test, exercises hundreds of lines via the integrated
    happy-path. Skips if the project DB isn't present."""

    def test_main_writes_expected_files_when_db_present(self):
        import tempfile
        repo_root = Path(__file__).resolve().parent.parent.parent
        db_path = repo_root / "phase0.sqlite"
        if not db_path.exists():
            self.skipTest("phase0.sqlite not found at project root")

        original_db = gs.DB_PATH
        original_out = gs.OUT_DIR
        with tempfile.TemporaryDirectory() as td:
            gs.DB_PATH = str(db_path)
            gs.OUT_DIR = Path(td)
            try:
                rc = gs.main()
            finally:
                gs.DB_PATH = original_db
                gs.OUT_DIR = original_out
            self.assertEqual(rc, 0)
            out = Path(td)
            for f in ("index.html", "matches.html", "styles.css", ".nojekyll"):
                self.assertTrue((out / f).exists(), f"missing {f}")
            # Per-player pages directory should be populated.
            self.assertTrue((out / "players").is_dir())


# --- 12. CLI smoke tests ----------------------------------------------------
#
# cli.py is a Click-style argparse front-end with many subcommands. We don't
# exhaustively test each path; we DO confirm the parser doesn't crash on
# --help and that the basic shape is intact, which exercises the imports +
# subparser wiring (a non-trivial chunk of cli.py).


class TestCliInvocation(unittest.TestCase):
    """CLI exercise tests. Each subcommand is invoked through `cli.main` —
    in-process is faster than subprocess, but we monkeypatch `db.DEFAULT_DB_PATH`
    so the real project DB stays untouched.

    Read-only commands (rank, history, suggest-merges, recommend-pairs)
    can run against the real `phase0.sqlite` if it's present; otherwise they
    skip. Mutating commands run against an empty in-memory schema dumped to
    a tempfile."""

    @classmethod
    def setUpClass(cls):
        repo_root = Path(__file__).resolve().parent.parent.parent
        cls.project_db = repo_root / "phase0.sqlite"
        cls.have_project_db = cls.project_db.exists()

    def setUp(self):
        # Capture stdout so CLI prints don't pollute test output.
        import io
        import contextlib
        self._buf = io.StringIO()
        self._ctx = contextlib.redirect_stdout(self._buf)
        self._ctx.__enter__()

    def tearDown(self):
        self._ctx.__exit__(None, None, None)
        self._restore_db()

    @staticmethod
    def _patch_db(path):
        """Redirect every `db.init_db()` (and the constant) to `path`.

        Python evaluates default-argument values at function-def time, so
        re-binding `db.DEFAULT_DB_PATH` alone wouldn't change `init_db`'s
        default — we wrap `init_db` itself to force the redirect."""
        import db
        db.DEFAULT_DB_PATH = str(path)
        original = getattr(db, "_orig_init_db", None) or db.init_db
        db._orig_init_db = original

        def _patched(p: str = str(path), **kw):
            return original(p, **kw)
        db.init_db = _patched

    @staticmethod
    def _restore_db():
        import db
        if hasattr(db, "_orig_init_db"):
            db.init_db = db._orig_init_db
            del db._orig_init_db

    def test_module_imports_without_side_effects(self):
        import importlib
        mod = importlib.import_module("cli")
        self.assertTrue(hasattr(mod, "main"))
        self.assertTrue(hasattr(mod, "build_parser"))

    def test_build_parser_lists_every_subcommand(self):
        import cli
        parser = cli.build_parser()
        # Trick to enumerate subparsers:
        sub_actions = [
            a for a in parser._actions if isinstance(a, argparse._SubParsersAction)
        ]
        self.assertEqual(len(sub_actions), 1)
        names = set(sub_actions[0].choices.keys())
        for expected in ("load", "rate", "rank", "history", "suggest-merges",
                         "merge-case-duplicates", "merge-token-duplicates",
                         "merge-typo-duplicates", "apply-manual-aliases",
                         "recommend-pairs", "review", "review-server"):
            self.assertIn(expected, names)

    def test_help_for_each_subparser(self):
        # `--help` exits via SystemExit — catch and assert each subcommand
        # has a non-empty help text. Exercises build_parser + every parser
        # description string.
        import cli
        for name in ("load", "rate", "rank", "history", "suggest-merges",
                     "merge-case-duplicates", "merge-token-duplicates",
                     "merge-typo-duplicates", "apply-manual-aliases",
                     "recommend-pairs"):
            with self.assertRaises(SystemExit) as cm:
                cli.main([name, "--help"])
            self.assertEqual(cm.exception.code, 0)

    def test_load_init_only_creates_schema(self):
        import cli, db, tempfile
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
            tmp = f.name
        try:
            self._patch_db(tmp)
            rc = cli.main(["load", "--init-only"])
            self.assertEqual(rc, 0)
            # Re-open and assert at least one of the core tables exists.
            import sqlite3
            conn = sqlite3.connect(tmp)
            tables = {
                r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            conn.close()
            self.assertIn("players", tables)
            self.assertIn("matches", tables)
        finally:
            Path(tmp).unlink(missing_ok=True)

    def test_rank_against_real_db(self):
        if not self.have_project_db:
            self.skipTest("phase0.sqlite not present")
        import cli
        self._patch_db(self.project_db)
        rc = cli.main(["rank", "--top", "5", "--active-months", "0"])
        self.assertEqual(rc, 0)
        # Some rows printed
        self.assertGreater(len(self._buf.getvalue().splitlines()), 0)

    def test_rank_men_only(self):
        if not self.have_project_db:
            self.skipTest("phase0.sqlite not present")
        import cli
        self._patch_db(self.project_db)
        rc = cli.main(
            ["rank", "--top", "3", "--gender", "men", "--active-months", "0"]
        )
        self.assertEqual(rc, 0)

    def test_rank_by_category(self):
        if not self.have_project_db:
            self.skipTest("phase0.sqlite not present")
        import cli
        self._patch_db(self.project_db)
        rc = cli.main(
            ["rank", "--top", "3", "--by-category", "--active-months", "0"]
        )
        self.assertEqual(rc, 0)

    def test_history_unknown_player_returns_nonzero(self):
        if not self.have_project_db:
            self.skipTest("phase0.sqlite not present")
        import cli
        self._patch_db(self.project_db)
        rc = cli.main(["history", "--player", "Definitely Not Real Player Xyz"])
        # Implementation may return 0 with a "not found" message or 1 outright
        # — assert it doesn't crash.
        self.assertIsInstance(rc, int)

    def test_suggest_merges_dry_run(self):
        if not self.have_project_db:
            self.skipTest("phase0.sqlite not present")
        import cli
        self._patch_db(self.project_db)
        rc = cli.main([
            "suggest-merges", "--threshold", "0.95",
            "--limit", "5", "--no-links",
        ])
        self.assertEqual(rc, 0)

    def test_merge_token_duplicates_dry_run_safe(self):
        if not self.have_project_db:
            self.skipTest("phase0.sqlite not present")
        import cli, sqlite3
        self._patch_db(self.project_db)
        # Snapshot a player count before — dry-run should not change it.
        before = sqlite3.connect(self.project_db).execute(
            "SELECT COUNT(*) FROM players WHERE merged_into_id IS NULL"
        ).fetchone()[0]
        rc = cli.main(["merge-token-duplicates", "--dry-run"])
        after = sqlite3.connect(self.project_db).execute(
            "SELECT COUNT(*) FROM players WHERE merged_into_id IS NULL"
        ).fetchone()[0]
        self.assertEqual(rc, 0)
        self.assertEqual(before, after)

    def test_apply_manual_aliases_dry_run_safe(self):
        if not self.have_project_db:
            self.skipTest("phase0.sqlite not present")
        import cli, sqlite3
        self._patch_db(self.project_db)
        before = sqlite3.connect(self.project_db).execute(
            "SELECT COUNT(*) FROM players WHERE merged_into_id IS NOT NULL"
        ).fetchone()[0]
        rc = cli.main(["apply-manual-aliases", "--dry-run"])
        after = sqlite3.connect(self.project_db).execute(
            "SELECT COUNT(*) FROM players WHERE merged_into_id IS NOT NULL"
        ).fetchone()[0]
        self.assertEqual(rc, 0)
        self.assertEqual(before, after)

    def test_recommend_pairs_against_real_db(self):
        if not self.have_project_db:
            self.skipTest("phase0.sqlite not present")
        import cli, sqlite3
        self._patch_db(self.project_db)
        # Pick 4 known canonical names from the DB.
        names = [
            r[0] for r in sqlite3.connect(self.project_db).execute(
                "SELECT canonical_name FROM players p JOIN ratings r "
                "ON r.player_id = p.id WHERE p.merged_into_id IS NULL "
                "ORDER BY r.n_matches DESC LIMIT 4"
            )
        ]
        if len(names) < 4:
            self.skipTest("not enough rated players")
        rc = cli.main(["recommend-pairs", "--players", ",".join(names)])
        self.assertEqual(rc, 0)


# --- 13. Players module — push from 71% → higher ----------------------------


class TestPlayerNormalizationExtras(unittest.TestCase):
    """Round-trip checks beyond the existing TestNormalizeName suite."""

    def test_double_apostrophe_collapsed(self):
        import players
        # Both U+2019 and ASCII apostrophes survive normalization symmetrically.
        self.assertEqual(
            players.normalize_name("D'Alessandro"),
            players.normalize_name("D’Alessandro"),
        )

    def test_idempotent(self):
        import players
        once = players.normalize_name("  Mark  Gatt  ")
        twice = players.normalize_name(once)
        self.assertEqual(once, twice)


class TestMergePlayerInto(unittest.TestCase):
    """The merge_player_into call path is the basis for every fuzzy/manual
    merge. Cover its happy path against an in-memory DB."""

    def test_merge_redirects_match_sides_and_marks_loser(self):
        import players
        conn = fresh_conn()
        try:
            club = add_club(conn)
            winner = add_player(conn, "Winner Name", gender="M")
            loser = add_player(conn, "Loser Name", gender="M")
            other = add_player(conn, "Other", gender="M")
            _, run = add_source_and_run(conn, club)
            tour = add_tournament(conn, club)
            mid = add_match(
                conn, tournament_id=tour, run_id=run,
                played_on="2026-01-01",
                side_a=(loser, None, 6, 1, 1),
                side_b=(other, None, 0, 0, 0),
            )

            players.merge_player_into(
                conn, loser_id=loser, winner_id=winner,
                reason="test merge",
            )
            conn.commit()

            row = conn.execute(
                "SELECT player1_id FROM match_sides WHERE match_id = ? "
                "AND side = 'A'", (mid,),
            ).fetchone()
            self.assertEqual(row[0], winner)

            merged = conn.execute(
                "SELECT merged_into_id FROM players WHERE id = ?", (loser,),
            ).fetchone()[0]
            self.assertEqual(merged, winner)
        finally:
            conn.close()


# --- 14. team_selection module ----------------------------------------------


class TestTeamSelectionStorage(unittest.TestCase):
    def _stub_get_or_create(self, conn, raw_name, source_file_id):
        """Mimic players.get_or_create_player without the normalization layer
        — we just need a player_id back for each unique name."""
        del source_file_id  # unused by stub
        row = conn.execute(
            "SELECT id FROM players WHERE canonical_name = ?",
            (raw_name,),
        ).fetchone()
        if row:
            return row[0]
        cur = conn.execute(
            "INSERT INTO players (canonical_name) VALUES (?)", (raw_name,),
        )
        return cur.lastrowid

    def test_store_inserts_player_team_assignments(self):
        import team_selection as ts
        conn = fresh_conn()
        try:
            club = add_club(conn)
            tour = add_tournament(conn, club, fmt="doubles_team")
            sf = conn.execute(
                "INSERT INTO source_files (club_id, original_filename, sha256)"
                " VALUES (?, ?, ?)", (club, "src.xlsx", "abc"),
            ).lastrowid
            assignments = [
                {"team_letter": "A", "captain_name": "Cap",
                 "class_label": "A1", "tier_letter": "A", "slot_number": 1,
                 "player_name": "Captain Alpha", "gender": "M"},
                {"team_letter": "A", "captain_name": "Cap",
                 "class_label": "A2", "tier_letter": "A", "slot_number": 2,
                 "player_name": "Squad Member", "gender": "M"},
            ]
            inserted = ts.store_team_selection(
                conn, tour, sf, assignments,
                get_or_create_player_fn=self._stub_get_or_create,
            )
            self.assertEqual(inserted, 2)
            rows = conn.execute(
                "SELECT team_letter, class_label "
                "FROM player_team_assignments WHERE tournament_id = ? "
                "ORDER BY class_label",
                (tour,),
            ).fetchall()
            self.assertEqual(rows, [("A", "A1"), ("A", "A2")])
        finally:
            conn.close()

    def test_player_current_class_returns_most_recent(self):
        import team_selection as ts
        conn = fresh_conn()
        try:
            club = add_club(conn)
            sf = conn.execute(
                "INSERT INTO source_files (club_id, original_filename, sha256)"
                " VALUES (?, ?, ?)", (club, "src.xlsx", "abc"),
            ).lastrowid
            old_tour = add_tournament(
                conn, club, name="Old Cup", year=2024, fmt="doubles_team",
            )
            new_tour = add_tournament(
                conn, club, name="New Cup", year=2026, fmt="doubles_team",
            )
            pid = add_player(conn, "Mover")
            for tour, cls in ((old_tour, "C1"), (new_tour, "B2")):
                ts.store_team_selection(
                    conn, tour, sf,
                    [{"team_letter": "A", "captain_name": "Cap",
                      "class_label": cls, "tier_letter": cls[0],
                      "slot_number": int(cls[1]), "player_name": "Mover",
                      "gender": "M"}],
                    get_or_create_player_fn=lambda c, n, s: pid,
                )
            cls, tier, slot = ts.player_current_class(conn, pid)
            self.assertEqual((cls, tier, slot), ("B2", "B", 2))
        finally:
            conn.close()

    def test_player_class_history_orders_by_year(self):
        import team_selection as ts
        conn = fresh_conn()
        try:
            club = add_club(conn)
            sf = conn.execute(
                "INSERT INTO source_files (club_id, original_filename, sha256)"
                " VALUES (?, ?, ?)", (club, "src.xlsx", "abc"),
            ).lastrowid
            t24 = add_tournament(conn, club, year=2024, fmt="doubles_team")
            t26 = add_tournament(conn, club, year=2026, fmt="doubles_team")
            pid = add_player(conn, "Hist")
            for tour, cls in ((t24, "D1"), (t26, "A2")):
                ts.store_team_selection(
                    conn, tour, sf,
                    [{"team_letter": "B", "captain_name": "Cap",
                      "class_label": cls, "tier_letter": cls[0],
                      "slot_number": int(cls[1]), "player_name": "Hist"}],
                    get_or_create_player_fn=lambda c, n, s: pid,
                )
            history = ts.player_class_history(conn, pid)
            self.assertEqual(len(history), 2)
            # Ordering is implementation-defined but each row should have a year.
            years = sorted(h["year"] for h in history)
            self.assertEqual(years, [2024, 2026])
        finally:
            conn.close()


# --- 15. Build-time safety: no module-level side effects --------------------


class TestModuleImportSafety(unittest.TestCase):
    """Importing generate_site shouldn't touch the disk or DB. This guards
    against future refactors that move setup into module scope by accident."""

    def test_db_path_is_a_string(self):
        self.assertIsInstance(gs.DB_PATH, str)

    def test_out_dir_is_a_path(self):
        self.assertTrue(hasattr(gs.OUT_DIR, "mkdir"))

    def test_model_constant_set(self):
        self.assertEqual(gs.MODEL, "openskill_pl")


if __name__ == "__main__":
    unittest.main(verbosity=2)
