"""Fixture locator for parser tests.

The `_DATA_/` layout has been reorganised once already (flat → `<year>/<club>/<slug>/`)
and may move again. Tests should NOT hardcode paths under `_DATA_/`; they should
ask `locate(name)` which walks the tree once per test process and caches results.

If a fixture is genuinely missing, `locate(name)` returns `None` so the calling
test can `skipTest(...)` rather than erroring.
"""
from __future__ import annotations

import functools
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DATA_ROOT = REPO_ROOT / "_DATA_"


@functools.lru_cache(maxsize=1)
def _index() -> dict[str, str]:
    """basename → first-match absolute path. Cached for the life of the
    process so tests don't re-walk the tree per call."""
    if not DATA_ROOT.exists():
        return {}
    out: dict[str, str] = {}
    for p in DATA_ROOT.rglob("*.xls*"):
        # First match wins; we don't expect duplicate basenames across the
        # tree (and if one ever appears, the duplicate will be silently
        # ignored — fix the data layout, don't paper over here).
        out.setdefault(p.name, str(p))
    return out


def locate(name: str) -> str | None:
    """Return the absolute path of the fixture `name` (e.g.
    `'Wilson Autumn Results 2019.xlsx'`), or None if not present."""
    return _index().get(name)
