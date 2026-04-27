#!/usr/bin/env python3
"""One-off cleanup for the CROSS-CLUB tournament-duplication bug.

Background: a sibling of T-P0.5-020. The earlier `dedupe_tournaments.py`
collapses tournaments that share `(club_id, name, year)`. But a single
physical tournament can also exist under TWO clubs in `_DATA_/`:

  _DATA_/2025/VLTC/<slug>/foo.xlsx
  _DATA_/2025/TCK/<slug>/foo.xlsx

Different `club_id` per source path → two `tournaments` rows → identical
match content stored twice → 2x active matches in the rating engine.

The xlsx files are byte-different (different download timestamps and
embedded image filenames) but contain identical tabular data, so the
sha256-only fallback in source_files dedup (T-P0.5-020) cannot catch
them at ingest time. This script repairs the existing data by
collapsing each cross-club tournament group to a single canonical row.

What this script does:
  1. For each (name, year) group with > 1 distinct club_id, identify
     the canonical tournament — defined as "the row that owns the most
     active matches", tie-broken by lowest id. (This matches the
     within-club dedupe convention.)
  2. Mark every active match belonging to any non-canonical tournament
     in the group as superseded by the latest ingestion_run.
  3. Write one audit_log entry per superseded match.
  4. Print pre/post diagnostics.

Idempotent — re-running after the cleanup is a no-op (only touches
matches whose superseded_by_run_id IS NULL).
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

DEFAULT_DB = str(Path(__file__).resolve().parent.parent.parent / "phase0.sqlite")
ACTION = "tournament.cross_club_deduped"
TASK_ID = "T-P0.5-023"


def find_cross_club_groups(conn: sqlite3.Connection) -> list[dict]:
    """Return groups where the same (name, year) spans multiple clubs.

    Each entry: {
        'name': str, 'year': int,
        'members': [(tournament_id, club_id, n_active_matches), ...],
        'canonical_id': int,        # the one we keep
        'dup_ids': [int, ...],      # tournaments whose active matches we supersede
        'matches_to_supersede': int,
    }
    """
    group_keys = conn.execute(
        """
        SELECT name, year
        FROM tournaments
        GROUP BY name, year
        HAVING COUNT(DISTINCT club_id) > 1
        ORDER BY year, name
        """
    ).fetchall()

    groups = []
    for name, year in group_keys:
        members = conn.execute(
            """
            SELECT
                t.id,
                t.club_id,
                (SELECT COUNT(*) FROM matches m
                 WHERE m.tournament_id = t.id
                   AND m.superseded_by_run_id IS NULL) AS n_active
            FROM tournaments t
            WHERE t.name = ? AND t.year = ?
            ORDER BY t.id
            """,
            (name, year),
        ).fetchall()

        # Canonical: most active matches, tiebreak lowest id.
        sorted_members = sorted(members, key=lambda m: (-m[2], m[0]))
        canonical_id = sorted_members[0][0]

        dup_ids = [tid for tid, _, _ in members if tid != canonical_id]
        matches_to_supersede = sum(
            n for tid, _, n in members if tid != canonical_id
        )

        groups.append({
            "name": name,
            "year": year,
            "members": members,
            "canonical_id": canonical_id,
            "dup_ids": dup_ids,
            "matches_to_supersede": matches_to_supersede,
        })
    return groups


def print_summary(groups: list[dict]) -> int:
    print(f"Found {len(groups)} cross-club tournament group(s).\n")
    total = 0
    print(f"{'year':>4}  {'canon':>6}  {'members (id:club:n_active)':<60}  "
          f"{'active->sup':>11}  name")
    print("-" * 130)
    for g in groups:
        member_str = ", ".join(
            f"[{tid}:c{cid}:{n}]" if tid == g["canonical_id"]
            else f"{tid}:c{cid}:{n}"
            for tid, cid, n in g["members"]
        )
        print(
            f"{g['year']:>4}  {g['canonical_id']:>6}  {member_str[:60]:<60}  "
            f"{g['matches_to_supersede']:>11}  {g['name']}"
        )
        total += g["matches_to_supersede"]
    print("-" * 130)
    print(f"Total active matches that would be superseded: {total}")
    return total


def apply_supersede(conn: sqlite3.Connection, groups: list[dict]) -> tuple[int, int]:
    """Mark every active match in non-canonical tournaments as superseded.

    Writes one audit_log row per superseded match.

    Returns (n_matches_superseded, n_audit_rows_written).
    """
    max_run_id = conn.execute("SELECT MAX(id) FROM ingestion_runs").fetchone()[0]
    if max_run_id is None:
        raise RuntimeError("No ingestion_runs rows — cannot stamp supersede.")

    all_dup_ids: list[int] = []
    canon_for: dict[int, int] = {}
    name_year_for: dict[int, tuple[str, int]] = {}
    for g in groups:
        for did in g["dup_ids"]:
            all_dup_ids.append(did)
            canon_for[did] = g["canonical_id"]
            name_year_for[did] = (g["name"], g["year"])
    if not all_dup_ids:
        return 0, 0

    # Snapshot affected matches BEFORE update so we can audit them.
    placeholders = ",".join("?" * len(all_dup_ids))
    affected = conn.execute(
        f"""
        SELECT id, tournament_id, played_on
        FROM matches
        WHERE tournament_id IN ({placeholders})
          AND superseded_by_run_id IS NULL
        """,
        all_dup_ids,
    ).fetchall()

    # Supersede them.
    cur = conn.execute(
        f"""
        UPDATE matches
        SET superseded_by_run_id = ?
        WHERE tournament_id IN ({placeholders})
          AND superseded_by_run_id IS NULL
        """,
        (max_run_id, *all_dup_ids),
    )
    n_superseded = cur.rowcount

    # Audit each one.
    n_audit = 0
    for match_id, tid, played_on in affected:
        canonical_id = canon_for[tid]
        name, year = name_year_for[tid]
        conn.execute(
            """
            INSERT INTO audit_log (
                action, entity_type, entity_id, before_jsonb, after_jsonb
            ) VALUES (?, 'match', ?, ?, ?)
            """,
            (
                ACTION,
                match_id,
                json.dumps({
                    "match_id": match_id,
                    "tournament_id": tid,
                    "tournament_name": name,
                    "tournament_year": year,
                    "played_on": played_on,
                    "superseded_by_run_id": None,
                    "reason": (
                        f"{TASK_ID}: cross-club duplicate tournament — same "
                        "(name, year) ingested under multiple clubs because "
                        "the source xlsx exists in both _DATA_/<year>/VLTC/ "
                        "and _DATA_/<year>/TCK/ as byte-different but "
                        "content-identical files. Match superseded; "
                        f"canonical tournament_id = {canonical_id}."
                    ),
                }),
                json.dumps({
                    "match_id": match_id,
                    "tournament_id": tid,
                    "superseded_by_run_id": max_run_id,
                    "canonical_tournament_id": canonical_id,
                }),
            ),
        )
        n_audit += 1

    return n_superseded, n_audit


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
    p.add_argument("--db", default=DEFAULT_DB,
                   help=f"SQLite path (default: {DEFAULT_DB})")
    p.add_argument("--apply", action="store_true",
                   help="Actually write changes (default is dry-run).")
    args = p.parse_args(argv)

    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA foreign_keys = ON;")

    pre_active, pre_distinct = verify(conn)
    print("=== Pre-cleanup ===")
    print(f"  active matches:            {pre_active}")
    print(f"  distinct match signatures: {pre_distinct}")
    print(f"  excess (=active-distinct): {pre_active - pre_distinct}")
    print()

    groups = find_cross_club_groups(conn)
    if not groups:
        print("No cross-club duplicate tournaments — nothing to do.")
        return 0

    expected = print_summary(groups)
    print()

    if not args.apply:
        print("DRY RUN — re-run with --apply to commit.")
        return 0

    n_superseded, n_audit = apply_supersede(conn, groups)
    conn.commit()
    print()
    print(f"=== Applied: {n_superseded} match(es) superseded, "
          f"{n_audit} audit_log row(s) written ===")

    post_active, post_distinct = verify(conn)
    print()
    print("=== Post-cleanup ===")
    print(f"  active matches:            {post_active}")
    print(f"  distinct match signatures: {post_distinct}")
    print(f"  excess (=active-distinct): {post_active - post_distinct}")
    print()
    if post_active - post_distinct > 0:
        print("NOTE: residual excess remains — likely intra-tournament parser "
              "duplicates (Elektra Mixed Doubles 2023, Sports Experience 2025) "
              "or other known parser quirks. Out of scope for the cross-club "
              "fix.")
    print()
    print("Next: `python3 scripts/phase0/cli.py rate` to rebuild rating_history.")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
