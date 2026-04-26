"""SQLite DB helper for RallyRank Phase 0.

The canonical schema design lives in PLAN.md §6. The Phase 0 SQLite subset
lives at `scripts/phase0/schema.sql`. All Phase 0 code that touches the DB
should go through `init_db()` to ensure foreign keys are enabled and the
schema is applied.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent / "schema.sql"
# Anchor the default DB to the project root, NOT cwd — otherwise running the
# CLI from `scripts/phase0/` silently touches a different file than running it
# from the repo root, and the deploy script (which reads project-root
# phase0.sqlite) sees stale data. The path resolves to:
#   scripts/phase0/db.py → scripts/phase0/ → scripts/ → <project root>
DEFAULT_DB_PATH = str(Path(__file__).resolve().parent.parent.parent / "phase0.sqlite")


def init_db(path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open a SQLite connection to `path` and apply the Phase 0 schema.

    Idempotent: safe to call against an existing file. Foreign keys enforced.
    Returns the open connection — caller is responsible for closing it.
    """
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.executescript(SCHEMA_PATH.read_text())
    conn.commit()
    return conn


def table_count(conn: sqlite3.Connection) -> int:
    """Return number of user tables in the DB. Used by `cli.py load --init-only`."""
    row = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    ).fetchone()
    return row[0]
