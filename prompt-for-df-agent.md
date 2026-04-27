# Task: add a "DF Version" alongside the existing "KC Version" leaderboard

> **Note for future readers:** this file is a snapshot brief from when DF's contribution was first proposed. For the *canonical* procedure for adding any new rating model — any future contributor, any algorithm — invoke the **`/add-rating-model`** skill in Claude Code, or read [`.claude/skills/add-rating-model/SKILL.md`](.claude/skills/add-rating-model/SKILL.md) directly. The brief below is still valid as a self-contained spec for agents that don't support Claude Code skills (Cursor, Copilot, Claude.ai web, ChatGPT, etc.).

You're contributing to **RallyRank** — an open-source multi-club tennis doubles ranking system: https://github.com/devkurtc/wks-social-tennis-rankings-malta

The current site (https://devkurtc.github.io/wks-social-tennis-rankings-malta/) shows leaderboard rankings produced by Kurt's rating model (OpenSkill Plackett-Luce, called "the champion"). My friend Kurt and I want both rating models to coexist and update independently. Your job is to add a **version toggle** at the top of the leaderboard so a viewer can switch between **"KC Version"** (the existing model) and **"DF Version"** (my model). Both versions read from the same matches data; they differ only in the rating algorithm.

---

## Step 1 — clone and orient yourself (read these first, before writing any code)

1. `git clone https://github.com/devkurtc/wks-social-tennis-rankings-malta.git` and `cd` in.
2. Read in this order — they're short:
   - `README.md` (project pitch + live demo link)
   - `CONTRIBUTING.md` (setup, tests, workflow, hard rules — the canonical contributor doc)
   - `CLAUDE.md` (orientation, especially if your agent supports Claude Code skills)
   - `PLAN.md` §5.2 (champion algorithm choice and universal score formula)
   - `PLAN.md` §5.7 (multi-model architecture — **this is the contract you're plugging into**)
   - `PLAN.md` §6 (schema; especially `ratings` and `rating_history` tables)
3. Skim:
   - `scripts/phase0/rating.py` — the existing OpenSkill engine. Note `CHAMPION_MODEL = "openskill_pl"` and how `recompute_all(conn, model_name=...)` is called.
   - `scripts/phase0/generate_site.py` lines 1–100 (overview + `MODEL = "openskill_pl"` constant) and lines 596–640 (`render_nav` — top navigation).
   - `scripts/phase0/cli.py` around line 253 (`recompute` subcommand entry point).
   - `scripts/deploy-site.sh` (how the site is shipped).

**Hard rules from `CLAUDE.md`:**
- Do **not** modify any file inside `_DATA_/`. Treat as read-only.
- Do **not** widen the schema or rename tables without proposing it in `PLAN.md` first. Multi-model is already supported; you should not need a schema change.
- Do **not** deploy. Open a PR to `main`. Kurt regenerates and ships via `./scripts/deploy-site.sh`.
- Names are normalized (NFKC + straight quotes + collapsed whitespace) on insert. Use existing helpers — don't roll your own.
- Every mutation goes through the audit-log helper. If you add a recompute path, follow the same pattern as `rating.recompute_all`.

---

## Step 2 — implement DF's rating model

Create `scripts/phase0/rating_df.py` (sibling to `rating.py`). Constraints:

1. **Choose a unique `model_name` string** — e.g. `"df_<algorithm>_v1"`. It must not collide with existing names: `openskill_pl`, `openskill_pl_vanilla`, `openskill_pl_decay365`. Add it as a constant at the top of the file.
2. **Expose a `recompute_all(conn, model_name=...)` function** with the same signature/contract as `rating.recompute_all`. Read matches from the existing `matches` table (chronologically); write `ratings` (current state) and `rating_history` (per-match snapshot) rows tagged with your `model_name`.
3. **Reuse `rating.universal_score(...)`** for the per-match outcome value (PLAN.md §5.2). If your algorithm needs a different score representation, document the deviation in a `# Why:` comment.
4. **Pure-Python or one new pinned dep.** If you add a dep, justify it briefly in the PR description. Keep style consistent with the repo: black + ruff, type hints on public functions.
5. **Tests + coverage.** Add `scripts/phase0/test_rating_df.py` mirroring the structure of `test_rating.py`. **Project policy: ≥80% line coverage on `scripts/phase0/`. Your new module must hit ≥80% on its own, and the project-total coverage must not drop.** At minimum: a small synthetic match set with known expected ratings (or known *ordering*); a regression that ensures running your model does not mutate `openskill_pl` rows; a re-run idempotence check. Measure with `pytest --cov=scripts.phase0 --cov-report=term-missing scripts/phase0/` (install `pytest-cov` if needed).

Wire it into the CLI: extend `scripts/phase0/cli.py`'s `recompute` subcommand so `python3 -m scripts.phase0.cli recompute --model df_<...>_v1` invokes your `recompute_all`. Don't break the existing default-model behaviour.

---

## Step 3 — add the version toggle to the leaderboard page

The leaderboard is a **static page** generated by `scripts/phase0/generate_site.py`. There's no SPA framework — it's a single HTML file with embedded JS. The toggle should be a tab-style switcher right above the leaderboard table:

```
┌──────────────────────────────────┐
│  [ KC Version ] [ DF Version ]   │
└──────────────────────────────────┘
   Power | Glicko | RD | OS cons. | ...
```

Implementation guidance:

1. In `generate_site.py`, replace the single hard-coded `MODEL = "openskill_pl"` constant with a list of view configurations:
   ```python
   LEADERBOARD_MODELS = [
       {"key": "kc",  "label": "KC Version",  "model_name": "openskill_pl"},
       {"key": "df",  "label": "DF Version",  "model_name": "df_<...>_v1"},
   ]
   ```
2. For each entry, run the existing leaderboard query (look for `WHERE r.model_name = ?`). Emit one `<table>` per model, all on `index.html`, but only one visible at a time. The tab buttons toggle a CSS class — keep it pure CSS + a few lines of vanilla JS, matching the style elsewhere in `generate_site.py` (e.g. the changelog filter pills around line 3879).
3. Persist the user's choice in `localStorage` so a reload keeps the active tab.
4. **Per-player pages and tournament pages stay on KC's model** (don't multiply pages — that's a follow-up). Just the main leaderboard gets the toggle for now.
5. If a model has zero rated players (DF hasn't been run yet), the tab should still render but show an empty state ("No DF Version data yet — run `python3 -m scripts.phase0.cli recompute --model df_<...>_v1`").

**Style rules:**
- Don't introduce a JS framework or build step. The repo is intentionally framework-free.
- Don't add comments that explain *what* the code does. Only add a `# Why:` comment if a constant or branch is non-obvious. Default = no comment.
- Match the existing visual style of `site/styles.css`. Don't restyle the whole page.

---

## Step 4 — verify locally

From repo root:

```bash
python3 -m scripts.phase0.cli ingest        # if needed; only runs if matches haven't loaded
python3 -m scripts.phase0.cli recompute --model openskill_pl
python3 -m scripts.phase0.cli recompute --model df_<...>_v1
python3 scripts/phase0/generate_site.py
python3 -m http.server -d site 8000
# open http://localhost:8000/ and click between KC Version / DF Version
```

Check:
- Both tabs render. Numbers are different (your model produces different ratings).
- Switching tabs is instant — no page reload.
- All other pages (`matches.html`, `aliases.html`, `how-it-works.html`, etc.) still work.
- `pytest scripts/phase0/` passes (existing tests + your new `test_rating_df.py`).
- `git diff` does not touch `_DATA_/` or `phase0.sqlite` (the DB file is gitignored anyway, but double-check).

---

## Step 5 — open a PR

Branch name: `df/add-version-toggle` (or similar).

**Commit + pull cadence (please follow):** small commits, one logical chunk each; push as soon as a commit is mergeable; `git pull --rebase origin main` before each work session and again before any push if the session has been long. See `CONTRIBUTING.md` for the full rule and the why. This matters specifically because multiple agents and humans are touching `TASKS.md` and the `.claude/` coordination files concurrently.

PR description should include:

- One-paragraph summary of the algorithm DF used and how it differs from OpenSkill PL.
- A screenshot of the toggle in both states.
- Confirmation: "I did not modify `_DATA_/`, did not deploy to gh-pages, and ran the local verify steps in Step 4."
- Coverage report: `pytest --cov=scripts.phase0 --cov-report=term scripts/phase0/` output, demonstrating ≥80% coverage on the new module and no regression on project total.
- Any new pinned deps and why.

**License:** by submitting the PR you agree your contribution is licensed under [AGPL-3.0](LICENSE) — same as the rest of the repo. Your `rating_df.py` ships under that license.

Kurt will review, run `./scripts/deploy-site.sh` to ship it, and merge.

---

## Things NOT to do

- Don't touch the `gh-pages` branch. Don't run `deploy-site.sh`. Kurt deploys.
- Don't introduce a second SQLite DB. Both models share `phase0.sqlite`.
- Don't add a "default model" toggle to the CLI that changes what KC's existing scripts do. Your model is purely additive.
- Don't rewrite `rating.py`. Add a sibling module.
- Don't rename existing `model_name` strings in the DB; downstream queries depend on `openskill_pl` and `openskill_pl_decay365`.
- Don't regenerate `phase0.sqlite` from scratch unless explicitly asked — it has manual identity-resolution decisions baked in (see `manual_aliases.json` and the `pending_changes` flow).
