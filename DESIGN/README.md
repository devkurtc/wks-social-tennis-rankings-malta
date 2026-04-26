# DESIGN — RallyRank public-site design dossier

This folder is the reviewable design surface for RallyRank's public-facing
site. It exists because the public surface must be **rock-solid from day 1**
(decided 2026-04-26): consent, privacy, security, performance, and
trust-signal design have to be locked before code is written, not retrofitted
after launch.

`PLAN.md` remains the canonical project plan. This folder records the
*public-site-specific* architectural decisions in a format optimized for
incremental review, amendment, and traceability.

## What lives here

| Path | Purpose |
|---|---|
| `README.md` | This file. Workflow, conventions, index pointer. |
| `repo-layout.md` | The `/src` source tree, with each folder's responsibility. |
| `architecture.md` | C4-style component + deployment diagrams. Updated per accepted ADR. |
| `diagrams.md` | Visual atlas — domain model, lifecycles, user journeys, security zones, failure modes. Complements `architecture.md`. |
| `adr/INDEX.md` | Numbered index of every architectural decision (proposed and accepted). |
| `adr/000-template.md` | Blank template for new ADRs. |
| `adr/NNN-<slug>.md` | One file per architectural decision. |
| `contracts/` | OpenAPI spec, event schemas, auth flows — populated when ADR-012 is accepted. |
| `pages/` | Per-page wireframes / specs — populated when visibility matrix lands. |
| `runbooks/` | Incident playbooks — grows over time as services come online. |
| `research/` | Dated research artifacts (cost analyses, benchmarks, option surveys) that inform ADRs but aren't themselves decisions. See `research/README.md`. |
| `threat-model.md` | STRIDE-lite walkthrough — populated when the API contract is drafted. |
| `privacy.md` | GDPR / consent / data-residency policy — populated by ADR-002 + ADR-006. |
| `chat-eval.yaml` | Golden Q&A set the chatbot must pass to ship — populated by ADR-024. |
| `quality-bar.md` | Definition of "production-grade from day 1" — populated by ADR-016. |
| `perf-budget.md` | Concrete SLOs, query caps, LLM cost ceilings — populated by ADR-018. |

Files marked "populated when" are deliberate placeholders — they exist so
the dependency graph between artifacts is visible and gaps don't hide.

## ADR workflow

Architecture Decision Records follow this lifecycle:

```
proposed  →  accepted  →  superseded
                    ↘  deprecated
```

- **proposed** — drafted, open for discussion. Title prefixed `[draft]` until accepted.
- **accepted** — locked. Changing requires a new ADR that supersedes it.
- **superseded** — replaced by a newer ADR. Kept in repo for history; `Status` line links the replacement.
- **deprecated** — removed without replacement (rare). Kept for context.

Every ADR has the same structure (see `adr/000-template.md`):

1. **Context** — the situation forcing a decision
2. **Decision drivers** — the forces in play (constraints, qualities to optimize)
3. **Options considered** — at least two, each with explicit pros/cons
4. **Decision** — the choice + one-paragraph rationale
5. **Consequences** — what this enables, what it constrains, the explicit *revisit triggers* that would re-open the decision
6. **Related** — links to other ADRs, PLAN.md sections, external references

The "consequences" section is the most important one. It's what stops us
six months from now from re-litigating settled decisions, and it's what
tells us when a decision has actually expired.

## Numbering

ADRs are numbered globally and never re-used. Numbers reflect *creation
order*, not topic. Topical grouping happens in `adr/INDEX.md`. Gaps are
fine (some numbers will be reserved during planning then never written —
we'd rather have gaps than renumber).

## Amending vs superseding

- **Typo / clarification / new revisit-trigger** → edit in place, note in
  `Status` line ("accepted 2026-04-28, clarified 2026-05-10").
- **Decision changes** → write a new ADR; mark the old one `superseded by
  ADR-NNN`. Never edit an accepted ADR's *Decision* in place.

## Validation gates

Three gates the public site must pass before launch (per design-first
commitment):

1. **Design-complete review** — every ADR in `INDEX.md` is accepted; OpenAPI
   spec lints clean; threat model has mitigations for every "high" item;
   visibility matrix has zero `?` cells.
2. **Chat-eval baseline** — `chat-eval.yaml` runs against the prototype
   and meets the threshold defined in ADR-024.
3. **Security review** — full review of auth, rate-limiting, prompt-injection
   defenses, GDPR, PII handling. Required before public DNS goes live.

## Related

- `../PLAN.md` — canonical project plan; ADRs amend it explicitly when
  they change a locked decision.
- `../TASKS.md` — operational task tracker; design work produces tasks
  but doesn't replace the tracker.
- `../CLAUDE.md` — agent orientation; references this folder.
