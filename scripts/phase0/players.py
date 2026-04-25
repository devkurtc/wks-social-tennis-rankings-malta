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
_APOSTROPHE_TABLE = str.maketrans({c: "'" for c in "‘’ʼʻ‛"})

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
