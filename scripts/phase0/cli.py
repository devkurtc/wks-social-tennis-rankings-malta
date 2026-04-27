#!/usr/bin/env python3
"""RallyRank Phase 0 — local proof-of-concept CLI.

See `scripts/phase0/README.md` for usage.
See `PLAN.md` §7 (Phase 0) and `TASKS.md` (T-P0-001..010) for context.

Subcommands print a "not implemented" message and exit non-zero until
the corresponding task lands. This is the T-P0-001 scaffold.
"""

from __future__ import annotations

import argparse
import sys


def cmd_load(args: argparse.Namespace) -> int:
    # lazy import so `--help` doesn't pay the sqlite import + schema-read cost
    import db

    if args.init_only:
        conn = db.init_db()
        try:
            n = db.table_count(conn)
        finally:
            conn.close()
        print(f"Initialized {db.DEFAULT_DB_PATH} with {n} tables.")
        return 0

    if not args.file:
        print("load: --file required (or use --init-only)", file=sys.stderr)
        return 1

    # Filename-based dispatch via a simple (substring, parser_module) registry.
    # Match by case-insensitive substring; first match wins. Phase 1 will move
    # this to a proper plugin registry.
    import os
    filename = os.path.basename(args.file).lower()
    from parsers import sports_experience_2025 as _se
    from parsers import mixed_doubles as _md
    from parsers import team_tournament as _tt
    from parsers import team_tournament_legacy as _ttl
    from parsers import wilson as _wl
    from parsers import elektra_2022 as _e22
    from parsers import tck_chosen_2024 as _tck

    DISPATCH: list[tuple[str, callable]] = [
        # Sports Experience Chosen Doubles (2024 + 2025) — same template,
        # same sheet names ('Men Div 1'..'Lad Div 3') → original parser.
        ("sports experience chosen doubles", _se.parse),
        # TCK Chosen Tournament Divisions 2024 — flat-list format
        # (DATE/TIME/COURT/DIV/TEAM/VS/TEAM/RESULTS columns). Filename has
        # the typo "TOUNAMENT" — match against that.
        ("tck chosen tounament", _tck.parse),
        # VLTC Mixed Doubles (and same-template division-RR files) — sheets
        # are 'Division 1'..'Division N'. Dynamic sub-block discovery.
        ("ess mixed tournament div and results", _md.parse),
        ("elektra mixed tournament div and results", _md.parse),
        # Elektra 2022 — cross-tab matrix variant (UNIQUE format: 'Draws and
        # Results Elektra Mixed Doubles 2022.xlsx'). Must come BEFORE the
        # generic 'elektra' substring check would fire.
        ("draws and results elektra", _e22.parse),
        # VLTC Team Tournaments (modern "Day N" template) — Antes / Tennis
        # Trade / San Michel post-2024 / Samsung Rennie Tonna. Same family.
        # IMPORTANT: list these BEFORE the legacy patterns below so the
        # modern files (e.g. "Tennis Trade Team Tournament - Results.xlsx")
        # don't get stolen by a less-specific legacy substring.
        ("antes insurance team tournament", _tt.parse),
        ("tennis trade team tournament", _tt.parse),
        ("results tennis trade team tournament", _tt.parse),
        ("san michel results", _tt.parse),
        # 2026+ Google-Sheet scraper names this file "SAN MICHEL TEAM TOURNAMENT
        # YYYY.xlsx" but the file inside is the modern Day-N layout. Add explicit
        # year prefixes here so the more general "san michel team tournament"
        # legacy match (below) doesn't steal it. Add a new line per year.
        ("san michel team tournament 2026", _tt.parse),
        ("samsung rennie tonna", _tt.parse),
        # VLTC Team Tournaments (LEGACY single-sheet "DAY" template) —
        # PKF 2023/2024, Tennis Trade 2023, San Michel 2023/2024/2025
        # (uppercase). Filename patterns are distinctive: "pkf", uppercase
        # "san michel team tournament" (the modern "san michel results"
        # pattern above already matched all 2025+ files), the legacy
        # "tennis trade  team tournament 2023" specifically (the modern
        # "tennis trade team tournament" above already matched newer ones),
        # and the bare " team tournament 2024" (San Michel 2024).
        ("pkf  team tournament", _ttl.parse),
        ("pkf team tournament", _ttl.parse),
        ("san michel team tournament", _ttl.parse),
        ("tennis trade  team tournament 2023", _ttl.parse),
        (" team tournament 2024", _ttl.parse),
        # Wilson Autumn/Spring 2017-2021 (older team-tournament format,
        # both .xls and .xlsx). Auto-handles legacy Excel via xlrd.
        ("wilson autumn results", _wl.parse),
        ("wilson spring results", _wl.parse),
        # TCK (Tennis Club Kordin) team tournaments — same modern Day-N
        # template as VLTC's Antes/Tennis Trade/etc.
        ("tck spring team tournament", _tt.parse),
        ("tck autumn team tournament", _tt.parse),
        # TCK Mixed Doubles — same flat-list shape as TCK Chosen 2024
        ("tck mixed doubles", _tck.parse),
    ]

    # Team-tournament parsers are the ones whose source files carry a
    # 'Team Selection' sheet with captain-assigned class labels. Mark them so
    # we can run extract_team_selection after the main parse succeeds.
    TEAM_TOURNAMENT_PARSERS = {_tt.parse, _ttl.parse, _wl.parse}

    parse_fn = None
    for substr, fn in DISPATCH:
        if substr in filename:
            parse_fn = fn
            break

    if parse_fn is None:
        print(
            f"load: no parser registered for {os.path.basename(args.file)!r}. "
            "Phase 0 supports Sports Experience Chosen Doubles 2024/2025, "
            "ESS / Elektra Mixed Doubles, and VLTC team-tournament (modern "
            "Day-N template — Antes 2024+, Tennis Trade 2024+, San Michel 2025+) files.",
            file=sys.stderr,
        )
        return 1

    conn = db.init_db()
    try:
        run_id = parse_fn(args.file, conn)
        # v2 multi-club: parsers hard-code VLTC; reattribute to the correct
        # club based on the file's `_DATA_/<CLUB>/...` path. Idempotent.
        club_name = _detect_club_from_path(args.file)
        if club_name and club_name != "VLTC":
            club_id = _ensure_club(conn, club_name)
            # Update source_files + tournaments for THIS run to point at the
            # correct club.
            sf_id_row = conn.execute(
                "SELECT source_file_id FROM ingestion_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if sf_id_row:
                sf_id = sf_id_row[0]
                conn.execute(
                    "UPDATE source_files SET club_id = ? WHERE id = ?",
                    (club_id, sf_id),
                )
                conn.execute(
                    "UPDATE tournaments SET club_id = ? WHERE source_file_id = ?",
                    (club_id, sf_id),
                )
                conn.commit()

        # Extract captain-assigned class labels from the 'Team Selection' sheet
        # for team-tournament files. Players (with their gender) are upserted
        # via get_or_create_player so this also fills in genders for players
        # that the match-sheet parsers couldn't infer.
        n_team_assigns = 0
        if parse_fn in TEAM_TOURNAMENT_PARSERS:
            import team_selection
            from players import get_or_create_player

            assignments = team_selection.extract_team_selection(args.file)
            if assignments:
                sf_id_row = conn.execute(
                    "SELECT source_file_id FROM ingestion_runs WHERE id = ?",
                    (run_id,),
                ).fetchone()
                t_id_row = conn.execute(
                    "SELECT id FROM tournaments WHERE source_file_id = ?",
                    (sf_id_row[0],),
                ).fetchone() if sf_id_row else None
                if sf_id_row and t_id_row:
                    n_team_assigns = team_selection.store_team_selection(
                        conn,
                        tournament_id=t_id_row[0],
                        source_file_id=sf_id_row[0],
                        assignments=assignments,
                        get_or_create_player_fn=get_or_create_player,
                    )
                    conn.commit()

        # Auto-run identity-resolution mergers so the DB doesn't accumulate
        # stale duplicates. Order matters:
        #   1. case-only (cheapest, deterministic)
        #   2. token-equivalent (catches surname-first vs first-name swaps)
        #   3. typo (lopsided 1-char-typo pairs)
        #   4. manual aliases (marriage names, nicknames — hand-curated JSON)
        # Each is idempotent. Skipped via --no-merge for diagnostic loads.
        merge_summary: list[str] = []
        if not getattr(args, "no_merge", False):
            import players as _players
            n = len(_players.merge_case_duplicates(conn))
            if n: merge_summary.append(f"{n} case")
            n = len(_players.merge_token_duplicates(conn))
            if n: merge_summary.append(f"{n} token")
            n = sum(1 for p in _players.merge_typo_duplicates(conn) if p.get("merged"))
            if n: merge_summary.append(f"{n} typo")
            # Manual aliases path resolves relative to project root, not cwd.
            from pathlib import Path as _P
            aliases_path = _P(__file__).resolve().parent / "manual_aliases.json"
            if aliases_path.exists():
                applied, _warnings = _players.apply_manual_aliases(
                    conn, str(aliases_path)
                )
                n = sum(
                    1 for r in applied for l in r["losers"]
                    if l["status"] == "merged"
                )
                if n: merge_summary.append(f"{n} manual")
    finally:
        conn.close()
    msg = f"Loaded ingestion_run_id={run_id} from {args.file}"
    if n_team_assigns:
        msg += f" (+{n_team_assigns} team assignments)"
    if merge_summary:
        msg += f"\n  auto-merged: {', '.join(merge_summary)}. Run `cli.py rate` to refresh ratings."
    print(msg)
    return 0


def _detect_club_from_path(path: str) -> str | None:
    """Infer the club from a path like `_DATA_/VLTC/foo.xlsx` → 'VLTC'."""
    import os
    parts = os.path.normpath(path).split(os.sep)
    # Walk backward from the file to find a directory that looks like a club code
    for p in reversed(parts[:-1]):
        if p == "_DATA_":
            return None  # didn't find a club subdir
        # Heuristic: club codes are SHORT all-caps tokens (e.g. VLTC, TCK, MARSA)
        if 2 <= len(p) <= 8 and p.replace("_", "").isalpha() and p.isupper():
            return p
    return None


def _ensure_club(conn, club_name: str) -> int:
    """Get-or-create a club row; return its id. Idempotent."""
    slug = club_name.lower()
    row = conn.execute(
        "SELECT id FROM clubs WHERE slug = ?", (slug,)
    ).fetchone()
    if row:
        return row[0]
    cur = conn.execute(
        "INSERT INTO clubs (name, slug) VALUES (?, ?)",
        (club_name, slug),
    )
    return cur.lastrowid


def cmd_rate(args: argparse.Namespace) -> int:
    import db
    import rating

    conn = db.init_db()
    try:
        n = rating.recompute_all(conn, model_name=rating.CHAMPION_MODEL)
    finally:
        conn.close()
    print(f"Recomputed ratings over {n} matches (model={rating.CHAMPION_MODEL}).")
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    """Show the match-by-match rating trajectory for a single player."""
    import db
    import rating

    conn = db.init_db()
    try:
        # Resolve player by canonical name
        row = conn.execute(
            "SELECT id, canonical_name, gender FROM players "
            "WHERE canonical_name = ? AND merged_into_id IS NULL",
            (args.player,),
        ).fetchone()
        if row is None:
            print(
                f"history: player {args.player!r} not found "
                f"(must match canonical_name exactly).",
                file=sys.stderr,
            )
            return 1
        player_id, canonical_name, gender = row

        # Per-match trajectory: partner, opponents, score, μ/σ before+after
        rows = conn.execute(
            """
            SELECT
                m.id, m.played_on, t.name AS tournament, m.division,
                ms.side, ms.player1_id, ms.player2_id, ms.games_won, ms.won,
                opp.player1_id, opp.player2_id, opp.games_won,
                rh.mu_after, rh.sigma_after,
                opp.won AS opp_won
            FROM rating_history rh
            JOIN matches m ON m.id = rh.match_id
            JOIN tournaments t ON t.id = m.tournament_id
            JOIN match_sides ms ON ms.match_id = m.id
                AND (ms.player1_id = ? OR ms.player2_id = ?)
            JOIN match_sides opp ON opp.match_id = m.id AND opp.side <> ms.side
            WHERE rh.player_id = ?
              AND rh.model_name = ?
              AND m.superseded_by_run_id IS NULL
            ORDER BY m.played_on, m.id
            """,
            (player_id, player_id, player_id, rating.CHAMPION_MODEL),
        ).fetchall()

        if not rows:
            print(
                f"history: no rated matches for {canonical_name!r}.",
                file=sys.stderr,
            )
            return 0

        # Resolve all player IDs to names in one pass
        all_ids = set()
        for r in rows:
            all_ids.update((r[5], r[6], r[9], r[10]))
        all_ids.discard(None)
        name_map = dict(
            conn.execute(
                f"SELECT id, canonical_name FROM players "
                f"WHERE id IN ({','.join('?' * len(all_ids))})",
                tuple(all_ids),
            ).fetchall()
        )
    finally:
        conn.close()

    def short(name: str | None, width: int = 18) -> str:
        if not name:
            return ""
        return name if len(name) <= width else name[: width - 1] + "…"

    # Apply --recent filter
    if args.recent and args.recent > 0:
        rows = rows[-args.recent:]

    # Determine starting μ for first match's "before" (if showing from match 1)
    # We use rating.division_starting_mu for the player's first division.
    # For middle slices, "before" is the previous row's after.
    first_div = rows[0][3] if rows else None
    starting_mu = rating.division_starting_mu(first_div)
    starting_sigma = 25.0 / 3  # OpenSkill default

    # Header
    print(f"\nMatch history for {canonical_name} (gender={gender or '?'}, {len(rows)} matches shown)\n")
    print(
        f"{'#':>3}  {'Date':<10}  {'Tournament':<28}  {'Rubber':<8}  "
        f"{'Partner':<18}  {'vs':2}  {'Opponents':<32}  "
        f"{'Score':<7}  {'μ before':>8} → {'μ after':>8}  "
        f"{'Δμ':>6}   {'σ':>5}→{'σ':<5}"
    )
    print("-" * 156)

    prev_mu = starting_mu
    prev_sigma = starting_sigma
    for i, r in enumerate(rows, 1):
        (match_id, date, tournament, division,
         side, p1, p2, my_games, my_won,
         opp1, opp2, opp_games,
         mu_after, sigma_after, opp_won) = r

        partner_id = p2 if p1 == player_id else p1
        partner = short(name_map.get(partner_id), 18)
        opp1_n = short(name_map.get(opp1), 14)
        opp2_n = short(name_map.get(opp2), 14)
        opponents = f"{opp1_n} + {opp2_n}"
        score = f"{my_games}-{opp_games}"
        # Tied rubbers (both won=0) are decided by games-tiebreak — same
        # convention as the rating engine. Display as "W (g)" / "L (g)" so
        # the user can see which result was a tiebreak.
        if my_won and not opp_won:
            result = "W    "
        elif opp_won and not my_won:
            result = "L    "
        elif (my_games or 0) > (opp_games or 0):
            result = "W (g)"
        else:
            result = "L (g)"
        delta_mu = mu_after - prev_mu
        delta_sigma = sigma_after - prev_sigma

        print(
            f"{i:>3}  {date:<10}  {tournament[:28]:<28}  "
            f"{(division or '?')[:8]:<8}  "
            f"{partner:<18}  vs  {opponents[:32]:<32}  "
            f"{score:<5}{result}  "
            f"{prev_mu:>8.2f} → {mu_after:>8.2f}  "
            f"{delta_mu:>+6.2f}   {prev_sigma:>5.2f}→{sigma_after:<5.2f}"
        )

        prev_mu = mu_after
        prev_sigma = sigma_after

    print()
    print(
        f"Final: μ={rows[-1][12]:.2f}  σ={rows[-1][13]:.2f}  "
        f"μ-3σ={rows[-1][12] - 3*rows[-1][13]:.2f}"
    )
    return 0


def cmd_merge_case_duplicates(args: argparse.Namespace) -> int:
    import db
    import players

    conn = db.init_db()
    try:
        merged = players.merge_case_duplicates(conn)
    finally:
        conn.close()

    if not merged:
        print("No case-only duplicate players found.")
        return 0

    n_losers = sum(len(losers) for _, losers in merged)
    print(
        f"Merged {n_losers} duplicate record(s) into {len(merged)} canonical "
        f"player(s):"
    )
    for winner, losers in merged:
        for loser in losers:
            print(f"  {loser!r}  →  {winner!r}")
    print()
    print("Run `cli.py rate` to recompute ratings against the merged data.")
    return 0


def cmd_suggest_merges(args: argparse.Namespace) -> int:
    """Surface plausible same-person fuzzy matches for human review."""
    import db
    import players
    from pathlib import Path as _P

    conn = db.init_db()
    try:
        kd_path = _P(__file__).resolve().parent / "known_distinct.json"
        kd = players.load_known_distinct(str(kd_path))
        suggestions = players.suggest_fuzzy_matches(
            conn,
            threshold=args.threshold,
            same_gender_only=not args.cross_gender,
            min_matches=args.min_matches,
            known_distinct=kd,
        )
    finally:
        conn.close()

    if not suggestions:
        print(
            f"No suggestions at threshold {args.threshold}. "
            f"Try lowering --threshold (current: {args.threshold})."
        )
        return 0

    if args.limit and args.limit > 0:
        suggestions = suggestions[: args.limit]

    base = args.base_url.rstrip("/")

    # Bucket by confidence
    BUCKETS = [
        ("VERY HIGH", 0.95, 1.01, "auto-merge candidates — safe to bulk-add"),
        ("HIGH",      0.88, 0.95, "almost certainly the same person — quick glance"),
        ("MEDIUM",    0.78, 0.88, "needs human review — not obvious"),
        ("LOW",       0.00, 0.78, "probably different — but flagged"),
    ]
    buckets: dict[str, list[dict]] = {b[0]: [] for b in BUCKETS}
    for s in suggestions:
        c = s["confidence"]
        for label, lo, hi, _ in BUCKETS:
            if lo <= c < hi:
                buckets[label].append(s)
                break

    total = sum(len(v) for v in buckets.values())
    print(
        f"Found {total} candidate pair(s) (raw >= {args.threshold:.2f}). "
        f"Cmd+click any name to open the player page."
    )
    summary = []
    for label, lo, hi, _ in BUCKETS:
        summary.append(f"{label}={len(buckets[label])}")
    print(f"Distribution: {' · '.join(summary)}")
    print()

    # Short signal codes for the compact table.
    SIGNAL_CODES = {
        "first-letter match":         "fl+",
        "first-letter differs":       "fl!",
        "gender match (M)":           "gM",
        "gender match (F)":           "gF",
        "gender differs":             "g!",
        "shared club":                "club",
        "token-fp ~1-char-edit":      "typo",
        "token-count differs":        "tc!",
        "both have 30+ matches":      "30+",
    }

    def _short_signals(reasons: list[str]) -> str:
        out = []
        for r in reasons:
            if r.startswith("token-count match"):
                out.append("tc")
                continue
            if r.startswith("shared club"):
                out.append("club")
                continue
            if r.startswith("both have 30+"):
                out.append("30+")
                continue
            for prefix, code in SIGNAL_CODES.items():
                if r.startswith(prefix):
                    out.append(code)
                    break
        return "·".join(out)

    # OSC 8 hyperlink (clickable in iTerm2, Terminal.app, Warp, modern Cmder).
    OSC8_START = "\033]8;;{url}\033\\"
    OSC8_END = "\033]8;;\033\\"
    use_links = not args.no_links

    def _pad(text: str, visible: str, width: int) -> str:
        pad = max(1, width - len(visible))
        return text + (" " * pad)

    def _player_cell(p: dict, side: str) -> str:
        """Render one player as: ' A 385  37m C2  Aaron Micallef Piccione'.
        Total width ~46 + name. Name is OSC8-linked to the live player page.
        Gender, clubs, last-played are encoded via signal codes — not repeated
        in the table — so each row stays narrow enough for 80-char terminals.
        """
        url = f"{base}/players/{p['id']}.html"
        name = p["name"]
        truncated_name = name[:32]
        if use_links:
            linked = OSC8_START.format(url=url) + truncated_name + OSC8_END
        else:
            linked = truncated_name
        return (
            f"  {side}  "
            f"{str(p['id']):<5}"
            f"{str(p['n']) + 'm':>4}  "
            f"{(p.get('latest_class') or '-'):<3} "
            f"{linked}"
        )

    overall_idx = 0
    for label, lo, hi, hint in BUCKETS:
        bucket = buckets[label]
        if not bucket:
            continue
        bar = "═" * 78
        print(bar)
        rng = f"{lo:.2f}+" if hi > 1.0 else f"{lo:.2f}..{hi:.2f}"
        print(f"  {label}  (conf {rng})  —  {hint}  ({len(bucket)})")
        print(bar)
        # Compact header. Columns: [N] conf | side id n cl name | signals on next line.
        print(f"  #     conf   vs id    n   cl  player")
        print("─" * 78)

        for s in bucket:
            overall_idx += 1
            a, b = s["a"], s["b"]
            sigs = _short_signals(s["reasons"])
            print(f"[{overall_idx:>3}] {s['confidence']:.2f}{_player_cell(a, 'A')}")
            print(f"            {_player_cell(b, 'B')}".rstrip())
            print(f"            ↳ {sigs}")
        print()

    print(
        "Signal codes: fl+/fl! = first-letter match/differs · tc/tc! = "
        "token-count match/differs · gM/gF/g! = gender match/differs · "
        "club = shared club · typo = ~1-char-edit on token fp · 30+ = both "
        "30+ matches (dampener)"
    )
    print()
    print(
        "Same-person? Add their canonical names to "
        "scripts/phase0/manual_aliases.json (winner = prettier name, losers "
        "= the rest), then `apply-manual-aliases` + `rate` + "
        "`./scripts/deploy-site.sh`."
    )
    return 0


def cmd_apply_manual_aliases(args: argparse.Namespace) -> int:
    """Apply manual same-person merges from a JSON file (marriage names,
    nicknames, etc).
    """
    import db
    import players

    conn = db.init_db()
    try:
        applied, warnings = players.apply_manual_aliases(
            conn, args.file, dry_run=args.dry_run
        )
    finally:
        if args.dry_run:
            conn.rollback()
        conn.close()

    if not applied and not warnings:
        print(f"No merges defined in {args.file}.")
        return 0

    label = "Would apply" if args.dry_run else "Applied"
    n_merged = sum(
        1 for r in applied for l in r["losers"] if l["status"] == "merged"
    )
    print(f"{label} {n_merged} loser merge(s):")
    for r in applied:
        winner_label = f"{r['winner_name']!r} (id={r['winner_id']})"
        for loser in r["losers"]:
            status = loser["status"]
            if status == "merged":
                arrow = "→"
            elif status == "already-merged":
                arrow = "↻ already-merged →"
            elif status == "self":
                arrow = "= self →"
            else:
                arrow = "✗ not-found →"
            print(
                f"  {loser['name']!r} (id={loser['id']})  {arrow}  {winner_label}"
            )
    if warnings:
        print()
        print("Warnings:")
        for w in warnings:
            print(f"  - {w}")
    print()
    if args.dry_run:
        print("Dry run — re-run without --dry-run to apply.")
    else:
        print("Run `cli.py rate` to recompute ratings against the merged data.")
    return 0


def cmd_merge_token_duplicates(args: argparse.Namespace) -> int:
    """Merge players whose names are token-order-insensitive equivalents.

    Catches: case variants, swapped Surname/Name order, mixed combos.
    Same-token-count requirement avoids collapsing 'Robert Smith' into
    an unrelated 'Robert John Smith'.
    """
    import db
    import players

    conn = db.init_db()
    try:
        results = players.merge_token_duplicates(conn, dry_run=args.dry_run)
    finally:
        if args.dry_run:
            conn.rollback()
        conn.close()

    if not results:
        print("No token-equivalent duplicate players found.")
        return 0

    n_losers = sum(len(r["losers"]) for r in results)
    label = "Would merge" if args.dry_run else "Merged"
    print(
        f"{label} {n_losers} duplicate record(s) into {len(results)} canonical "
        f"player(s):"
    )
    for r in results:
        winner_label = (
            f"{r['winner_name']!r} (id={r['winner_id']}, n={r['winner_n_matches']})"
        )
        for loser in r["losers"]:
            print(
                f"  {loser['name']!r} (id={loser['id']}, n={loser['n_matches']}) "
                f" →  {winner_label}"
            )
    print()
    if args.dry_run:
        print("Dry run only — re-run without --dry-run to apply.")
    else:
        print("Run `cli.py rate` to recompute ratings against the merged data.")
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    """Walk pending fuzzy-match suggestions interactively (terminal-friendly).

    Designed for low-bandwidth use including SSH from phone — the prompt is
    minimal, the verdicts go to the same JSON files the public site reads,
    so a triage session done over SSH is durable.
    """
    import db
    import players
    from pathlib import Path as _P

    aliases_path = _P(__file__).resolve().parent / "manual_aliases.json"
    distinct_path = _P(__file__).resolve().parent / "known_distinct.json"

    conn = db.init_db()
    try:
        kd = players.load_known_distinct(str(distinct_path))
        suggestions = players.suggest_fuzzy_matches(
            conn,
            threshold=args.threshold,
            same_gender_only=not args.cross_gender,
            min_matches=args.min_matches,
            known_distinct=kd,
        )
    finally:
        conn.close()

    if not suggestions:
        print("Nothing to review — fuzzy queue is empty.")
        return 0

    # Apply confidence ceiling/floor filters if user asked
    if args.min_confidence is not None:
        suggestions = [s for s in suggestions if s["confidence"] >= args.min_confidence]
    if args.max_confidence is not None:
        suggestions = [s for s in suggestions if s["confidence"] <= args.max_confidence]

    if args.limit and args.limit > 0:
        suggestions = suggestions[: args.limit]

    n = len(suggestions)
    print(
        f"Reviewing {n} pending pair(s). For each, choose:\n"
        f"  s = SAME person (will be merged)\n"
        f"  d = DIFFERENT people (will stop being suggested)\n"
        f"  k = SKIP (decide later)\n"
        f"  q = QUIT (saves progress, exits)\n"
    )

    n_same = n_distinct = n_skip = 0
    for i, s in enumerate(suggestions, 1):
        a, b = s["a"], s["b"]
        signals = " · ".join(s.get("reasons") or [])
        # Pick a default winner: more matches, then non-CAPS
        def _pretty_key(p):
            return (-p["n"], 1 if p["name"].isupper() else 0, p["id"])
        default_winner_first = sorted([a, b], key=_pretty_key)[0] is a
        winner_default = a if default_winner_first else b
        loser_default = b if default_winner_first else a

        a_class = f", {a.get('latest_class')}" if a.get("latest_class") else ""
        b_class = f", {b.get('latest_class')}" if b.get("latest_class") else ""
        print(f"\n[{i}/{n}]  conf {s['confidence']:.2f}")
        print(f"  A  id #{a['id']:<5} ({a['n']}m{a_class})  {a['name']}")
        print(f"  B  id #{b['id']:<5} ({b['n']}m{b_class})  {b['name']}")
        print(f"  signals: {signals}")
        print(
            f"  default winner if [s]ame: {winner_default['name']!r} "
            f"(loser: {loser_default['name']!r})"
        )

        try:
            verdict = input("  → [s]ame / [d]ifferent / [k]eep / [q]uit > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n(interrupted — progress saved)")
            break

        if verdict in ("q", "quit"):
            print("(quit — progress saved)")
            break
        elif verdict in ("d", "different", "no", "n"):
            reason = input("  reason (optional, ENTER for default) > ").strip()
            if not reason:
                reason = "Different people; confirmed via cli review"
            ok = players.record_distinct(
                str(distinct_path), a["name"], b["name"], reason=reason
            )
            n_distinct += 1
            print(f"  → {'recorded' if ok else 'already recorded'}: distinct")
        elif verdict in ("s", "same", "yes", "y"):
            choice = input(
                f"  winner? [a]/[b]/ENTER for default ({'A' if default_winner_first else 'B'}) > "
            ).strip().lower()
            if choice == "a":
                w, l = a, b
            elif choice == "b":
                w, l = b, a
            else:
                w, l = winner_default, loser_default
            reason = input("  reason (optional) > ").strip() or "Same person; confirmed via cli review"
            ok = players.record_same_person(
                str(aliases_path), w["name"], l["name"], reason=reason
            )
            n_same += 1
            print(f"  → {'recorded' if ok else 'already recorded'}: {l['name']!r} → {w['name']!r}")
        else:
            n_skip += 1
            print("  → skipped")

    print(
        f"\nSession: {n_same} same · {n_distinct} different · {n_skip} skipped."
    )
    if n_same > 0:
        print(
            "Run `cli.py apply-manual-aliases --file scripts/phase0/manual_aliases.json` "
            "+ `cli.py rate` to materialize the SAME merges. "
            "Then `./scripts/deploy-site.sh` to publish."
        )
    elif n_distinct > 0:
        print(
            "DIFFERENT verdicts only — no DB changes needed. The next site "
            "build will pick up the filter via `./scripts/deploy-site.sh`."
        )
    return 0


def cmd_review_server(args: argparse.Namespace) -> int:
    """Start the local review server. Defined separately from the import so
    `cli.py --help` doesn't pay the import cost."""
    import review_server
    review_server.serve(port=args.port, open_browser=not args.no_browser)
    return 0


def cmd_merge_typo_duplicates(args: argparse.Namespace) -> int:
    """Auto-merge lopsided typo pairs (see players.merge_typo_duplicates)."""
    import db
    import players

    conn = db.init_db()
    try:
        pairs = players.merge_typo_duplicates(
            conn,
            dry_run=args.dry_run,
            min_winner_matches=args.min_winner_matches,
            max_loser_matches=args.max_loser_matches,
        )
    finally:
        if args.dry_run:
            conn.rollback()
        conn.close()

    if not pairs:
        print(
            f"No typo-pair candidates found "
            f"(winner ≥{args.min_winner_matches}m, loser ≤{args.max_loser_matches}m)."
        )
        return 0

    label = "Would merge" if args.dry_run else "Merged"
    print(f"{label} {len(pairs)} typo pair(s):")
    for p in pairs:
        w, l = p["winner"], p["loser"]
        print(
            f"  {l['name']!r} (id={l['id']}, n={l['n']}) "
            f" →  {w['name']!r} (id={w['id']}, n={w['n']})"
        )
    print()
    if args.dry_run:
        print("Dry run — re-run without --dry-run to apply.")
    else:
        print("Run `cli.py rate` to recompute ratings against the merged data.")
    return 0


def cmd_rank(args: argparse.Namespace) -> int:
    import db
    import rating

    sql = """
        SELECT
            p.canonical_name,
            p.gender,
            r.mu,
            r.sigma,
            r.n_matches,
            (
                SELECT MAX(m.played_on)
                FROM rating_history rh
                JOIN matches m ON m.id = rh.match_id
                WHERE rh.player_id = p.id AND rh.model_name = ?
            ) AS last_played,
            (
                SELECT m.division
                FROM matches m
                JOIN match_sides ms ON ms.match_id = m.id
                WHERE (ms.player1_id = p.id OR ms.player2_id = p.id)
                  AND m.superseded_by_run_id IS NULL
                  AND m.division IS NOT NULL
                GROUP BY m.division
                ORDER BY COUNT(*) DESC, m.division
                LIMIT 1
            ) AS primary_division,
            (
                SELECT COALESCE(SUM(ms.won), 0)
                FROM match_sides ms
                JOIN matches m ON m.id = ms.match_id
                WHERE (ms.player1_id = p.id OR ms.player2_id = p.id)
                  AND m.superseded_by_run_id IS NULL
            ) AS wins,
            (
                SELECT COALESCE(SUM(ms.games_won), 0)
                FROM match_sides ms
                JOIN matches m ON m.id = ms.match_id
                WHERE (ms.player1_id = p.id OR ms.player2_id = p.id)
                  AND m.superseded_by_run_id IS NULL
            ) AS games_won,
            (
                SELECT COALESCE(SUM(opp.games_won), 0)
                FROM match_sides ms
                JOIN matches m ON m.id = ms.match_id
                JOIN match_sides opp ON opp.match_id = ms.match_id AND opp.side <> ms.side
                WHERE (ms.player1_id = p.id OR ms.player2_id = p.id)
                  AND m.superseded_by_run_id IS NULL
            ) AS games_lost,
            -- v2: captain-assigned class label from most recent team tournament.
            -- NULL if player has no team-tournament assignments — fallback to
            -- derived class from primary division in display logic.
            (
                SELECT pta.class_label
                FROM player_team_assignments pta
                JOIN tournaments t ON t.id = pta.tournament_id
                WHERE pta.player_id = p.id
                ORDER BY t.year DESC, t.id DESC
                LIMIT 1
            ) AS captain_class,
            (
                SELECT pta.tier_letter
                FROM player_team_assignments pta
                JOIN tournaments t ON t.id = pta.tournament_id
                WHERE pta.player_id = p.id
                ORDER BY t.year DESC, t.id DESC
                LIMIT 1
            ) AS captain_tier,
            (
                SELECT pta.slot_number
                FROM player_team_assignments pta
                JOIN tournaments t ON t.id = pta.tournament_id
                WHERE pta.player_id = p.id
                ORDER BY t.year DESC, t.id DESC
                LIMIT 1
            ) AS captain_slot
        FROM ratings r
        JOIN players p ON p.id = r.player_id
        WHERE r.model_name = ?
    """
    params: list = [rating.CHAMPION_MODEL, rating.CHAMPION_MODEL]

    if args.gender == "men":
        sql += " AND p.gender = 'M'"
    elif args.gender == "ladies":
        sql += " AND p.gender = 'F'"
    # Default: sort by μ-3σ; we re-sort in Python for class-mode
    sql += " ORDER BY (r.mu - 3 * r.sigma) DESC"

    conn = db.init_db()
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    # Apply active-months filter (Phase 0 SE 2025 has placeholder dates;
    # use --active-months 0 to disable filter and see everyone).
    if args.active_months > 0:
        from datetime import date, timedelta

        cutoff = (date.today() - timedelta(days=args.active_months * 30)).isoformat()
        rows = [r for r in rows if r[5] and r[5] >= cutoff]

    if not rows:
        print(
            "rank: no players match the filters. Try --active-months 0 if "
            "your data uses placeholder dates.",
            file=sys.stderr,
        )
        return 0

    # v2: compute resolved class for each row (captain-assigned > derived from
    # primary division > '?'), and sort accordingly.
    TIER_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3, "?": 9}

    def _resolve_class(row):
        """Return (class_label, tier_letter, slot_number, source) for sorting.
        SQL row indices: 0=name, 1=gender, 2=mu, 3=sigma, 4=n, 5=last,
        6=primary_div, 7=wins, 8=games_won, 9=games_lost,
        10=captain_class, 11=captain_tier, 12=captain_slot."""
        captain_class = row[10]
        captain_tier = row[11]
        captain_slot = row[12]
        if captain_class:
            return captain_class, captain_tier, captain_slot, "captain"
        # Fallback: derive from primary division
        primary = row[6]
        if primary:
            norm = rating.normalize_division(primary)
            tier_map = {
                "Men Div 1": "A", "Men A": "A", "Lad Div 1": "A", "Lad A": "A",
                "Men Div 2": "B", "Men B": "B", "Lad Div 2": "B", "Lad B": "B",
                "Men Div 3": "C", "Men C": "C", "Lad Div 3": "C", "Lad C": "C",
                "Men Div 4": "D", "Men D": "D", "Lad D": "D",
            }
            tier = tier_map.get(norm)
            if tier:
                # Derived class: tier letter + '?' (no slot known)
                return f"{tier}?", tier, 99, "derived"
        return "?", "?", 99, "unknown"

    # Annotate rows with resolved class info: (..., class_label, tier, slot, source)
    rows_annotated = []
    for r in rows:
        cls, tier, slot, source = _resolve_class(r)
        rows_annotated.append((*r, cls, tier, slot, source))

    if args.sort == "class":
        # Sort: tier letter, slot number, then -μ-3σ (higher first within class)
        rows_annotated.sort(
            key=lambda r: (
                TIER_ORDER.get(r[11], 9),
                r[12],  # slot
                -(r[2] - 3 * r[3]),  # -μ-3σ
            )
        )
    # else 'raw': already sorted by μ-3σ in SQL

    rows = rows_annotated

    if args.by_category:
        # Group by TIER (per Kurt's domain knowledge: Men A ≡ Men Div 1,
        # Men B ≡ Men Div 2, etc.). Print top-N per tier in canonical order.
        # Unrecognized divisions sink to the end.
        from collections import OrderedDict

        # Map canonical division name → tier-display label. Both legs of
        # each tier (e.g. "Men A" and "Men Div 1") map to the same label
        # so they appear in the same group.
        DIV_TO_TIER_LABEL: dict[str, str] = {
            "Men A": "Men Tier 1  (A / Div 1)",
            "Men Div 1": "Men Tier 1  (A / Div 1)",
            "Men B": "Men Tier 2  (B / Div 2)",
            "Men Div 2": "Men Tier 2  (B / Div 2)",
            "Men C": "Men Tier 3  (C / Div 3)",
            "Men Div 3": "Men Tier 3  (C / Div 3)",
            "Men D": "Men Tier 4  (D / Div 4)",
            "Men Div 4": "Men Tier 4  (D / Div 4)",
            "Lad A": "Ladies Tier 1  (A / Div 1)",
            "Lad Div 1": "Ladies Tier 1  (A / Div 1)",
            "Lad B": "Ladies Tier 2  (B / Div 2)",
            "Lad Div 2": "Ladies Tier 2  (B / Div 2)",
            "Lad C": "Ladies Tier 3  (C / Div 3)",
            "Lad Div 3": "Ladies Tier 3  (C / Div 3)",
            "Lad D": "Ladies Tier 4  (D)",
        }
        TIER_ORDER = [
            "Men Tier 1  (A / Div 1)",
            "Men Tier 2  (B / Div 2)",
            "Men Tier 3  (C / Div 3)",
            "Men Tier 4  (D / Div 4)",
            "Ladies Tier 1  (A / Div 1)",
            "Ladies Tier 2  (B / Div 2)",
            "Ladies Tier 3  (C / Div 3)",
            "Ladies Tier 4  (D)",
        ]

        by_tier: OrderedDict[str, list] = OrderedDict((t, []) for t in TIER_ORDER)
        other: dict[str, list] = {}

        for row in rows:
            primary = row[6]
            norm = rating.normalize_division(primary) if primary else None
            tier = DIV_TO_TIER_LABEL.get(norm) if norm else None
            if tier:
                by_tier[tier].append(row)
            else:
                other.setdefault(norm or "(unknown)", []).append(row)

        any_printed = False
        for tier_label, tier_rows in by_tier.items():
            visible = tier_rows[: args.top]
            if not visible:
                continue
            any_printed = True
            print(f"\n=== {tier_label}  —  top {len(visible)} of {len(tier_rows)} ===")
            _print_rank_table(visible)

        for group_name, group_rows in other.items():
            visible = group_rows[: args.top]
            if not visible:
                continue
            any_printed = True
            print(f"\n=== {group_name}  —  top {len(visible)} of {len(group_rows)} ===")
            _print_rank_table(visible)

        if not any_printed:
            print("(no rows after filters)", file=sys.stderr)
        return 0

    rows = rows[: args.top]
    _print_rank_table(rows)
    return 0


def _print_rank_table(rows: list) -> None:
    """Print the standard rank table.

    Columns (v2):
      Rank  Class  Player  G  Primary  μ  σ  μ-3σ  n  W-L  win%  gW-gL  gW%  last

    Row formats supported:
    - 17 elements (annotated v2): SQL 13 fields + cls + tier + slot + source
    - 13 elements (raw v2 SQL):    13 SQL fields, no class resolution yet
    - 10 elements (legacy):         old format pre-class
    """
    print(
        f"{'Rank':>4}  {'Class':<6}  {'Player':<22}  {'G':1}  {'Primary':<10}  "
        f"{'mu':>6}  {'σ':>5}  {'μ-3σ':>6}  {'n':>4}  "
        f"{'W':>3}-{'L':<3}  {'win%':>4}  "
        f"{'gW':>4}-{'gL':<4}  {'gW%':>4}  {'last':<10}"
    )
    print("-" * 132)
    for i, row in enumerate(rows, 1):
        if len(row) >= 17:
            # Annotated: 13 SQL + (cls, tier, slot, source)
            name = row[0]; gender = row[1]; mu = row[2]; sigma = row[3]
            n = row[4]; last = row[5]; primary_div = row[6]
            wins = row[7]; games_won = row[8]; games_lost = row[9]
            cls = row[13]; source = row[16]
        elif len(row) >= 13:
            # Raw v2 SQL (no annotation): show captain_class directly
            name = row[0]; gender = row[1]; mu = row[2]; sigma = row[3]
            n = row[4]; last = row[5]; primary_div = row[6]
            wins = row[7]; games_won = row[8]; games_lost = row[9]
            cls = row[10] or "?"
            source = "captain" if row[10] else ""
        else:
            # Legacy 10-element format (pre-class)
            (name, gender, mu, sigma, n, last, primary_div,
             wins, games_won, games_lost) = row
            cls = "—"
            source = ""

        cons = mu - 3 * sigma
        # Note: tied rubbers (sets 1-1) are stored with won=0 on both sides
        # and so count as losses in this W-L column. The rating math is
        # already correct (rating.universal_score breaks the tie via games);
        # only the count is a documented compromise. Per-match displays use
        # the games-tiebreak — see generate_site.match_result().
        losses = n - wins
        win_pct = (wins / n * 100) if n > 0 else 0
        total_games = games_won + games_lost
        gw_pct = (games_won / total_games * 100) if total_games > 0 else 0
        print(
            f"{i:>4}  {cls:<6}  {name[:22]:<22}  {gender or '?':1}  "
            f"{(primary_div or '?')[:10]:<10}  "
            f"{mu:>6.2f}  {sigma:>5.2f}  {cons:>6.2f}  {n:>4}  "
            f"{wins:>3}-{losses:<3}  {win_pct:>3.0f}%  "
            f"{games_won:>4}-{games_lost:<4}  {gw_pct:>3.0f}%  {last or '?':<10}"
        )


def cmd_recommend_pairs(args: argparse.Namespace) -> int:
    import difflib

    import db
    import rating

    names = [n.strip() for n in args.players.split(",") if n.strip()]
    n = len(names)
    if n < 4 or n % 2 != 0:
        print(
            f"recommend-pairs: need an even number ≥ 4 of players (got {n}).",
            file=sys.stderr,
        )
        return 1

    conn = db.init_db()
    try:
        # Resolve names → (player_id, mu, sigma)
        player_data: dict[str, tuple[int, float, float]] = {}
        unresolved: list[str] = []
        for name in names:
            row = conn.execute(
                "SELECT p.id, r.mu, r.sigma FROM players p "
                "JOIN ratings r ON r.player_id = p.id "
                "WHERE p.canonical_name = ? AND r.model_name = ?",
                (name, rating.CHAMPION_MODEL),
            ).fetchone()
            if row:
                player_data[name] = row
            else:
                unresolved.append(name)

        if unresolved:
            all_names = [
                r[0] for r in conn.execute("SELECT canonical_name FROM players").fetchall()
            ]
            print(
                f"recommend-pairs: could not resolve {len(unresolved)} player(s):",
                file=sys.stderr,
            )
            for name in unresolved:
                close = difflib.get_close_matches(name, all_names, n=3, cutoff=0.5)
                hint = (", ".join(repr(c) for c in close)) if close else "(no close matches)"
                print(f"  {name!r}: did you mean {hint}?", file=sys.stderr)
            return 1
    finally:
        conn.close()

    # Pair-strength function: mu_a + mu_b - alpha * (sigma_a + sigma_b)
    # alpha = 1.0 default per T-P0-008 acceptance criteria.
    ALPHA = 1.0

    def pair_strength(a: str, b: str) -> float:
        _, mu_a, sigma_a = player_data[a]
        _, mu_b, sigma_b = player_data[b]
        return mu_a + mu_b - ALPHA * (sigma_a + sigma_b)

    # Brute force: enumerate all perfect matchings (fine for N ≤ ~14).
    # For 12 players: 10395 matchings — trivial.
    pairing, total = _best_pairing(names, pair_strength)

    print(
        f"Optimal pairing for {n} players "
        f"(score per pair = mu_a + mu_b - {ALPHA} × (σ_a + σ_b)):"
    )
    print("-" * 70)
    for a, b in pairing:
        print(f"  {a:<28} + {b:<28}  score: {pair_strength(a, b):>7.2f}")
    print("-" * 70)
    print(f"Total team strength: {total:>7.2f}")
    return 0


def _best_pairing(names: list[str], strength_fn) -> tuple[list[tuple[str, str]], float]:
    """Brute-force optimal perfect matching on `names` (must be even).

    Pairs the first name with each remaining one, recurses on the rest,
    keeps the highest-total split. O((N-1)!!) — fine for N ≤ ~14
    (12 players → 10395 matchings).
    """
    if not names:
        return [], 0.0
    if len(names) == 2:
        return [(names[0], names[1])], strength_fn(names[0], names[1])

    first = names[0]
    best: tuple[list[tuple[str, str]], float] = ([], float("-inf"))
    for i in range(1, len(names)):
        partner = names[i]
        rest = names[1:i] + names[i + 1 :]
        sub_pairing, sub_total = _best_pairing(rest, strength_fn)
        total = strength_fn(first, partner) + sub_total
        if total > best[1]:
            best = ([(first, partner)] + sub_pairing, total)
    return best


def cmd_eval_identity(args: argparse.Namespace) -> int:
    """Score the fuzzy suggester against the labelled identity sets."""
    import db
    import eval_identity

    conn = db.init_db()
    try:
        report = eval_identity.evaluate(conn, args.aliases, args.distinct)
        print(eval_identity.format_report(report))
    finally:
        conn.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="phase0",
        description="RallyRank Phase 0 — local doubles ranking proof of concept.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True, metavar="<command>")

    p_load = sub.add_parser(
        "load",
        help="Initialize SQLite and (optionally) load a tournament file.",
    )
    p_load.add_argument(
        "--init-only",
        action="store_true",
        help="Create the schema in phase0.sqlite; do not load any file.",
    )
    p_load.add_argument(
        "--file",
        help="Path to a tournament .xlsx file to load (e.g. _DATA_/VLTC/...).",
    )
    p_load.add_argument(
        "--no-merge",
        action="store_true",
        help=(
            "Skip the post-load identity-resolution sweep "
            "(case + token + typo + manual aliases). Use for diagnostic loads "
            "where you want to inspect raw post-parse state."
        ),
    )
    p_load.set_defaults(func=cmd_load)

    p_rate = sub.add_parser(
        "rate",
        help="Recompute OpenSkill ratings for all loaded matches.",
    )
    p_rate.set_defaults(func=cmd_rate)

    p_history = sub.add_parser(
        "history",
        help=(
            "Show the match-by-match rating trajectory for one player: "
            "partner, opponents, score, μ before→after, σ before→after. "
            "Useful for understanding why a player has the rating they do."
        ),
    )
    p_history.add_argument(
        "--player",
        required=True,
        help='Canonical player name (exact match). E.g. "Kurt Carabott".',
    )
    p_history.add_argument(
        "--recent",
        type=int,
        default=0,
        help=(
            "Limit to the most recent N matches (default 0 = show all). "
            "First-shown match's 'before' will reflect the previous match's "
            "after, OR the division starting-μ for match #1."
        ),
    )
    p_history.set_defaults(func=cmd_history)

    p_merge = sub.add_parser(
        "merge-case-duplicates",
        help=(
            "Find and merge player records that differ only by case "
            "(e.g. 'KURT CARABOTT' → 'Kurt Carabott'). The record with most "
            "matches is the winner; others are merged in (audit_log entry "
            "per merge). Run `rate` afterward to recompute."
        ),
    )
    p_merge.set_defaults(func=cmd_merge_case_duplicates)

    p_merge_tok = sub.add_parser(
        "merge-token-duplicates",
        help=(
            "Like merge-case-duplicates but ALSO catches swapped Surname/Name "
            "order (e.g. 'SCHEMBRI LEANNE' = 'Leanne Schembri'). Same token "
            "count required — won't collapse 'Robert Smith' into 'Robert John "
            "Smith'. Use --dry-run to preview."
        ),
    )
    p_merge_tok.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the proposed merges without modifying the database.",
    )
    p_merge_tok.set_defaults(func=cmd_merge_token_duplicates)

    p_merge_typo = sub.add_parser(
        "merge-typo-duplicates",
        help=(
            "Auto-merge lopsided typo pairs: established player (>=4 matches) "
            "+ ghost record (<=2 matches) whose names differ by ~1 character "
            "(missing letter, transposition). Requires same token count, same "
            "first letter, same gender or one unknown, and shared club. "
            "Conservative — same-N pairs go to suggest-merges for human review."
        ),
    )
    p_merge_typo.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the proposed merges without modifying the database.",
    )
    p_merge_typo.add_argument(
        "--min-winner-matches",
        type=int,
        default=4,
        help="Larger record must have at least this many matches (default 4).",
    )
    p_merge_typo.add_argument(
        "--max-loser-matches",
        type=int,
        default=2,
        help="Smaller record must have at most this many matches (default 2).",
    )
    p_merge_typo.set_defaults(func=cmd_merge_typo_duplicates)

    p_review = sub.add_parser(
        "review",
        help=(
            "Interactive triage of the fuzzy-match queue. For each pair "
            "shows compact info + signals; you choose [s]ame / [d]ifferent / "
            "[k]eep / [q]uit. Verdicts are appended to manual_aliases.json "
            "(same) or known_distinct.json (different). Phone-friendly: "
            "minimal output, single-character prompts, safe to interrupt."
        ),
    )
    p_review.add_argument(
        "--threshold", type=float, default=0.85,
        help="Minimum raw similarity to surface (default 0.85).",
    )
    p_review.add_argument(
        "--cross-gender", action="store_true",
        help="Also surface cross-gender pairs (default: same gender only).",
    )
    p_review.add_argument(
        "--min-matches", type=int, default=1,
        help="Both records must have at least this many active matches.",
    )
    p_review.add_argument(
        "--min-confidence", type=float, default=None,
        help="Skip pairs with confidence below this (e.g. 0.95 = VERY HIGH only).",
    )
    p_review.add_argument(
        "--max-confidence", type=float, default=None,
        help="Skip pairs above this (e.g. only review LOW/MEDIUM).",
    )
    p_review.add_argument(
        "--limit", type=int, default=0,
        help="Max number of pairs to walk in this session (0 = all).",
    )
    p_review.set_defaults(func=cmd_review)

    p_review_server = sub.add_parser(
        "review-server",
        help=(
            "Start a local-only review UI (stdlib http.server) on localhost. "
            "Same/different/defer buttons per pair, inline player mini-profiles. "
            "Verdicts go to manual_aliases.json + known_distinct.json — same "
            "files as `cli.py review` so the two tools cooperate."
        ),
    )
    p_review_server.add_argument(
        "--port", type=int, default=8765,
        help="Port to listen on (default 8765).",
    )
    p_review_server.add_argument(
        "--no-browser", action="store_true",
        help="Don't auto-open a browser tab.",
    )
    p_review_server.set_defaults(func=cmd_review_server)

    p_apply_aliases = sub.add_parser(
        "apply-manual-aliases",
        help=(
            "Apply manual same-person merges from a JSON file. For cases the "
            "automated rules can't catch — surname changes, nicknames, etc. "
            "Default file: scripts/phase0/manual_aliases.json. Idempotent."
        ),
    )
    p_apply_aliases.add_argument(
        "--file",
        default="scripts/phase0/manual_aliases.json",
        help="Path to the manual aliases JSON file.",
    )
    p_apply_aliases.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview without modifying the database.",
    )
    p_apply_aliases.set_defaults(func=cmd_apply_manual_aliases)

    p_suggest = sub.add_parser(
        "suggest-merges",
        help=(
            "List plausible same-person fuzzy matches above a similarity "
            "threshold so you can decide which to add to manual_aliases.json. "
            "Excludes pairs already caught by the case + token mergers."
        ),
    )
    p_suggest.add_argument(
        "--threshold",
        type=float,
        default=0.78,
        help=(
            "Raw similarity threshold (0..1). Default 0.78 — surfaces typos "
            "(VERY HIGH/HIGH) plus borderline pairs (MEDIUM/LOW) for review."
        ),
    )
    p_suggest.add_argument(
        "--limit",
        type=int,
        default=200,
        help="Max suggestions to print (default 200; 0 = unlimited).",
    )
    p_suggest.add_argument(
        "--min-matches",
        type=int,
        default=1,
        help=(
            "Skip players with fewer than this many active matches "
            "(default 1; raise to suppress noise from one-off entries)."
        ),
    )
    p_suggest.add_argument(
        "--cross-gender",
        action="store_true",
        help="Allow pairs across genders (default: off; same-gender only).",
    )
    p_suggest.add_argument(
        "--base-url",
        default="https://devkurtc.github.io/wks-social-tennis-rankings-malta",
        help="Base URL for clickable player links (default: live GH Pages).",
    )
    p_suggest.add_argument(
        "--no-links",
        action="store_true",
        help=(
            "Disable OSC 8 hyperlinks (use if your terminal renders the "
            "escape sequences as garbled text)."
        ),
    )
    p_suggest.set_defaults(func=cmd_suggest_merges)

    p_rank = sub.add_parser(
        "rank",
        help="Print the top-N doubles players from current ratings.",
    )
    p_rank.add_argument("--top", type=int, default=20, help="Number of players to show (default: 20).")
    p_rank.add_argument(
        "--active-months",
        type=int,
        default=12,
        help="Filter to players with a match in the last N months. Pass 0 to disable.",
    )
    p_rank.add_argument(
        "--gender",
        choices=["men", "ladies", "all"],
        default="all",
        help="Filter by gender (default: all).",
    )
    p_rank.add_argument(
        "--by-category",
        action="store_true",
        help=(
            "Group output by primary division/category — separate top-N per "
            "Men A / Men B / ... / Lad A / Lad B / ... etc."
        ),
    )
    p_rank.add_argument(
        "--sort",
        choices=["class", "raw"],
        default="class",
        help=(
            "Sort method. 'class' (default, v2): captain-assigned class label "
            "(A1, A2, ..., D3) primary; μ-3σ secondary within class. "
            "'raw': μ-3σ only (math-view; ignores class)."
        ),
    )
    p_rank.set_defaults(func=cmd_rank)

    p_pairs = sub.add_parser(
        "recommend-pairs",
        help="Recommend optimal pair combinations for a roster of players.",
    )
    p_pairs.add_argument(
        "--players",
        required=True,
        help='Comma-separated player names (even count, ≥4). Example: "Alice,Bob,Carol,Dan".',
    )
    p_pairs.set_defaults(func=cmd_recommend_pairs)

    p_eval = sub.add_parser(
        "eval-identity",
        help=(
            "Score the fuzzy suggester against the labelled identity sets — "
            "manual_aliases.json (positives) and known_distinct.json "
            "(negatives). Prints per-threshold recall, FP-rate, and the "
            "miss list to find score-function regressions early."
        ),
    )
    p_eval.add_argument(
        "--aliases",
        default="scripts/phase0/manual_aliases.json",
        help="Path to manual_aliases.json (positive pairs).",
    )
    p_eval.add_argument(
        "--distinct",
        default="scripts/phase0/known_distinct.json",
        help="Path to known_distinct.json (negative pairs).",
    )
    p_eval.set_defaults(func=cmd_eval_identity)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
