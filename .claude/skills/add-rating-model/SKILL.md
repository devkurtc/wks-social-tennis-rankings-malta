---
name: add-rating-model
description: Add a new rating-engine variant (e.g. Glicko-2, custom Elo, decay-tuned OpenSkill) alongside the existing OpenSkill PL champion. Schema-level multi-model support already exists; this skill walks you through the additive steps so you don't break the champion. Use when a contributor wants to plug a new algorithm into the leaderboard. Do NOT use to replace the champion — that's a different operation (CHAMPION_MODEL promotion, see PLAN.md §5.7).
---

# add-rating-model

When invoked, help the user add a new rating-model variant to the project. The schema is already model-agnostic (the `ratings` and `rating_history` tables have a `model_name` discriminator — see [`PLAN.md`](../../../PLAN.md) §5.7). Existing models in the DB: `openskill_pl` (champion), `openskill_pl_vanilla`, `openskill_pl_decay365`. Adding a new one is purely additive — no schema change, no champion replacement, no risk to KC's pipeline.

## Procedure

### 1. Confirm the user's intent

Before writing code, confirm:

- **What's the model name?** Suggest a unique slug like `df_glicko2_v1` or `<contributor>_<algo>_<version>`. It must not collide with `openskill_pl`, `openskill_pl_vanilla`, or `openskill_pl_decay365`. Query the DB to verify:
  ```bash
  sqlite3 phase0.sqlite "SELECT DISTINCT model_name FROM ratings"
  ```
- **Is it a *variant* or a *replacement*?** If the user wants to replace the champion, this skill is the wrong tool — point them to [`PLAN.md`](../../../PLAN.md) §5.7 for champion-promotion semantics. This skill is strictly additive.
- **Pure-Python or new dep?** If new dep, add it to `requirements-phase0.txt` with a pinned minimum version. Justify the choice in the PR description.

### 2. Read the contract

Make sure the contributor has read:

- [`PLAN.md`](../../../PLAN.md) §5.2 — the universal score formula and walkover handling. Reuse `rating.universal_score(...)` for the per-match outcome unless there's a documented reason not to.
- [`PLAN.md`](../../../PLAN.md) §5.7 — model-agnostic schema; `model_name` discriminator semantics.
- `scripts/phase0/rating.py` — the existing OpenSkill engine. Note the shape of `recompute_all(conn, model_name=...)`: read matches chronologically, write `ratings` (current state) and `rating_history` (per-match snapshot) tagged with the model name.

### 3. Implement the model

Create `scripts/phase0/rating_<short>.py`:

- Top-level constant for the model name: `MODEL_NAME = "df_glicko2_v1"` (whatever the user chose).
- `recompute_all(conn, model_name=...)` matching `rating.recompute_all`'s signature and behaviour: chronological read, write rows tagged with `model_name`, audit-log every mutation.
- Reuse `rating.universal_score(...)` for the per-match outcome. If the algorithm needs a different score representation (e.g. Glicko-2 takes binary win/loss), document the deviation with a `# Why:` comment.
- Type hints on public functions; black + ruff formatting; no comments that just explain *what* the code does.

### 4. Wire it into the CLI

Extend `scripts/phase0/cli.py`'s `recompute` subcommand so the user can run:

```bash
python3 -m scripts.phase0.cli recompute --model df_glicko2_v1
```

The `recompute` handler should dispatch on `--model` and call the right module's `recompute_all`. Don't break the default-model behaviour (which still calls `rating.recompute_all` with `CHAMPION_MODEL`).

### 5. Tests

Create `scripts/phase0/test_rating_<short>.py` modelled on `test_rating.py`. Cover at minimum:

- A small synthetic match set with known expected ordering (or known μ/σ values if deterministic).
- A regression test asserting that running the new model does NOT mutate any rows tagged with `openskill_pl` — this catches accidental champion damage.
- A rate-twice-idempotence test: running `recompute_all` twice produces the same final ratings.

Run `pytest scripts/phase0/` to confirm everything still passes.

### 6. (Optional) Surface it in the leaderboard

If the user wants a UI tab toggle so viewers can switch between models on the leaderboard, the additions live in `scripts/phase0/generate_site.py`:

- Replace the single hard-coded `MODEL = "openskill_pl"` constant with a `LEADERBOARD_MODELS` list of `{key, label, model_name}` entries.
- For each entry, run the existing leaderboard query (search for `WHERE r.model_name = ?`).
- Emit one `<table>` per model on `index.html`, only one visible at a time. Tab buttons toggle a CSS class — pure CSS + a few lines of vanilla JS, matching the style of the changelog filter pills (search `.filter.active` in `generate_site.py`).
- Persist the active tab in `localStorage`.
- If a model has zero rated rows yet, render an empty state with the recompute command.

`prompt-for-df-agent.md` at repo root has a worked example of this UI step.

### 7. PR checklist

Before the user opens a PR to `main`, confirm:

- [ ] `pytest scripts/phase0/` passes (existing 222 tests + the new ones).
- [ ] `git diff` does NOT touch `_DATA_/`, `phase0.sqlite`, or anything tagged with `openskill_pl` in committed test fixtures.
- [ ] `python3 scripts/phase0/generate_site.py` succeeds (no Python errors, even if the UI toggle isn't added).
- [ ] PR description references the model name, summarises the algorithm + how it differs from OpenSkill PL, and notes any new pinned deps.
- [ ] User did NOT run `scripts/deploy-site.sh`. Deploy is the maintainer's job ([`CLAUDE.md`](../../../CLAUDE.md) hard rule).

## When NOT to use this skill

- **Replacing the champion model.** That's a `CHAMPION_MODEL` promotion — different semantics, different acceptance criteria. See [`PLAN.md`](../../../PLAN.md) §5.7 and the `rating-engine-expert` agent for guidance.
- **Tuning hyperparameters of an existing model.** That's not a new model, that's a refit. Just edit the constants in `rating.py` and add a regression test.
- **Adding a model that needs schema changes** (e.g. extra per-match feature columns). Propose the schema change in [`PLAN.md`](../../../PLAN.md) §6 first; this skill only handles the schema-as-is path.
