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
    from parsers import wilson as _wl

    DISPATCH: list[tuple[str, callable]] = [
        # Sports Experience Chosen Doubles (2024 + 2025) — same template,
        # same sheet names ('Men Div 1'..'Lad Div 3') → original parser.
        ("sports experience chosen doubles", _se.parse),
        # VLTC Mixed Doubles (and same-template division-RR files) — sheets
        # are 'Division 1'..'Division N'. Dynamic sub-block discovery.
        ("ess mixed tournament div and results", _md.parse),
        ("elektra mixed tournament div and results", _md.parse),
        # VLTC Team Tournaments (modern "Day N" template) — Antes / Tennis
        # Trade / San Michel post-2024 / Samsung Rennie Tonna. Same family.
        ("antes insurance team tournament", _tt.parse),
        ("tennis trade team tournament", _tt.parse),
        ("results tennis trade team tournament", _tt.parse),
        ("san michel results", _tt.parse),
        ("samsung rennie tonna", _tt.parse),
        # Wilson Autumn/Spring 2017-2021 (older team-tournament format,
        # both .xls and .xlsx). Auto-handles legacy Excel via xlrd.
        ("wilson autumn results", _wl.parse),
        ("wilson spring results", _wl.parse),
    ]

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
    finally:
        conn.close()
    print(f"Loaded ingestion_run_id={run_id} from {args.file}")
    return 0


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
            ) AS wins
        FROM ratings r
        JOIN players p ON p.id = r.player_id
        WHERE r.model_name = ?
    """
    params: list = [rating.CHAMPION_MODEL, rating.CHAMPION_MODEL]

    if args.gender == "men":
        sql += " AND p.gender = 'M'"
    elif args.gender == "ladies":
        sql += " AND p.gender = 'F'"
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
    """Print the standard rank table for a list of rows from cmd_rank's SQL."""
    print(
        f"{'Rank':>4}  {'Player':<26}  {'G':1}  {'PrimaryDiv':<13}  "
        f"{'mu':>6}  {'σ':>5}  {'μ-3σ':>6}  {'W':>3}-{'L':<3}  "
        f"{'win%':>4}  {'last':<10}"
    )
    print("-" * 100)
    for i, (name, gender, mu, sigma, n, last, primary_div, wins) in enumerate(rows, 1):
        cons = mu - 3 * sigma
        losses = n - wins
        win_pct = (wins / n * 100) if n > 0 else 0
        print(
            f"{i:>4}  {name[:26]:<26}  {gender or '?':1}  "
            f"{(primary_div or '?')[:13]:<13}  "
            f"{mu:>6.2f}  {sigma:>5.2f}  {cons:>6.2f}  "
            f"{wins:>3}-{losses:<3}  {win_pct:>3.0f}%  {last or '?':<10}"
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
    p_load.set_defaults(func=cmd_load)

    p_rate = sub.add_parser(
        "rate",
        help="Recompute OpenSkill ratings for all loaded matches.",
    )
    p_rate.set_defaults(func=cmd_rate)

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

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
