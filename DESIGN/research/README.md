# research/

Dated research artifacts that inform ADRs but are not themselves decisions.

## What lives here

Files in this folder are **research notes, cost analyses, benchmark
comparisons, and option surveys** — the kind of work that produces facts
and projections an ADR's "Options considered" section then summarizes.

Research files are:

- **Dated** — filenames start with `YYYY-MM-DD` so we can tell at a glance
  when the underlying facts were gathered. Pricing, model availability,
  and provider feature parity all change fast; a 6-month-old research
  note is suspicious by default.
- **Source-cited** — every quantitative claim links to where it came from.
- **Single-topic** — one research artifact per question we're answering.
- **Read-only after the ADR they informed is accepted** — refresh by
  writing a new dated artifact, not by editing the old one. The history
  is the point.

## Naming

```
YYYY-MM-DD-<short-slug>.md
```

Examples:
- `2026-04-26-llm-options.md` — informs ADR-023 (chat LLM) and ADR-025 (ingestion LLM)
- `2026-XX-XX-postgres-managed-vs-self-hosted.md` — would inform ADR-014 if revisited
- `2026-XX-XX-chat-eval-baseline.md` — would inform ADR-024 thresholds

## Lifecycle

```
draft (in flight)  →  complete (informs an ADR)  →  superseded (newer dated note exists)
```

A research note is `superseded` *implicitly* when a newer dated artifact
on the same topic exists. We don't move or delete superseded notes — they
stay as historical context for why the corresponding ADR was decided
the way it was at the time.

## Index

| Date | Topic | Informs |
|---|---|---|
| 2026-04-26 | [LLM options — providers, pricing, projected cost](2026-04-26-llm-options.md) | ADR-023 (chat), ADR-025 (ingestion) |
