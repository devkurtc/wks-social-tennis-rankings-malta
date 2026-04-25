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
    print("rate: not implemented (T-P0-006 OpenSkill rating engine)", file=sys.stderr)
    return 1


def cmd_rank(args: argparse.Namespace) -> int:
    print("rank: not implemented (T-P0-007 rank command)", file=sys.stderr)
    return 1


def cmd_recommend_pairs(args: argparse.Namespace) -> int:
    print("recommend-pairs: not implemented (T-P0-008 pair recommender)", file=sys.stderr)
    return 1


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
