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

        # Snapshot the (match_id, side, slot) triples the loser owned BEFORE
        # we redirect them. `unmerge_player` reads this to reverse cleanly.
        loser_sides_rows = conn.execute(
            "SELECT match_id, side, "
            "  CASE WHEN player1_id = ? THEN 'p1' ELSE 'p2' END AS slot "
            "FROM match_sides "
            "WHERE player1_id = ? OR player2_id = ?",
            (loser_id, loser_id, loser_id),
        ).fetchall()
        match_sides_snapshot = [
            {"match_id": mid, "side": sd, "slot": slot}
            for (mid, sd, slot) in loser_sides_rows
        ]

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
                json.dumps({
                    "id": loser_id,
                    "canonical_name": loser_row[1],
                    "match_sides": match_sides_snapshot,
                }),
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


# ---- Token-order-insensitive duplicate detection ----
#
# Catches "Leanne Schembri" / "SCHEMBRI LEANNE" / "Schembri Leanne" all
# as one player. The fingerprint is `sorted(tokens.lower())` joined by
# spaces — invariant to case AND word order.
#
# This is more aggressive than the case-only merger: e.g. theoretical
# false positives like "Robert Lee" vs "Lee Robert" (which are the same
# person 99.9% of the time anyway in this domain). For two-name pairs,
# in a Maltese tennis context, swapped tokens are essentially always the
# same person (Excel data-entry order varies by file).
#
# Only matches when token *count* is identical: "Robert Smith" and
# "Robert John Smith" produce different fingerprints — so we don't
# accidentally collapse a 2-token name into an unrelated 3-token name.


def _token_fingerprint(name: str) -> str:
    """Return a token-order-insensitive fingerprint for a name."""
    norm = normalize_name(name).lower()
    tokens = sorted(t for t in norm.split() if t)
    return " ".join(tokens)


def find_token_duplicate_groups(
    conn: sqlite3.Connection,
) -> list[list[tuple[int, str, int]]]:
    """Find groups of players whose names match modulo case AND token order.

    Same return shape as `find_case_duplicate_groups`: a list of groups,
    each a list of `(player_id, canonical_name, n_matches)` tuples sorted
    by n_matches DESC. Excludes already-merged players. Only returns
    groups with 2+ members.
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
        key = _token_fingerprint(name)
        if not key:
            continue
        groups.setdefault(key, []).append((pid, name, n_matches))

    for g in groups.values():
        g.sort(key=lambda t: (-t[2], t[0]))

    return [g for g in groups.values() if len(g) > 1]


def _pick_canonical_display(group: list[tuple[int, str, int]]) -> int:
    """Within a token-equivalent group, choose which row's canonical_name
    becomes the winner's *display* name. Heuristics, in order:
       1. Prefer a non-ALL-CAPS form (e.g. 'Leanne Schembri' over 'SCHEMBRI LEANNE').
       2. Prefer the form with the most matches (already encoded in sort order).
    Returns the index in `group` of the chosen display row.
    The actual winner_id (where matches/aliases get redirected) is always
    group[0] — we just possibly rename it to a nicer display form.
    """
    for i, (_, name, _) in enumerate(group):
        if not name.isupper():
            return i
    return 0  # all upper-case, keep most-matches one


def merge_token_duplicates(
    conn: sqlite3.Connection,
    *,
    dry_run: bool = False,
) -> list[dict]:
    """Find and merge all token-order-insensitive duplicate player records.

    Winner selection prioritises the *prettier* display name (non-ALL-CAPS,
    Surname-Last form) so the surviving record looks right in the UI.
    Match counts and aliases are merged regardless of which row wins.

    If `dry_run=True`, returns the proposed merges without modifying the DB.

    Each result entry:
        {
            "winner_id": int,
            "winner_name": str,
            "winner_n_matches": int,
            "losers": [{"id": int, "name": str, "n_matches": int}, ...]
        }
    Caller should run `rate` afterward to recompute ratings.
    """
    groups = find_token_duplicate_groups(conn)
    out: list[dict] = []

    for group in groups:
        # Pick the prettiest display row as the winner; everyone else is a loser.
        # Tie-breaker preference order: non-CAPS > most-matches > lowest id (stable).
        def _winner_key(item):
            _pid, name, n = item
            return (
                0 if not name.isupper() else 1,  # non-CAPS first
                -n,                               # more matches first
                _pid,                             # stable
            )

        sorted_group = sorted(group, key=_winner_key)
        winner_id, winner_name, winner_n = sorted_group[0]
        losers = sorted_group[1:]

        losers_info = []
        for loser_id, loser_name, loser_n in losers:
            losers_info.append(
                {"id": loser_id, "name": loser_name, "n_matches": loser_n}
            )
            if not dry_run:
                merge_player_into(
                    conn, loser_id, winner_id,
                    reason=f"token-equivalent of '{winner_name}'",
                )

        out.append({
            "winner_id": winner_id,
            "winner_name": winner_name,
            "winner_n_matches": winner_n,
            "losers": losers_info,
        })

    # Now drop the helper that was only used by the previous winner-rename
    # path (no longer needed but kept above for any future caller).
    return out


# ---- Typo auto-merger ----
#
# Catches the dominant pattern in the real data: an established player (10s of
# matches, captain-assigned class) plus a "ghost" record with 1-2 matches whose
# canonical name differs by a single character (Excel typo, missing letter,
# transposition). Adding hundreds of these to manual_aliases.json doesn't
# scale; the rules below auto-merge them safely.
#
# Discriminator vs same-first-name-different-surname false positives
# (e.g. "Christine Schembri" vs "Christine Scerri" — different people):
# the typo signal requires `abs(len_diff) <= 1` on token-sorted fingerprints
# AND ratio >= 0.95. Two distinct surnames diverging by 4+ characters fail
# that gate, so the auto-merger leaves them for the human suggester.


def _is_typo_pair(name_a: str, name_b: str) -> bool:
    """Return True if two names look like a 1-char edit of each other
    (insertion, deletion, substitution, or transposition).

    Compares lowercased+whitespace-collapsed *raw* names — NOT token-sorted
    fingerprints — because sorting destroys positional character similarity.
    Example: 'Clayton Zammit Cesare' vs 'Calyton Zammit Cesare' is an obvious
    1-char typo on the raw names, but sorting the tokens moves 'calyton' to
    position 0 and 'clayton' to position 1, which makes SequenceMatcher
    treat them as much less similar.

    Token-order variants of the SAME person (e.g. 'Borg Reuben' vs
    'Reuben Borg') are handled separately by `merge_token_duplicates` —
    the typo gate doesn't need to cover them.

    This is the same gate used by `_confidence` for the "token-fp
    ~1-char-edit" boost (kept under that name for backward-compatible
    reasoning labels) and by `merge_typo_duplicates` for auto-merging.
    Keeping a single definition prevents the suggester and merger from
    drifting out of sync.
    """
    import difflib
    a = " ".join(name_a.lower().split())
    b = " ".join(name_b.lower().split())
    if abs(len(a) - len(b)) > 1:
        return False
    # Min length 9 (the shorter of the two). Below this, one differing char
    # is too large a fraction of the name to discriminate typos from genuine
    # different names. Real Maltese names mostly exceed 9 chars.
    if len(a) < 9 or len(b) < 9:
        return False
    # Threshold 0.92: empirically separates genuine typos (>= 0.94 in our
    # data) from same-first-name-different-surname false positives
    # (Christine Schembri vs Scerri = 0.88, Mike vs Mark Smith = 0.80).
    # The "Jon Smith" vs "John Smith" 0.95 nickname case is rare enough
    # in this domain that auto-merging is more often right than wrong;
    # the additional gates (shared club + lopsided n + same gender)
    # keep the false-positive surface small.
    sm = difflib.SequenceMatcher(None, a, b)
    return sm.ratio() >= 0.92


def find_typo_duplicate_groups(
    conn: sqlite3.Connection,
    *,
    min_winner_matches: int = 4,
    max_loser_matches: int = 2,
) -> list[dict]:
    """Find lopsided typo pairs that are safe to auto-merge.

    Lopsided: one record has >= `min_winner_matches` matches, the other has
    <= `max_loser_matches`. Captures the "established player + ghost typo
    record" pattern. Two real players who happen to share a near-identical
    name (both with 5+ matches each) are NOT auto-merged — they go through
    `suggest_fuzzy_matches` for human review.

    Each result entry:
        {
            "winner": {"id", "name", "n", "gender", "clubs", "latest_class"},
            "loser":  {"id", "name", "n", "gender", "clubs", "latest_class"},
            "reason": str,
        }
    """
    rows = conn.execute(
        """
        SELECT
            p.id, p.canonical_name, p.gender,
            (SELECT COUNT(*) FROM match_sides ms
             JOIN matches m ON m.id = ms.match_id
             WHERE (ms.player1_id = p.id OR ms.player2_id = p.id)
               AND m.superseded_by_run_id IS NULL) AS n,
            (SELECT GROUP_CONCAT(DISTINCT c.slug)
             FROM match_sides ms
             JOIN matches m ON m.id = ms.match_id
             JOIN tournaments t ON t.id = m.tournament_id
             JOIN clubs c ON c.id = t.club_id
             WHERE (ms.player1_id = p.id OR ms.player2_id = p.id)
               AND m.superseded_by_run_id IS NULL) AS clubs,
            (SELECT pta.class_label
             FROM player_team_assignments pta
             JOIN tournaments t ON t.id = pta.tournament_id
             WHERE pta.player_id = p.id
             ORDER BY t.year DESC, t.id DESC LIMIT 1) AS latest_class
        FROM players p
        WHERE p.merged_into_id IS NULL
        """
    ).fetchall()

    # Pre-compute fingerprints + first letter for fast filtering
    enriched = []
    for pid, name, gender, n, clubs, latest_class in rows:
        fp = _token_fingerprint(name)
        if not fp:
            continue
        enriched.append({
            "id": pid, "name": name, "gender": gender,
            "n": n or 0, "clubs": clubs or "",
            "latest_class": latest_class or "",
            "_fp": fp,
            "_first": name[:1].lower(),
            "_token_count": len(fp.split()),
        })

    pairs: list[dict] = []
    seen_loser_ids: set[int] = set()
    n_players = len(enriched)
    for i in range(n_players):
        a = enriched[i]
        for j in range(i + 1, n_players):
            b = enriched[j]
            # Cheap prefilters
            if a["_first"] != b["_first"]:
                continue
            if a["_token_count"] != b["_token_count"]:
                continue
            # Same gender required (or one unknown — captures unattributed ghosts)
            if a["gender"] and b["gender"] and a["gender"] != b["gender"]:
                continue
            # Shared club — guard against cross-club homonyms
            a_clubs = set((a["clubs"] or "").split(",")) - {""}
            b_clubs = set((b["clubs"] or "").split(",")) - {""}
            if not (a_clubs & b_clubs):
                continue
            # Typo gate (the actual discriminator). Compares raw names —
            # see _is_typo_pair docstring for why sorted fingerprints are
            # the wrong input here.
            if not _is_typo_pair(a["name"], b["name"]):
                continue
            # Lopsidedness: one established, one ghost
            n_max = max(a["n"], b["n"])
            n_min = min(a["n"], b["n"])
            if n_max < min_winner_matches or n_min > max_loser_matches:
                continue
            # Pick winner: the higher-N record. Tie-break: non-CAPS, then lowest id.
            def _sort_key(p):
                return (-p["n"], 1 if p["name"].isupper() else 0, p["id"])
            winner, loser = sorted([a, b], key=_sort_key)[:2]
            if loser["id"] in seen_loser_ids:
                # A ghost shouldn't be merged into two different winners.
                # If it could match multiple, the human suggester should sort it.
                continue
            seen_loser_ids.add(loser["id"])
            pairs.append({
                "winner": {k: v for k, v in winner.items() if not k.startswith("_")},
                "loser":  {k: v for k, v in loser.items() if not k.startswith("_")},
                "reason": (
                    f"typo auto-merge: {loser['name']!r} ({loser['n']}m) "
                    f"≈ {winner['name']!r} ({winner['n']}m), shared club"
                ),
            })

    return pairs


def merge_typo_duplicates(
    conn: sqlite3.Connection,
    *,
    dry_run: bool = False,
    min_winner_matches: int = 4,
    max_loser_matches: int = 2,
) -> list[dict]:
    """Auto-merge lopsided typo pairs (see find_typo_duplicate_groups).

    Returns the list of pairs (with a `merged: bool` field added to each).
    Caller should run `rate` afterward to recompute ratings.
    """
    pairs = find_typo_duplicate_groups(
        conn,
        min_winner_matches=min_winner_matches,
        max_loser_matches=max_loser_matches,
    )
    for p in pairs:
        if not dry_run:
            merge_player_into(
                conn,
                loser_id=p["loser"]["id"],
                winner_id=p["winner"]["id"],
                reason=p["reason"],
            )
            p["merged"] = True
        else:
            p["merged"] = False
    return pairs


# ---- Manual-alias merges ----
#
# For cases automated rules cannot catch: marriage surname changes,
# nicknames, deliberate aliases. Driven by a JSON file so the list is
# durable, reviewable, and survives DB rebuilds.


def _resolve_player_id(conn: sqlite3.Connection, name: str) -> tuple[int, str] | None:
    """Look up a player by canonical_name (exact match), then follow the
    merge chain to the surviving record. Returns (id, name) of the surviving
    record or None if not found.
    """
    row = conn.execute(
        "SELECT id, canonical_name, merged_into_id FROM players "
        "WHERE canonical_name = ?",
        (name,),
    ).fetchone()
    if row is None:
        return None
    pid, n, merged_into = row
    seen = {pid}
    while merged_into is not None and merged_into not in seen:
        seen.add(merged_into)
        nxt = conn.execute(
            "SELECT id, canonical_name, merged_into_id FROM players WHERE id = ?",
            (merged_into,),
        ).fetchone()
        if nxt is None:
            break
        pid, n, merged_into = nxt
    return (pid, n)


def _confidence(
    a: dict, b: dict, raw_score: float
) -> tuple[float, list[str]]:
    """Combine raw string similarity with structured signals to produce a
    'this is the same person' confidence in [0..1]. Returns (confidence, reasons).

    Signals:
      + raw string similarity (gestalt ratio from difflib) — base.
      + same first character of canonical name (anchors first-name).
      + same token count (rules out 'Robert Smith' vs 'Robert John Smith').
      + same gender when both known.
      + shared club presence (overlap in any of the comma-separated club slugs).
      + Levenshtein-1 between sorted-token fingerprints (catches 1-char typo).
      − different first character (suggests different first name).
      − both have many active matches (>30 each) — both look 'real' & distinct.
    """
    reasons: list[str] = []
    score = raw_score
    a_key = a["_key"]
    b_key = b["_key"]
    a_tok = a["_token_fp"].split()
    b_tok = b["_token_fp"].split()

    # Boosts are intentionally small so the *raw similarity* dominates.
    # Total positive boost ceiling is ~0.10 — enough to lift a strong typo
    # match (raw 0.92) into VERY HIGH, but not enough to hide a mediocre
    # raw match (0.85 with all boosts → 0.95, still HIGH not VERY HIGH).
    # Penalties are larger because they encode "this is probably not the
    # same person" — different first letter or no signal overlap.

    # First character anchor
    if a_key and b_key:
        if a_key[0] == b_key[0]:
            score += 0.02
            reasons.append("first-letter match")
        else:
            score -= 0.15
            reasons.append("first-letter differs")

    # Token-count parity
    if len(a_tok) == len(b_tok):
        score += 0.02
        reasons.append(f"token-count match ({len(a_tok)})")
    else:
        score -= 0.05
        reasons.append("token-count differs")

    # Gender
    ga, gb = a.get("gender"), b.get("gender")
    if ga and gb and ga == gb:
        score += 0.02
        reasons.append(f"gender match ({ga})")
    elif ga and gb and ga != gb:
        # Should already be filtered out upstream when same_gender_only=True
        score -= 0.20
        reasons.append("gender differs")

    # Club overlap
    a_clubs = set((a.get("clubs") or "").split(",")) - {""}
    b_clubs = set((b.get("clubs") or "").split(",")) - {""}
    if a_clubs and b_clubs and (a_clubs & b_clubs):
        score += 0.02
        reasons.append(
            f"shared club ({','.join(sorted(a_clubs & b_clubs))})"
        )

    # Single-character edit on raw lowercased names (catches typos
    # like 'Lillian Badacchino' / 'Lillian Baldacchino'). Uses the same
    # gate as the typo auto-merger so the two stay in sync.
    if _is_typo_pair(a["name"], b["name"]):
        score += 0.04
        reasons.append("token-fp ~1-char-edit")

    # Both look 'real' (lots of matches each) — penalise as collision risk.
    # Two players with 30+ matches each are much less likely to be a typo
    # than a 30-match player + a 3-match ghost record.
    n_a = a.get("n", 0)
    n_b = b.get("n", 0)
    if n_a >= 30 and n_b >= 30:
        score -= 0.08
        reasons.append("both have 30+ matches (less typo-like)")

    # Both have a captain-assigned class from a recent tournament. That's a
    # strong "both records are real, distinct people" signal — captains pick
    # rosters by hand, so a ghost typo record almost never carries a class
    # assignment. If the classes are *different* divisions that's the
    # strongest evidence yet that they're separate players (e.g. Christine
    # Schembri A1 vs Christine Scerri C3). If the classes match, milder
    # penalty — they might still be the same person across two tournaments.
    cls_a = (a.get("latest_class") or "").strip()
    cls_b = (b.get("latest_class") or "").strip()
    if cls_a and cls_b:
        if cls_a == cls_b:
            score -= 0.04
            reasons.append(f"both class-assigned ({cls_a})")
        else:
            # Strip trailing digit (A1/A2/A3 → A) to compare division-tiers.
            tier_a = cls_a.rstrip("0123456789")
            tier_b = cls_b.rstrip("0123456789")
            if tier_a and tier_b and tier_a != tier_b:
                # Different tier (A vs C) — almost certainly different people.
                score -= 0.18
                reasons.append(f"different class tiers ({cls_a} vs {cls_b})")
            else:
                score -= 0.08
                reasons.append(f"different classes ({cls_a} vs {cls_b})")

    # Lopsided n is a typo signal (one ghost, one established) — boost slightly
    # so genuine typos rank above same-n ambiguous cases at the same raw score.
    if min(n_a, n_b) <= 2 and max(n_a, n_b) >= 10:
        score += 0.02
        reasons.append("lopsided n (ghost+established)")

    # Bound and round
    score = max(0.0, min(1.0, score))
    return round(score, 3), reasons


def load_known_distinct(path: str) -> set[frozenset[str]]:
    """Load the 'these are different people' pair set from JSON.

    Returns a set of frozensets of two canonical names. Order doesn't matter
    (frozenset equality is order-insensitive). Missing file → empty set.
    Used by `suggest_fuzzy_matches` to filter out pairs a human has already
    ruled on.
    """
    import json
    import os
    if not os.path.exists(path):
        return set()
    with open(path, "r", encoding="utf-8") as f:
        # Don't catch JSONDecodeError — silently swallowing means the
        # suggester quietly stops respecting the file, which is worse than
        # a loud failure.
        data = json.loads(f.read())
    out: set[frozenset[str]] = set()
    for entry in data.get("pairs", []):
        a, b = entry.get("a"), entry.get("b")
        if a and b:
            out.add(frozenset({a, b}))
    return out


def record_distinct(
    path: str,
    a_name: str,
    b_name: str,
    reason: str,
) -> bool:
    """Append a 'these are different people' verdict to the known-distinct
    JSON file. Returns True if newly added, False if the pair was already
    recorded. Idempotent — safe to call repeatedly.
    """
    import json
    import os
    from datetime import datetime, timezone

    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.loads(f.read())
    else:
        data = {"pairs": []}
    pairs = data.setdefault("pairs", [])

    target = frozenset({a_name, b_name})
    for existing in pairs:
        if frozenset({existing.get("a", ""), existing.get("b", "")}) == target:
            return False  # already recorded — no-op

    pairs.append({
        "a": a_name,
        "b": b_name,
        "reason": reason,
        "decided_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    # Atomic write: tmpfile + rename, so a crashed process can't truncate
    # the JSON mid-write.
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, indent=2, ensure_ascii=False))
        f.write("\n")
    os.replace(tmp, path)
    return True


def record_same_person(
    aliases_path: str,
    winner_name: str,
    loser_name: str,
    reason: str,
) -> bool:
    """Append a 'same person' verdict to manual_aliases.json — adds the
    loser to the appropriate winner's `losers` list, creating a new merge
    entry if the winner doesn't appear yet. Returns True if anything new
    was written, False if the loser was already recorded under that winner.
    Idempotent.
    """
    import json
    import os

    if os.path.exists(aliases_path):
        with open(aliases_path, "r", encoding="utf-8") as f:
            data = json.loads(f.read())
    else:
        data = {"merges": []}
    merges = data.setdefault("merges", [])

    # Find existing merge entry for this winner (by exact canonical match).
    target = None
    for m in merges:
        if m.get("winner") == winner_name:
            target = m
            break

    if target is None:
        merges.append({
            "winner": winner_name,
            "losers": [loser_name],
            "reason": reason,
        })
        new_write = True
    else:
        losers = target.setdefault("losers", [])
        if loser_name in losers:
            return False
        losers.append(loser_name)
        # Don't overwrite an existing reason silently; append the new one if
        # it's different so the audit trail is complete.
        existing_reason = target.get("reason", "")
        if reason and reason not in existing_reason:
            target["reason"] = (existing_reason + "; " + reason).lstrip("; ")
        new_write = True

    tmp = aliases_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, indent=2, ensure_ascii=False))
        f.write("\n")
    os.replace(tmp, aliases_path)
    return new_write


def suggest_fuzzy_matches(
    conn: sqlite3.Connection,
    *,
    threshold: float = 0.85,
    same_gender_only: bool = True,
    min_matches: int = 1,
    known_distinct: set[frozenset[str]] | None = None,
    deferred: set[frozenset[str]] | None = None,
) -> list[dict]:
    """Surface plausible same-person pairs that automated rules missed.

    Heuristics:
      - difflib.SequenceMatcher ratio >= `threshold` on the lower-cased,
        whitespace-collapsed canonical names (so case + whitespace +
        token order don't dominate the signal). Token-equivalent pairs
        are excluded — those are caught by `find_token_duplicate_groups`.
      - When `same_gender_only=True`, both records must share gender
        (or one must be NULL) — avoids cross-gender false positives.
      - Both must have >= `min_matches` active matches.
      - Excludes already-merged records.
      - Excludes pairs where one is a subset of the other only because
        of token count (e.g. 'Robert Smith' vs 'Robert John Smith') —
        these need human judgement, not a fuzzy threshold.

    Returns a list of dicts, ordered by similarity DESC then total
    matches DESC. Each entry:
        {
            "score": float,           # similarity 0..1
            "a": {id, name, gender, n, last_played, latest_class, clubs},
            "b": {id, name, gender, n, last_played, latest_class, clubs},
        }
    """
    import difflib

    rows = conn.execute(
        """
        SELECT
            p.id, p.canonical_name, p.gender,
            (SELECT COUNT(*) FROM match_sides ms
             JOIN matches m ON m.id = ms.match_id
             WHERE (ms.player1_id = p.id OR ms.player2_id = p.id)
               AND m.superseded_by_run_id IS NULL) AS n,
            (SELECT MAX(m.played_on) FROM match_sides ms
             JOIN matches m ON m.id = ms.match_id
             WHERE (ms.player1_id = p.id OR ms.player2_id = p.id)
               AND m.superseded_by_run_id IS NULL) AS last_played,
            (SELECT pta.class_label
             FROM player_team_assignments pta
             JOIN tournaments t ON t.id = pta.tournament_id
             WHERE pta.player_id = p.id
             ORDER BY t.year DESC, t.id DESC LIMIT 1) AS latest_class,
            (SELECT GROUP_CONCAT(DISTINCT c.slug)
             FROM match_sides ms
             JOIN matches m ON m.id = ms.match_id
             JOIN tournaments t ON t.id = m.tournament_id
             JOIN clubs c ON c.id = t.club_id
             WHERE (ms.player1_id = p.id OR ms.player2_id = p.id)
               AND m.superseded_by_run_id IS NULL) AS clubs
        FROM players p
        WHERE p.merged_into_id IS NULL
        """
    ).fetchall()

    # Build a list of player dicts, keep only those with enough matches
    players_list = []
    for pid, name, gender, n, last_played, latest_class, clubs in rows:
        n = n or 0
        if n < min_matches:
            continue
        players_list.append({
            "id": pid, "name": name, "gender": gender,
            "n": n, "last_played": last_played or "",
            "latest_class": latest_class or "",
            "clubs": clubs or "",
            # Pre-computed key for faster comparison
            "_key": " ".join(name.lower().split()),
            "_token_fp": _token_fingerprint(name),
            "_first": name[:1].lower(),
        })

    suggestions: list[dict] = []
    known_distinct = known_distinct or set()
    deferred = deferred or set()
    n_players = len(players_list)
    for i in range(n_players):
        a = players_list[i]
        for j in range(i + 1, n_players):
            b = players_list[j]
            pair_key = frozenset({a["name"], b["name"]})
            # Filter pairs a human has already ruled "different people"
            # OR temporarily deferred via "don't know".
            if pair_key in known_distinct or pair_key in deferred:
                continue
            # Cheap prefilters
            if abs(len(a["_key"]) - len(b["_key"])) > 8:
                continue
            if a["_first"] and b["_first"] and a["_first"] != b["_first"]:
                # Different first letter => unlikely same person, but allow
                # the case where surname-first variants slip through
                # (since we already collapsed those via tokens above).
                # Skip for speed — token-fingerprint catches all such cases.
                pass
            if a["_token_fp"] == b["_token_fp"]:
                continue  # already a token-dup; not a fuzzy case
            if same_gender_only:
                ga, gb = a["gender"], b["gender"]
                if ga and gb and ga != gb:
                    continue
            score = difflib.SequenceMatcher(None, a["_key"], b["_key"]).ratio()
            if score < threshold:
                continue
            confidence, reasons = _confidence(a, b, score)
            suggestions.append({
                "score": score,
                "confidence": confidence,
                "reasons": reasons,
                "a": {k: v for k, v in a.items() if not k.startswith("_")},
                "b": {k: v for k, v in b.items() if not k.startswith("_")},
            })

    # Sort by confidence first (the user-facing trust signal), then by raw
    # similarity, then by combined match count (high-traffic pairs first).
    suggestions.sort(
        key=lambda s: (
            -s["confidence"],
            -s["score"],
            -(s["a"]["n"] + s["b"]["n"]),
        )
    )
    return suggestions


def apply_manual_aliases(
    conn: sqlite3.Connection,
    aliases_path: str,
    *,
    dry_run: bool = False,
) -> tuple[list[dict], list[str]]:
    """Apply manual same-person merges from a JSON file.

    Returns (applied, warnings):
        applied: [{winner_name, winner_id, losers: [{name, id, status}]}]
            status is one of: 'merged', 'already-merged', 'self', 'not-found'
        warnings: human-readable warning strings (e.g. unknown winner)
    """
    import json

    with open(aliases_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    applied: list[dict] = []
    warnings: list[str] = []

    for entry in data.get("merges", []):
        winner_name = entry["winner"]
        loser_names = entry.get("losers", [])
        reason = entry.get("reason", "manual alias")

        winner = _resolve_player_id(conn, winner_name)
        if winner is None:
            warnings.append(
                f"winner {winner_name!r} not found in players — entry skipped"
            )
            continue
        winner_id, winner_resolved = winner

        loser_results = []
        for ln in loser_names:
            loser = _resolve_player_id(conn, ln)
            if loser is None:
                loser_results.append({"name": ln, "id": None, "status": "not-found"})
                continue
            loser_id, _ = loser
            if loser_id == winner_id:
                loser_results.append(
                    {"name": ln, "id": loser_id, "status": "already-merged"}
                )
                continue
            if not dry_run:
                merge_player_into(
                    conn, loser_id, winner_id,
                    reason=f"manual alias: {reason}",
                )
            loser_results.append({"name": ln, "id": loser_id, "status": "merged"})

        applied.append({
            "winner_name": winner_resolved,
            "winner_id": winner_id,
            "losers": loser_results,
        })

    return applied, warnings


# ---- Defer ("Don't know") + de-merge helpers (T-P0.5-018) ----


def _atomic_write_json(path: str, data) -> None:
    """Tmpfile + rename. Avoids truncating the JSON if the process dies
    mid-write."""
    import json as _json
    import os as _os
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(_json.dumps(data, indent=2, ensure_ascii=False))
        f.write("\n")
    _os.replace(tmp, path)


def load_active_defers(path: str, *, now_iso: str | None = None) -> set[frozenset[str]]:
    """Load 'don't know — revisit later' deferrals from JSON.

    Pairs whose `revisit_after` is in the future are returned as frozensets
    (order-insensitive). Expired deferrals are filtered out so they re-surface
    in the queue automatically. Missing file → empty set.
    """
    import json as _json
    import os as _os
    from datetime import datetime as _dt, timezone as _tz

    if not _os.path.exists(path):
        return set()
    with open(path, "r", encoding="utf-8") as f:
        data = _json.loads(f.read())
    if now_iso is None:
        now_iso = _dt.now(_tz.utc).isoformat(timespec="seconds")
    out: set[frozenset[str]] = set()
    for entry in data.get("pairs", []) or []:
        a, b = entry.get("a"), entry.get("b")
        revisit_after = entry.get("revisit_after", "")
        if a and b and revisit_after > now_iso:
            out.add(frozenset({a, b}))
    return out


def record_defer(
    path: str,
    a_name: str,
    b_name: str,
    *,
    days: int = 14,
    reason: str = "",
) -> bool:
    """Record a 'don't know' verdict — defer the pair for `days` days.

    Re-deferring an existing pair refreshes the timestamp rather than
    appending a duplicate. Returns True if anything changed."""
    import json as _json
    import os as _os
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz

    if _os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            data = _json.loads(f.read())
    else:
        data = {"pairs": []}
    pairs = data.setdefault("pairs", [])

    target = frozenset({a_name, b_name})
    now = _dt.now(_tz.utc)
    revisit = (now + _td(days=days)).isoformat(timespec="seconds")

    for existing in pairs:
        if frozenset({existing.get("a", ""), existing.get("b", "")}) == target:
            existing["revisit_after"] = revisit
            if reason:
                existing["reason"] = reason
            existing["deferred_at"] = now.isoformat(timespec="seconds")
            _atomic_write_json(path, data)
            return True

    pairs.append({
        "a": a_name,
        "b": b_name,
        "reason": reason or "Deferred for review",
        "deferred_at": now.isoformat(timespec="seconds"),
        "revisit_after": revisit,
    })
    _atomic_write_json(path, data)
    return True


def unmerge_player(
    conn: sqlite3.Connection,
    audit_log_id: int,
    *,
    reason: str = "manual de-merge via review UI",
) -> dict:
    """Reverse a single `player.merged` audit entry.

    Restores `merged_into_id = NULL` and redirects each match_side back to
    the loser using the snapshot in `before_jsonb.match_sides`. Audit
    entries written before the snapshot field was added are flagged
    `legacy: True` — those clear merged_into_id but leave match_sides on
    the winner. Writes a new `player.unmerged` audit entry.
    """
    import json as _json

    row = conn.execute(
        "SELECT entity_id, before_jsonb, after_jsonb FROM audit_log "
        "WHERE id = ? AND action = 'player.merged' AND entity_type = 'players'",
        (audit_log_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"no player.merged audit entry with id={audit_log_id}")
    loser_id, before_json, after_json = row
    before = _json.loads(before_json or "{}")
    after = _json.loads(after_json or "{}")
    winner_id = after.get("merged_into_id")
    if winner_id is None:
        raise ValueError(
            f"audit entry id={audit_log_id} has no merged_into_id in after_jsonb"
        )

    sides = before.get("match_sides", [])
    legacy = "match_sides" not in before

    with conn:
        cur_row = conn.execute(
            "SELECT merged_into_id, canonical_name FROM players WHERE id = ?",
            (loser_id,),
        ).fetchone()
        if cur_row is None:
            raise ValueError(f"loser id={loser_id} no longer in players table")
        cur_merged_into, loser_name = cur_row
        if cur_merged_into != winner_id:
            raise ValueError(
                f"loser id={loser_id} is currently merged into "
                f"{cur_merged_into}, not {winner_id} as recorded in audit "
                f"entry {audit_log_id}; refusing to unmerge"
            )

        redirected = 0
        for entry in sides:
            mid = entry.get("match_id")
            sd = entry.get("side")
            slot = entry.get("slot")
            if not (mid and sd and slot in ("p1", "p2")):
                continue
            col = "player1_id" if slot == "p1" else "player2_id"
            cur = conn.execute(
                f"UPDATE match_sides SET {col} = ? "
                f"WHERE match_id = ? AND side = ? AND {col} = ?",
                (loser_id, mid, sd, winner_id),
            )
            redirected += cur.rowcount

        conn.execute(
            "UPDATE players SET merged_into_id = NULL WHERE id = ?",
            (loser_id,),
        )
        conn.execute("DELETE FROM ratings WHERE player_id = ?", (loser_id,))
        conn.execute("DELETE FROM rating_history WHERE player_id = ?", (loser_id,))
        conn.execute("DELETE FROM ratings WHERE player_id = ?", (winner_id,))
        conn.execute("DELETE FROM rating_history WHERE player_id = ?", (winner_id,))

        winner_name = (after.get("winner_canonical_name")
                       or conn.execute(
                           "SELECT canonical_name FROM players WHERE id = ?",
                           (winner_id,),
                       ).fetchone()[0])

        conn.execute(
            """
            INSERT INTO audit_log (action, entity_type, entity_id, before_jsonb, after_jsonb)
            VALUES (?, 'players', ?, ?, ?)
            """,
            (
                "player.unmerged",
                loser_id,
                _json.dumps({
                    "merged_into_id": winner_id,
                    "winner_canonical_name": winner_name,
                    "merge_audit_id": audit_log_id,
                }),
                _json.dumps({
                    "merged_into_id": None,
                    "match_sides_redirected": redirected,
                    "legacy": legacy,
                    "reason": reason,
                }),
            ),
        )

    return {
        "loser_id": loser_id,
        "loser_name": loser_name,
        "winner_id": winner_id,
        "winner_name": winner_name,
        "match_sides_redirected": redirected,
        "legacy": legacy,
    }
