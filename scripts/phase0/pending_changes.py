"""Pending-change accumulator for the identity-triage UI.

Every verdict written by `cli.py review-server` (Merge / De-merge / Different
/ Don't-know) appends one JSONL row to `pending_changes.jsonl`. The "Reprocess
pending changes" button — and the future T-P0.5-019 daemon — read this file
to know how much work has accumulated since the last full pipeline run.

Schema (one JSON object per line):
    {
        "ts": "2026-04-27T12:34:56Z",       # ISO8601 UTC
        "verdict": "merge"|"unmerge"|"distinct"|"defer",
        "a_name": str, "b_name": str,
        "extra": {...}                       # optional verdict-specific data
    }

Writes are append-only and atomic at the line level (one `write` call per
line, file flushed). Concurrent appenders cooperate via the OS's append-write
guarantee on small writes.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PENDING_PATH = SCRIPT_DIR / "pending_changes.jsonl"

# Lock around the append so two threads in the same process don't interleave
# JSONL lines. Cross-process safety relies on POSIX append-mode semantics.
_APPEND_LOCK = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def record(
    verdict: str,
    a_name: str,
    b_name: str,
    *,
    extra: dict | None = None,
    path: str | None = None,
    ts: str | None = None,
) -> dict:
    """Append one verdict row. Returns the row written."""
    if verdict not in ("merge", "unmerge", "distinct", "defer"):
        raise ValueError(f"unknown verdict: {verdict!r}")
    row = {
        "ts": ts or _now_iso(),
        "verdict": verdict,
        "a_name": a_name,
        "b_name": b_name,
    }
    if extra:
        row["extra"] = extra
    target = Path(path) if path else PENDING_PATH
    with _APPEND_LOCK:
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False))
            f.write("\n")
    return row


def iter_rows(path: str | None = None) -> list[dict]:
    """Read every row from the pending file. Empty list if missing."""
    target = Path(path) if path else PENDING_PATH
    if not target.exists():
        return []
    out: list[dict] = []
    with open(target, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                # Don't fail the whole read on a single corrupt row —
                # the rest are still useful and the operator can clean
                # the file if needed.
                continue
    return out


def summary(path: str | None = None) -> dict:
    """Return {count, first_change_ts, last_change_ts, by_verdict} over the
    current pending file. Used by the UI's reprocess button + by the future
    daemon's threshold check."""
    rows = iter_rows(path)
    if not rows:
        return {
            "count": 0,
            "first_change_ts": None,
            "last_change_ts": None,
            "by_verdict": {},
        }
    by_v: dict[str, int] = {}
    for r in rows:
        v = r.get("verdict", "?")
        by_v[v] = by_v.get(v, 0) + 1
    return {
        "count": len(rows),
        "first_change_ts": rows[0].get("ts"),
        "last_change_ts": rows[-1].get("ts"),
        "by_verdict": by_v,
    }


def archive(reason: str = "reprocess complete", *, path: str | None = None) -> str | None:
    """Move the pending file to a timestamped archive. Returns the archive
    path, or None if there was nothing to archive."""
    target = Path(path) if path else PENDING_PATH
    if not target.exists() or target.stat().st_size == 0:
        return None
    archive_path = target.with_suffix(
        f".{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.jsonl"
    )
    # Append a marker line BEFORE renaming so the archive carries its own
    # provenance (otherwise the reason is lost the moment we move the file).
    with _APPEND_LOCK:
        with open(target, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": _now_iso(),
                "verdict": "_archive_marker",
                "reason": reason,
            }) + "\n")
        os.replace(target, archive_path)
    return str(archive_path)


def threshold_reached(
    *,
    max_count: int = 10,
    max_minutes: int = 30,
    path: str | None = None,
) -> bool:
    """Return True if the daemon should fire reprocess.

    Trigger logic (matches T-P0.5-019 spec):
      * count >= max_count, OR
      * count >= 1 AND now - first_change >= max_minutes
    """
    s = summary(path)
    if s["count"] == 0:
        return False
    if s["count"] >= max_count:
        return True
    first = s["first_change_ts"]
    if not first:
        return False
    try:
        first_dt = datetime.fromisoformat(first.replace("Z", "+00:00"))
    except ValueError:
        return False
    age_min = (datetime.now(timezone.utc) - first_dt).total_seconds() / 60
    return age_min >= max_minutes
