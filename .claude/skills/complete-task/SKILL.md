---
name: complete-task
description: Mark a TASKS.md task as done. Walks through every acceptance criterion, verifies it against actual repo state (running commands as needed), and only flips status to `done` if every one is genuinely satisfied. Appends the final progress-log line. Optionally accepts a commit SHA reference. Refuses to mark done if any criterion is unmet — goalpost-moving destroys multi-agent trust.
---

# complete-task

When invoked with `<task-id> [<commit-sha>]`:

1. **Find the task** in `TASKS.md`. If not found, abort.

2. **Validate current status** is `in-progress`. If it's `todo`, abort with "task wasn't picked up — use `/pickup-task` first." If it's `done` or `deferred`, abort accordingly.

3. **Walk every acceptance criterion** listed under `**Acceptance criteria:**`:
   - For each `- [ ]` item, verify it against actual repo state. Use Read, Bash, Grep, etc. as needed — don't assume from memory.
   - If a criterion is genuinely satisfied: change `- [ ]` to `- [x]` in TASKS.md.
   - If a criterion is *not* satisfied (or you can't verify it): **abort**. Report which one failed and why. Do not edit anything.

4. **If all criteria pass:**
   - Change `**Status:** \`in-progress\`` to `**Status:** \`done\`` for the task.
   - Append a final progress-log line:
     `- YYYY-MM-DD HH:MM — <actor> — completed; <one-line summary>[; commit <sha>]`
   - Update the `## Current focus` table at the top of TASKS.md:
     - Remove the task from `in-progress`
     - Add to `recently done` (keep the 5 most recent)
     - Re-evaluate which tasks are now `up next` (deps may now be satisfied)
   - If this task is in the "Done" section's responsibility (the very bottom of TASKS.md), ALSO add a one-line entry there under the Done heading.

5. **Print** the final state of the task and a summary of which acceptance criteria were just verified.

## Hard rules

- **Never silently change an acceptance criterion to make it pass.** If the criterion is wrong, log a progress note explaining the deviation, edit the criterion text with a `(modified: reason)` annotation, and only then check it. Document the change in the same progress note.
- **Never mark `done` without verification.** If you can't run the verification (e.g. the task says "Kurt confirms rankings look right" and Kurt isn't here), abort and report.
- **Never modify past progress-log entries.** New "completed" line is always *appended*.

## Examples

```
/complete-task T-P0-001 abc1234
→ Walks through 6 acceptance criteria:
   ✓ scripts/phase0/ exists with __init__.py
   ✓ cli.py exists with stub subcommands
   ✓ scripts/phase0/README.md exists
   ✓ requirements-phase0.txt exists with required deps
   ✓ .gitignore updated for phase0.sqlite + .venv
   ✓ python scripts/phase0/cli.py --help runs cleanly
→ All pass. Edits TASKS.md:
   - Status → done
   - All criteria checked
   - Progress log appended:
     "- 2026-04-25 22:00 — Claude (Opus 4.7) — completed;
      scripts/phase0 scaffold + argparse stub CLI; commit abc1234"
   - Moved from in-progress to recently done in Current focus
```

```
/complete-task T-P0-002
→ Acceptance criterion #4 ("scripts/phase0/db.py init_db idempotent")
   not verifiable — function not found at scripts/phase0/db.py.
→ ABORT. Status remains `in-progress`. Report:
   "Criterion 4 unmet: scripts/phase0/db.py does not exist or does
    not export init_db. Implement before re-running /complete-task."
```
