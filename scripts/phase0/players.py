"""Player name normalization + alias storage for Phase 0.

See PLAN.md §5.4 for the full 3-layer entity-resolution design. This file
implements layer 1 only (within-file normalization). Layer 2 (within-club
fuzzy match + admin confirmation) and layer 3 (cross-club linking) land in
Phase 1+ via a separate merge CLI.

Rules:
- NFKC unicode normalization (composes decomposed characters).
- Curly / typographic apostrophes → straight ASCII apostrophe.
- Internal whitespace runs collapsed to single space.
- Leading/trailing whitespace stripped.
- Casing PRESERVED (display name matters).

Phase 0 trade-off: two raw names that produce different canonical forms
become two distinct players. So "Mark Gatt" and "MARK GATT" create two
records — that's a Phase 1 merge problem.
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata

# Apostrophe variants we normalize to ASCII '
# U+2018 LEFT SINGLE QUOTATION MARK
# U+2019 RIGHT SINGLE QUOTATION MARK
# U+02BC MODIFIER LETTER APOSTROPHE
# U+02BB MODIFIER LETTER TURNED COMMA
# U+201B SINGLE HIGH-REVERSED-9 QUOTATION MARK
# U+0060 GRAVE ACCENT (backtick) — common in Maltese-club Excel exports;
#        e.g. "Pule`" intended to mean "Pule'"
# U+00B4 ACUTE ACCENT
_APOSTROPHE_TABLE = str.maketrans({c: "'" for c in "‘’ʼʻ‛`´"})

_WHITESPACE_RUN = re.compile(r"\s+")


def normalize_name(raw: str) -> str:
    """Return the canonical form of a player name (see module docstring)."""
    s = unicodedata.normalize("NFKC", raw)
    s = s.translate(_APOSTROPHE_TABLE)
    s = _WHITESPACE_RUN.sub(" ", s).strip()
    return s


def get_or_create_player(
    conn: sqlite3.Connection,
    raw_name: str,
    source_file_id: int | None = None,
) -> int:
    """Look up or create a player by raw name. Returns the player_id.

    On first sight: creates a `players` row (canonical form as `canonical_name`)
    and a `player_aliases` row recording the raw form.

    On repeat sight (same canonical name): returns the existing player_id and
    adds a new alias only if this exact raw form has not been seen before for
    this player.
    """
    canonical = normalize_name(raw_name)

    row = conn.execute(
        "SELECT id FROM players WHERE canonical_name = ?", (canonical,)
    ).fetchone()

    if row is None:
        cur = conn.execute(
            "INSERT INTO players (canonical_name) VALUES (?)", (canonical,)
        )
        player_id = cur.lastrowid
    else:
        player_id = row[0]

    # UNIQUE(player_id, raw_name) means the same alias inserted twice would
    # fail; INSERT OR IGNORE makes the call idempotent.
    conn.execute(
        "INSERT OR IGNORE INTO player_aliases (player_id, raw_name, source_file_id) "
        "VALUES (?, ?, ?)",
        (player_id, raw_name, source_file_id),
    )
    return player_id


# ---- Player merge operations (case-only duplicates) ----
#
# Phase 0 normalize_name preserves casing (display name matters), so a
# tournament that wrote a player's name in ALL CAPS produces a *separate*
# player record from the same player's normal-cased record. The Phase 1
# fuzzy-match merge tool will collapse these properly. Until then, this
# helper handles the most common easy case: same name modulo casing.
#
# Audit: every merge writes one `player.merged` row to audit_log.


def find_case_duplicate_groups(
    conn: sqlite3.Connection,
) -> list[list[tuple[int, str, int]]]:
    """Find groups of players whose canonical_name collapses to the same form
    under the *current* normalization rules (NFKC + apostrophe variants
    including backtick + whitespace) PLUS lower-casing.

    This catches more than pure case differences: e.g. "Duncan D'Alessandro"
    (apostrophe) and "Duncan D`Alessandro" (backtick) get grouped together,
    since the new normalize_name maps backtick → ASCII apostrophe. Older
    canonical_names in the DB were created before backtick was in the table,
    so we re-normalize them on the fly here for grouping purposes.

    Returns a list of groups; each group is a list of
    `(player_id, canonical_name, n_matches)` tuples sorted by `n_matches`
    descending — so the first element is the natural "winner" for a merge.
    Excludes already-merged records (`merged_into_id IS NOT NULL`).
    Only returns groups with 2+ members.
    """
    rows = conn.execute(
        """
        SELECT
            p.id,
            p.canonical_name,
            (
                SELECT COUNT(*)
                FROM match_sides ms
                JOIN matches m ON m.id = ms.match_id
                WHERE (ms.player1_id = p.id OR ms.player2_id = p.id)
                  AND m.superseded_by_run_id IS NULL
            ) AS n_matches
        FROM players p
        WHERE p.merged_into_id IS NULL
        """
    ).fetchall()

    groups: dict[str, list[tuple[int, str, int]]] = {}
    for pid, name, n_matches in rows:
        # Re-normalize using current rules + lowercase to find equivalents.
        # Stored canonical_names predate any normalize_name updates.
        key = normalize_name(name).lower()
        groups.setdefault(key, []).append((pid, name, n_matches))

    # Sort each group by n_matches DESC (winner first), then by id for stability
    for g in groups.values():
        g.sort(key=lambda t: (-t[2], t[0]))

    return [g for g in groups.values() if len(g) > 1]


def merge_player_into(
    conn: sqlite3.Connection,
    loser_id: int,
    winner_id: int,
    *,
    reason: str = "case-only duplicate auto-merge",
) -> None:
    """Merge `loser_id` into `winner_id`.

    All references in `match_sides` (player1_id and player2_id) are redirected
    to the winner. Aliases are moved (with INSERT OR IGNORE to handle UNIQUE
    collisions). Stale ratings + rating_history rows for the loser are
    deleted (the next `rate` recomputes against the merged data). The loser's
    `players` row is preserved with `merged_into_id` set — never deleted —
    so the audit trail and `player_aliases` chain remain reconstructable.

    One `audit_log` row is written per merge with action `player.merged` and
    a JSON payload recording the before/after.
    """
    if loser_id == winner_id:
        raise ValueError("cannot merge a player into itself")

    import json

    with conn:
        # Capture the before-state for audit
        loser_row = conn.execute(
            "SELECT id, canonical_name, merged_into_id FROM players WHERE id = ?",
            (loser_id,),
        ).fetchone()
        winner_row = conn.execute(
            "SELECT id, canonical_name FROM players WHERE id = ?", (winner_id,)
        ).fetchone()
        if loser_row is None or winner_row is None:
            raise ValueError(f"unknown player id: loser={loser_id} winner={winner_id}")
        if loser_row[2] is not None:
            # Already merged — idempotent no-op
            return

        # Redirect match_sides references
        conn.execute(
            "UPDATE match_sides SET player1_id = ? WHERE player1_id = ?",
            (winner_id, loser_id),
        )
        conn.execute(
            "UPDATE match_sides SET player2_id = ? WHERE player2_id = ?",
            (winner_id, loser_id),
        )

        # Move aliases — INSERT OR IGNORE handles the UNIQUE(player_id, raw_name)
        # case (same raw_name on both records is just deduped)
        conn.execute(
            """
            INSERT OR IGNORE INTO player_aliases (player_id, raw_name, source_file_id, first_seen_at)
            SELECT ?, raw_name, source_file_id, first_seen_at
            FROM player_aliases
            WHERE player_id = ?
            """,
            (winner_id, loser_id),
        )
        conn.execute(
            "DELETE FROM player_aliases WHERE player_id = ?", (loser_id,)
        )

        # Wipe loser's stale ratings — next `rate` will recompute
        conn.execute("DELETE FROM ratings WHERE player_id = ?", (loser_id,))
        conn.execute(
            "DELETE FROM rating_history WHERE player_id = ?", (loser_id,)
        )

        # Mark merged (preserves the row + provenance)
        conn.execute(
            "UPDATE players SET merged_into_id = ? WHERE id = ?",
            (winner_id, loser_id),
        )

        # Audit log
        conn.execute(
            """
            INSERT INTO audit_log (action, entity_type, entity_id, before_jsonb, after_jsonb)
            VALUES (?, 'players', ?, ?, ?)
            """,
            (
                "player.merged",
                loser_id,
                json.dumps({"id": loser_id, "canonical_name": loser_row[1]}),
                json.dumps(
                    {
                        "merged_into_id": winner_id,
                        "winner_canonical_name": winner_row[1],
                        "reason": reason,
                    }
                ),
            ),
        )


def merge_case_duplicates(
    conn: sqlite3.Connection,
) -> list[tuple[str, list[str]]]:
    """Find and merge all case-only duplicate player records.

    For each group of players with case-insensitive identical names, the
    one with most matches becomes the winner; the others are merged into
    it via `merge_player_into`.

    Returns a list of `(winner_name, [loser_names])` for reporting.
    Caller should run `rate` afterward to recompute ratings against the
    merged data.
    """
    groups = find_case_duplicate_groups(conn)
    merged: list[tuple[str, list[str]]] = []
    for group in groups:
        # Group already sorted by n_matches DESC; first is winner
        winner_id, winner_name, _ = group[0]
        loser_names: list[str] = []
        for loser_id, loser_name, _ in group[1:]:
            merge_player_into(
                conn, loser_id, winner_id,
                reason=f"case-only duplicate of '{winner_name}'",
            )
            loser_names.append(loser_name)
        merged.append((winner_name, loser_names))
    return merged
