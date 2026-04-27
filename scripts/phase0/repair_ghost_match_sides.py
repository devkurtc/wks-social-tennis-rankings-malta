"""One-time repair for T-P0.5-025: redirect match_sides rows that point at
merged-out (ghost) player records to the surviving canonical id.

Walks `merged_into_id` chains for every match_sides row whose `player1_id` or
`player2_id` references a player with `merged_into_id IS NOT NULL`. Updates the
row in-place and writes one `audit_log` entry per redirect with
`action='match_sides.ghost_redirect'` so the change is reversible.

The companion code-hardening fix lives in `players.get_or_create_player` —
without that, re-ingestion would re-introduce the same drift this script
repairs.

Run from repo root (or any cwd — the DB path is anchored to this file's repo
root, never cwd):

    python scripts/phase0/repair_ghost_match_sides.py            # apply
    python scripts/phase0/repair_ghost_match_sides.py --dry-run  # preview only

All work happens in a single transaction. If anything fails, the whole repair
rolls back and no audit rows are written.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow `import db` whether run as script or module
sys.path.insert(0, str(Path(__file__).parent))

import db  # noqa: E402


def _resolve_terminal_id(
    cache: dict[int, int], all_merges: dict[int, int], pid: int
) -> int:
    """Walk merged_into_id chain to the terminal canonical id, with cycle guard."""
    if pid in cache:
        return cache[pid]
    seen: set[int] = set()
    cur = pid
    while cur in all_merges and cur not in seen:
        seen.add(cur)
        cur = all_merges[cur]
    cache[pid] = cur
    return cur


def repair(conn, *, dry_run: bool = False) -> dict:
    """Find and (optionally) repair stale match_sides rows.

    Returns a dict with stats: {stale_rows, distinct_ghosts, redirects, audited}.
    """
    # 1. Build merge lookup. Snapshot once so we can resolve chains in Python
    #    without N round-trips to the DB.
    all_merges: dict[int, int] = dict(
        conn.execute(
            "SELECT id, merged_into_id FROM players WHERE merged_into_id IS NOT NULL"
        ).fetchall()
    )
    cache: dict[int, int] = {}

    # 2. Find every match_sides row that touches a merged-out player. Snapshot
    #    the full row shape (incl. games_won, won, side, match_id) for audit.
    stale_rows = conn.execute(
        """
        SELECT
            ms.match_id,
            ms.side,
            ms.player1_id,
            ms.player2_id,
            ms.games_won,
            ms.won
        FROM match_sides ms
        WHERE EXISTS (
            SELECT 1 FROM players p
            WHERE (p.id = ms.player1_id OR p.id = ms.player2_id)
              AND p.merged_into_id IS NOT NULL
        )
        """
    ).fetchall()

    # 3. Compute the corrected ids per row and group ghosts.
    distinct_ghosts: set[int] = set()
    plan: list[dict] = []
    for match_id, side, p1_id, p2_id, games_won, won in stale_rows:
        new_p1 = _resolve_terminal_id(cache, all_merges, p1_id)
        new_p2 = _resolve_terminal_id(cache, all_merges, p2_id)
        if p1_id in all_merges:
            distinct_ghosts.add(p1_id)
        if p2_id in all_merges:
            distinct_ghosts.add(p2_id)
        # Sanity: terminal ids must NOT themselves be merged (the diagnostic
        # earlier confirmed 0 unresolvable chains, but be paranoid here).
        if new_p1 in all_merges or new_p2 in all_merges:
            raise RuntimeError(
                f"unresolvable merge chain reached merged-out id "
                f"(match_id={match_id} side={side} "
                f"p1={p1_id}->{new_p1} p2={p2_id}->{new_p2}); aborting"
            )
        plan.append(
            {
                "match_id": match_id,
                "side": side,
                "before": {
                    "player1_id": p1_id,
                    "player2_id": p2_id,
                    "games_won": games_won,
                    "won": won,
                },
                "after": {
                    "player1_id": new_p1,
                    "player2_id": new_p2,
                    "games_won": games_won,
                    "won": won,
                },
            }
        )

    stats = {
        "stale_rows": len(stale_rows),
        "distinct_ghosts": len(distinct_ghosts),
        "redirects": 0,
        "audited": 0,
    }

    if dry_run:
        return stats

    # 4. Apply within a single transaction.
    with conn:
        for entry in plan:
            mid = entry["match_id"]
            sd = entry["side"]
            before = entry["before"]
            after = entry["after"]

            cur = conn.execute(
                "UPDATE match_sides "
                "SET player1_id = ?, player2_id = ? "
                "WHERE match_id = ? AND side = ?",
                (after["player1_id"], after["player2_id"], mid, sd),
            )
            stats["redirects"] += cur.rowcount

            conn.execute(
                """
                INSERT INTO audit_log (
                    action, entity_type, entity_id, before_jsonb, after_jsonb
                ) VALUES (?, 'match', ?, ?, ?)
                """,
                (
                    "match_sides.ghost_redirect",
                    mid,
                    json.dumps(
                        {
                            "match_id": mid,
                            "side": sd,
                            "player1_id": before["player1_id"],
                            "player2_id": before["player2_id"],
                            "games_won": before["games_won"],
                            "won": before["won"],
                            "reason": (
                                "T-P0.5-025: redirected match_sides slot from "
                                "merged-out (ghost) player id to terminal "
                                "canonical id (chain walk via merged_into_id)"
                            ),
                        }
                    ),
                    json.dumps(
                        {
                            "match_id": mid,
                            "side": sd,
                            "player1_id": after["player1_id"],
                            "player2_id": after["player2_id"],
                            "games_won": after["games_won"],
                            "won": after["won"],
                        }
                    ),
                ),
            )
            stats["audited"] += 1

    return stats


def _verify(conn) -> tuple[int, int]:
    stale = conn.execute(
        """
        SELECT COUNT(*) FROM match_sides ms
        WHERE EXISTS (
            SELECT 1 FROM players p
            WHERE (p.id = ms.player1_id OR p.id = ms.player2_id)
              AND p.merged_into_id IS NOT NULL
        )
        """
    ).fetchone()[0]
    ghosts = conn.execute(
        """
        SELECT COUNT(DISTINCT pid) FROM (
            SELECT ms.player1_id AS pid FROM match_sides ms
            JOIN players p ON p.id = ms.player1_id
            WHERE p.merged_into_id IS NOT NULL
            UNION
            SELECT ms.player2_id FROM match_sides ms
            JOIN players p ON p.id = ms.player2_id
            WHERE p.merged_into_id IS NOT NULL
        )
        """
    ).fetchone()[0]
    return stale, ghosts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without modifying the DB.",
    )
    args = ap.parse_args()

    conn = db.init_db()
    try:
        stale_before, ghosts_before = _verify(conn)
        print(
            f"Pre-repair:  {stale_before} stale match_sides rows, "
            f"{ghosts_before} distinct ghost players"
        )

        stats = repair(conn, dry_run=args.dry_run)

        if args.dry_run:
            print(
                f"DRY RUN — would redirect {stats['stale_rows']} rows "
                f"affecting {stats['distinct_ghosts']} ghost players "
                f"(no DB changes, no audit rows written)."
            )
            return 0

        stale_after, ghosts_after = _verify(conn)
        print(
            f"Post-repair: {stale_after} stale match_sides rows, "
            f"{ghosts_after} distinct ghost players"
        )
        print(
            f"Wrote {stats['audited']} audit_log "
            f"'match_sides.ghost_redirect' rows; UPDATE rowcount={stats['redirects']}."
        )
        if stale_after != 0 or ghosts_after != 0:
            print("WARNING: post-repair counts non-zero; investigate.", file=sys.stderr)
            return 1
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
