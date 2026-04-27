"""Synchronous reprocess pipeline runner.

Used by the "Reprocess pending changes" button in the review server (and,
eventually, the T-P0.5-019 daemon). Runs:

    1. apply-manual-aliases  → re-apply the JSON file (catches new merges
                                 that arrived since the last run)
    2. rate                  → recompute ratings against the now-correct
                                 player set
    3. generate-site         → re-render the static site to disk
    4. deploy-site.sh        → force-push the site/ tree to gh-pages

Each step prints progress to stdout. Step 4 is optional (`include_deploy`)
since the operator may want to verify locally before pushing.

Returns a structured result for the UI to display.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
DEPLOY_SCRIPT = PROJECT_ROOT / "scripts/deploy-site.sh"

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


def _step_apply_aliases(aliases_path: str) -> dict:
    """Run apply_manual_aliases against the live DB."""
    import db
    import players

    conn = db.init_db()
    try:
        applied, warnings = players.apply_manual_aliases(
            conn, aliases_path, dry_run=False,
        )
        conn.commit()
    finally:
        conn.close()
    n_merges = sum(
        1 for entry in applied
        for loser in entry.get("losers", [])
        if loser.get("status") == "merged"
    )
    return {"step": "apply_aliases", "merges_applied": n_merges,
            "warnings": warnings}


def _step_rate() -> dict:
    """Re-rate by invoking `cli.py rate` as a subprocess. The rate command
    writes verbose progress to stdout — capture stderr only so the UI can
    see warnings while keeping stdout for the caller."""
    proc = subprocess.run(
        ["python3", str(SCRIPT_DIR / "cli.py"), "rate"],
        cwd=str(PROJECT_ROOT),
        capture_output=True, text=True,
    )
    return {
        "step": "rate",
        "rc": proc.returncode,
        "stderr": proc.stderr[-2000:] if proc.stderr else "",
    }


def _step_generate_site() -> dict:
    import generate_site
    rc = generate_site.main()
    return {"step": "generate_site", "rc": rc}


def _step_deploy() -> dict:
    if not DEPLOY_SCRIPT.exists():
        return {"step": "deploy", "rc": -1,
                "error": f"deploy script not found at {DEPLOY_SCRIPT}"}
    proc = subprocess.run(
        ["bash", str(DEPLOY_SCRIPT)],
        cwd=str(PROJECT_ROOT),
        capture_output=True, text=True,
        timeout=180,
    )
    return {
        "step": "deploy",
        "rc": proc.returncode,
        "stdout_tail": proc.stdout[-1500:] if proc.stdout else "",
        "stderr_tail": proc.stderr[-1500:] if proc.stderr else "",
    }


def run(
    *,
    aliases_path: str | None = None,
    include_deploy: bool = False,
) -> dict:
    """Run the full pipeline. Stops at the first non-zero rc step.

    Returns:
        {
            "ok": bool,                  # all steps rc=0
            "steps": [{step, rc, ...}],
            "stopped_at": str | None,
        }
    """
    if aliases_path is None:
        aliases_path = str(SCRIPT_DIR / "manual_aliases.json")

    steps = [
        ("apply_aliases", lambda: _step_apply_aliases(aliases_path)),
        ("rate", _step_rate),
        ("generate_site", _step_generate_site),
    ]
    if include_deploy:
        steps.append(("deploy", _step_deploy))

    results: list[dict] = []
    stopped_at: str | None = None
    for name, fn in steps:
        try:
            res = fn()
        except Exception as e:
            results.append({"step": name, "rc": -1, "error": str(e)})
            stopped_at = name
            break
        results.append(res)
        if res.get("rc", 0) != 0:
            stopped_at = name
            break

    ok = stopped_at is None and all(
        r.get("rc", 0) == 0 for r in results
    )
    return {"ok": ok, "steps": results, "stopped_at": stopped_at}


if __name__ == "__main__":
    out = run(include_deploy=False)
    print(json.dumps(out, indent=2))
    sys.exit(0 if out["ok"] else 1)
