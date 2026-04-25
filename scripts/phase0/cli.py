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

    # Phase 0: only one parser registered. Filename-based dispatch — Phase 1
    # introduces a registry pattern when more parsers exist.
    import os
    filename = os.path.basename(args.file).lower()
    parse_fn = None
    if filename.startswith("sports experience chosen doubles 2025"):
        from parsers import sports_experience_2025 as _p
        parse_fn = _p.parse
    if parse_fn is None:
        print(
            f"load: no parser registered for {os.path.basename(args.file)!r}. "
            "Phase 0 only supports 'Sports Experience Chosen Doubles 2025 result sheet.xlsx'.",
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
            ) AS last_played
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

    rows = rows[: args.top]

    if not rows:
        print(
            "rank: no players match the filters. Try --active-months 0 if "
            "your data uses placeholder dates.",
            file=sys.stderr,
        )
        return 0

    print(
        f"{'Rank':>4}  {'Player':<32}  {'G':1}  {'mu':>7}  {'sigma':>6}  "
        f"{'mu-3σ':>7}  {'matches':>7}  {'last played':<12}"
    )
    print("-" * 92)
    for i, (name, gender, mu, sigma, n, last) in enumerate(rows, 1):
        cons = mu - 3 * sigma
        print(
            f"{i:>4}  {name[:32]:<32}  {gender or '?':1}  {mu:>7.2f}  "
            f"{sigma:>6.2f}  {cons:>7.2f}  {n:>7}  {last or '?':<12}"
        )
    return 0


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
