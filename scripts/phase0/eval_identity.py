"""Identity-resolution evaluation harness.

Measures how well the fuzzy suggester (`players.suggest_fuzzy_matches` /
`players._confidence`) would have surfaced known same-person pairs and how
often it would have falsely surfaced known-distinct pairs.

Ground truth:
  * Positive pairs: every (winner, loser) in `manual_aliases.json`.
  * Negative pairs: every (a, b) in `known_distinct.json`.

Output: a per-threshold table of recall, FP-rate, and precision plus a
listing of misses (positive pairs the scorer would not have surfaced at the
production threshold). Use this to:

  - Validate that score-function changes don't regress recall.
  - Find the threshold that maximises precision-recall for the live data.
  - Surface algorithm misses worth tightening signal weights for.

Run from repo root:
    python scripts/phase0/eval_identity.py
or via the CLI:
    python scripts/phase0/cli.py eval-identity
"""

from __future__ import annotations

import difflib
import json
import sqlite3
import sys
from pathlib import Path

# Allow running directly OR as `python -m scripts.phase0.eval_identity`.
sys.path.insert(0, str(Path(__file__).parent))

import players as _players  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_ALIASES = str(REPO_ROOT / "scripts/phase0/manual_aliases.json")
DEFAULT_DISTINCT = str(REPO_ROOT / "scripts/phase0/known_distinct.json")
DEFAULT_THRESHOLDS = (
    0.50, 0.60, 0.70, 0.78, 0.85, 0.88, 0.92, 0.95, 0.98,
)


def _build_player_dict(conn: sqlite3.Connection, name: str) -> dict:
    """Best-effort player record for `name`. Looks up gender/n/class/clubs from
    the DB if the canonical_name still exists; otherwise returns a name-only
    stub. The score function tolerates missing fields — they just don't
    contribute their respective signals."""
    row = conn.execute(
        "SELECT id, canonical_name, gender FROM players "
        "WHERE canonical_name = ?",
        (name,),
    ).fetchone()
    if row:
        pid, canonical, gender = row
        n_row = conn.execute(
            "SELECT COUNT(*) FROM match_sides ms "
            "JOIN matches m ON m.id = ms.match_id "
            "WHERE (ms.player1_id = ? OR ms.player2_id = ?) "
            "AND m.superseded_by_run_id IS NULL",
            (pid, pid),
        ).fetchone()
        cls_row = conn.execute(
            "SELECT pta.class_label FROM player_team_assignments pta "
            "JOIN tournaments t ON t.id = pta.tournament_id "
            "WHERE pta.player_id = ? "
            "ORDER BY t.year DESC, t.id DESC LIMIT 1",
            (pid,),
        ).fetchone()
        clubs_row = conn.execute(
            "SELECT GROUP_CONCAT(DISTINCT c.slug) FROM match_sides ms "
            "JOIN matches m ON m.id = ms.match_id "
            "JOIN tournaments t ON t.id = m.tournament_id "
            "JOIN clubs c ON c.id = t.club_id "
            "WHERE (ms.player1_id = ? OR ms.player2_id = ?) "
            "AND m.superseded_by_run_id IS NULL",
            (pid, pid),
        ).fetchone()
        return _player_dict_for_scoring(
            pid=pid, name=canonical, gender=gender,
            n=(n_row[0] if n_row else 0),
            latest_class=(cls_row[0] if cls_row else "") or "",
            clubs=(clubs_row[0] if clubs_row else "") or "",
        )
    return _player_dict_for_scoring(pid=None, name=name)


def _player_dict_for_scoring(
    *, pid, name, gender=None, n=0, latest_class="", clubs="",
) -> dict:
    """Shape that `players._confidence` expects, including pre-computed keys."""
    return {
        "id": pid, "name": name, "gender": gender,
        "n": n, "latest_class": latest_class, "clubs": clubs,
        "_key": " ".join(name.lower().split()),
        "_token_fp": _players._token_fingerprint(name),
        "_first": name[:1].lower(),
    }


def score_pair(conn: sqlite3.Connection, name_a: str, name_b: str) -> dict:
    """Score a single (a, b) pair using the same logic the suggester applies."""
    a = _build_player_dict(conn, name_a)
    b = _build_player_dict(conn, name_b)
    raw = difflib.SequenceMatcher(None, a["_key"], b["_key"]).ratio()
    confidence, reasons = _players._confidence(a, b, raw)
    return {
        "a_name": name_a,
        "b_name": name_b,
        "raw_score": raw,
        "confidence": confidence,
        "reasons": reasons,
        "a_resolved": a["id"] is not None,
        "b_resolved": b["id"] is not None,
    }


def load_positive_pairs(path: str) -> list[tuple[str, str]]:
    """Read manual_aliases.json and yield each (winner, loser) pair."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    out: list[tuple[str, str]] = []
    for entry in data.get("merges", []):
        winner = entry.get("winner")
        if not winner:
            continue
        for loser in entry.get("losers", []) or []:
            if loser:
                out.append((winner, loser))
    return out


def load_negative_pairs(path: str) -> list[tuple[str, str]]:
    """Read known_distinct.json. Empty list if the file doesn't exist."""
    if not Path(path).exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    out: list[tuple[str, str]] = []
    for entry in data.get("pairs", []) or []:
        a, b = entry.get("a"), entry.get("b")
        if a and b:
            out.append((a, b))
    return out


def evaluate(
    conn: sqlite3.Connection,
    aliases_path: str = DEFAULT_ALIASES,
    distinct_path: str = DEFAULT_DISTINCT,
    thresholds: tuple[float, ...] = DEFAULT_THRESHOLDS,
) -> dict:
    """Run the harness end-to-end. Returns a structured report."""
    positives = [
        score_pair(conn, a, b) for (a, b) in load_positive_pairs(aliases_path)
    ]
    negatives = [
        score_pair(conn, a, b) for (a, b) in load_negative_pairs(distinct_path)
    ]

    rows = []
    n_pos, n_neg = len(positives), len(negatives)
    for t in thresholds:
        tp = sum(1 for s in positives if s["confidence"] >= t)
        fp = sum(1 for s in negatives if s["confidence"] >= t)
        recall = (tp / n_pos) if n_pos else None
        fp_rate = (fp / n_neg) if n_neg else None
        precision = (tp / (tp + fp)) if (tp + fp) else None
        rows.append({
            "threshold": t,
            "tp": tp, "fn": n_pos - tp,
            "fp": fp, "tn": n_neg - fp,
            "recall": recall, "fp_rate": fp_rate, "precision": precision,
        })
    return {
        "n_positive": n_pos,
        "n_negative": n_neg,
        "thresholds": rows,
        "positive_pairs": positives,
        "negative_pairs": negatives,
    }


def _fmt_pct(v: float | None) -> str:
    return f"{v:6.1%}" if v is not None else "   n/a"


def format_report(report: dict, miss_threshold: float = 0.78) -> str:
    """Render the report as a human-readable text block."""
    lines: list[str] = []
    lines.append(
        f"Identity-eval: {report['n_positive']} positive pair(s), "
        f"{report['n_negative']} negative pair(s)"
    )
    if report["n_negative"] == 0:
        lines.append(
            "  (No negative pairs in known_distinct.json yet — FP-rate and "
            "precision are undefined. Populate the file as you triage "
            "false-positives in `cli.py review`.)"
        )
    lines.append("")
    lines.append(
        f"  {'thr':>5}  {'recall':>7}  {'FP-rate':>7}  {'precision':>9}"
        f"  {'TP':>4} {'FN':>4} {'FP':>4} {'TN':>4}"
    )
    for r in report["thresholds"]:
        lines.append(
            f"  {r['threshold']:>5.2f}  {_fmt_pct(r['recall'])}  "
            f"{_fmt_pct(r['fp_rate'])}  {_fmt_pct(r['precision']):>9}"
            f"  {r['tp']:>4} {r['fn']:>4} {r['fp']:>4} {r['tn']:>4}"
        )

    misses = [
        s for s in report["positive_pairs"]
        if s["confidence"] < miss_threshold
    ]
    if misses:
        lines.append("")
        lines.append(
            f"Misses (confidence < {miss_threshold:.2f}): "
            f"{len(misses)} pair(s) the scorer would NOT surface at the "
            f"production threshold."
        )
        for m in sorted(misses, key=lambda s: s["confidence"]):
            badge = ""
            if not m["a_resolved"] or not m["b_resolved"]:
                # Name not in DB → enrichment fell back to defaults; the score
                # may be lower than what the live suggester saw before merge.
                badge = " [stub]"
            lines.append(
                f"  conf={m['confidence']:.3f}  raw={m['raw_score']:.3f}  "
                f"{m['a_name']!r}  vs  {m['b_name']!r}{badge}"
            )
        lines.append(
            "  (NOTE: pairs flagged [stub] couldn't be enriched from the DB "
            "— the loser record was deleted post-merge, so structured signals "
            "like gender/club aren't available. Score is name-only.)"
        )
    return "\n".join(lines)


def main(
    aliases_path: str = DEFAULT_ALIASES,
    distinct_path: str = DEFAULT_DISTINCT,
) -> int:
    import db
    conn = db.init_db()
    try:
        report = evaluate(conn, aliases_path, distinct_path)
        print(format_report(report))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
