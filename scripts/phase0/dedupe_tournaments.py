#!/usr/bin/env python3
"""One-off cleanup for the tournament-duplication bug.

Background: every parser used an unconditional INSERT INTO tournaments. When
the same tournament file was ingested under two different filenames (scraper
rename → different source_files row → different tournament row), both sets of
matches survived as `active` (superseded_by_run_id IS NULL), inflating
`rating_history` and corrupting every player's rating.

What this script does:
  1. For each (club_id, name, year) group with > 1 tournament row, identify
     the canonical tournament — defined as "the row that owns the most active
     matches", tie-broken by lowest id. (We deliberately do NOT use
     "lowest id" alone: prior runs of an identical filename were already
     superseded by `_supersede_prior_runs_for_file`, so the lowest-id
     tournament often has 0 active matches and is NOT what we want to keep.)
  2. Mark every active match belonging to any non-canonical tournament in the
     group as superseded by the latest ingestion_run.
  3. Print a dry-run summary, then (if --apply) commit the changes.

After this:
  - Run `python3 scripts/phase0/cli.py rate` to rebuild rating_history from
    the cleaned active-match set.
  - Verify the 'active matches == distinct match signatures' invariant holds.

This script is idempotent — re-running it after the cleanup is a no-op (it
only touches matches whose superseded_by_run_id IS NULL).
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

DEFAULT_DB = str(Path(__file__).resolve().parent.parent.parent / "phase0.sqlite")


def find_duplicate_groups(conn: sqlite3.Connection) -> list[dict]:
    """Return a list of duplicate-tournament groups with active-match counts.

    Each entry: {
        'club_id': int, 'name': str, 'year': int,
        'members': [(tournament_id, n_active_matches), ...],
        'canonical_id': int,        # the one we keep
        'dup_ids': [int, ...],      # the ones whose active matches we supersede
        'matches_to_supersede': int,
    }
    """
    group_keys = conn.execute(
        """
        SELECT club_id, name, year
        FROM tournaments
        GROUP BY club_id, name, year
        HAVING COUNT(*) > 1
        ORDER BY year, name
        """
    ).fetchall()

    groups = []
    for club_id, name, year in group_keys:
        members = conn.execute(
            """
            SELECT
                t.id,
                (SELECT COUNT(*) FROM matches m
                 WHERE m.tournament_id = t.id
                   AND m.superseded_by_run_id IS NULL) AS n_active
            FROM tournaments t
            WHERE t.club_id = ? AND t.name = ? AND t.year = ?
            ORDER BY t.id
            """,
            (club_id, name, year),
        ).fetchall()

        # Pick canonical: most active matches, tiebreak by lowest id.
        sorted_members = sorted(members, key=lambda m: (-m[1], m[0]))
        canonical_id = sorted_members[0][0]

        # Duplicates = every other member, but we only care about ones with
        # active matches (members with 0 active are already superseded — touching
        # them is a no-op but we still report).
        dup_ids = [tid for tid, _ in members if tid != canonical_id]
        matches_to_supersede = sum(
            n for tid, n in members if tid != canonical_id
        )

        groups.append({
            "club_id": club_id,
            "name": name,
            "year": year,
            "members": members,
            "canonical_id": canonical_id,
            "dup_ids": dup_ids,
            "matches_to_supersede": matches_to_supersede,
        })
    return groups


def print_summary(groups: list[dict]) -> int:
    """Print a per-group breakdown and return total active matches to supersede."""
    print(f"Found {len(groups)} duplicate-tournament group(s).\n")
    total = 0
    print(f"{'year':>4}  {'canon':>6}  {'dups':<25}  {'active→sup':>10}  name")
    print("-" * 100)
    for g in groups:
        member_str = ", ".join(
            f"{tid}({n})" if tid != g["canonical_id"] else f"[{tid}({n})]"
            for tid, n in g["members"]
        )
        print(
            f"{g['year']:>4}  {g['canonical_id']:>6}  {member_str[:25]:<25}  "
            f"{g['matches_to_supersede']:>10}  {g['name']}"
        )
        total += g["matches_to_supersede"]
    print("-" * 100)
    print(f"Total active matches that would be superseded: {total}")
    return total


def apply_supersede(conn: sqlite3.Connection, groups: list[dict]) -> int:
    """Mark every active match in non-canonical tournaments as superseded.

    Uses the latest ingestion_runs.id as the superseded_by_run_id stamp
    (we don't have a real "this run did the supersession" run — using the
    most recent existing run keeps the FK happy and signals "post-load
    cleanup").

    Returns the actual number of matches updated.
    """
    max_run_id = conn.execute(
        "SELECT MAX(id) FROM ingestion_runs"
    ).fetchone()[0]
    if max_run_id is None:
        raise RuntimeError("No ingestion_runs rows — cannot stamp supersede.")

    all_dup_ids: list[int] = []
    for g in groups:
        all_dup_ids.extend(g["dup_ids"])
    if not all_dup_ids:
        return 0

    placeholders = ",".join("?" * len(all_dup_ids))
    cur = conn.execute(
        f"""
        UPDATE matches
        SET superseded_by_run_id = ?
        WHERE tournament_id IN ({placeholders})
          AND superseded_by_run_id IS NULL
        """,
        (max_run_id, *all_dup_ids),
    )
    return cur.rowcount


def verify(conn: sqlite3.Connection) -> tuple[int, int]:
    """Return (n_active_matches, n_distinct_match_signatures)."""
    active = conn.execute(
        "SELECT COUNT(*) FROM matches WHERE superseded_by_run_id IS NULL"
    ).fetchone()[0]
    distinct = conn.execute(
        """
        SELECT COUNT(*) FROM (
            SELECT m.played_on, msa.player1_id, msa.player2_id,
                   msb.player1_id, msb.player2_id
            FROM matches m
            JOIN match_sides msa ON msa.match_id = m.id AND msa.side='A'
            JOIN match_sides msb ON msb.match_id = m.id AND msb.side='B'
            WHERE m.superseded_by_run_id IS NULL
            GROUP BY m.played_on, msa.player1_id, msa.player2_id,
                     msb.player1_id, msb.player2_id
        )
        """
    ).fetchone()[0]
    return active, distinct


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default=DEFAULT_DB, help=f"SQLite path (default: {DEFAULT_DB})")
    p.add_argument("--apply", action="store_true",
                   help="Actually write changes (default is dry-run).")
    args = p.parse_args(argv)

    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA foreign_keys = ON;")

    pre_active, pre_distinct = verify(conn)
    print(f"=== Pre-cleanup ===")
    print(f"  active matches:            {pre_active}")
    print(f"  distinct match signatures: {pre_distinct}")
    print(f"  excess (=active-distinct): {pre_active - pre_distinct}")
    print()

    groups = find_duplicate_groups(conn)
    if not groups:
        print("No duplicate tournaments — nothing to do.")
        return 0

    expected = print_summary(groups)
    print()

    if not args.apply:
        print("DRY RUN — re-run with --apply to commit.")
        return 0

    actual = apply_supersede(conn, groups)
    conn.commit()
    print()
    print(f"=== Applied: {actual} match(es) marked superseded ===")

    post_active, post_distinct = verify(conn)
    print()
    print(f"=== Post-cleanup ===")
    print(f"  active matches:            {post_active}")
    print(f"  distinct match signatures: {post_distinct}")
    print(f"  excess (=active-distinct): {post_active - post_distinct}")
    print()
    if post_active != post_distinct:
        print("NOTE: residual excess remains — likely intra-tournament parser "
              "duplicates (Elektra Mixed Doubles 2023 + San Michel 2026) or "
              "cross-name parser-year-detection bugs. These are out of scope "
              "for the tournament-duplication fix and warrant separate "
              "investigation.")
    print()
    print("Next: `python3 scripts/phase0/cli.py rate` to rebuild rating_history.")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
