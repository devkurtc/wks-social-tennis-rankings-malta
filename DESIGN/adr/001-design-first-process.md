# ADR-001: Design-first process for the public site

- **Status:** accepted
- **Date:** 2026-04-26
- **Deciders:** Kurt
- **Related:** `../README.md`, `../../PLAN.md` §1, §7

## Context

RallyRank's Phase 0 (local proof of concept) is complete: the rating
model, the schema, the parsers, and the CLI all work against real VLTC
data. Phases 1–5 in PLAN.md §7 take RallyRank from local prototype to
self-hosted public web app, agentic ingestion, and a chatbot.

The Phase 0 work was rightly hack-friendly: SQLite, hand-written parsers,
CLI-only, no auth, no public surface. That latitude does not transfer to
the public site. The public site is customer-facing — actual people will
read other people's tennis ratings on it, dispute them, share them, and
form opinions about each other from them. It also exposes a Claude-backed
chatbot, which means cost control, prompt-injection defense, and
hallucination guardrails are first-class concerns.

The instinct on a fresh phase is to start prototyping immediately. For
this app, that instinct produces predictable failures: privacy decisions
made silently by code, API contracts that aren't versioned, auth grafted
onto endpoints after the fact, chatbot tools shaped by what's easy rather
than what's safe. Each of those is cheap to design upfront and expensive
to retrofit after launch.

## Decision drivers

- **Public exposure** — real people, real reputations, real GDPR scope
  (Malta = EU). Mistakes are visible and persistent.
- **Multi-client API** — webapp now, native app later. The API contract
  is the durable interface; it deserves design attention disproportionate
  to its line count.
- **LLM-backed surface** — chatbot introduces cost, safety, and trust
  concerns that don't exist in conventional CRUD apps.
- **Single-maintainer reality** — Kurt is the primary author. Decisions
  must be recorded so future-Kurt (and any future contributor) doesn't
  re-litigate them.
- **"Great from day 1, not MVP mode"** — explicit framing from the
  2026-04-26 conversation. The public site's first version is the
  reference standard, not the throw-away spike.

## Options considered

### Option 1: Code-first — start building Phase 1, design as we go

**Pros**
- Faster to first visible deliverable
- "Designing on paper" risk: producing artifacts no one references
- Forces decisions to be concrete (you can't punt when the code needs them)

**Cons**
- Privacy / consent / auth decisions made implicitly by the first
  developer who needs them — typically in the wrong direction
- Native-app future not honored — easy to hard-couple API to webapp
- Chat safety / cost design done under deadline pressure
- Refactoring cost compounds; "we'll fix it later" rarely happens

### Option 2: Design-first with ADRs — lock decisions before code

**Pros**
- Privacy, auth, contract, and chat safety designed deliberately
- ADRs are reviewable, amendable, and survive contributor turnover
- Mistakes are caught at design review (cheap) not deploy review (expensive)
- Native-app future is structurally honored from the first endpoint
- Stakeholder input (consent model, real-name display) can happen async

**Cons**
- Slower to first visible deliverable
- Risk of analysis paralysis — design phase that never ends
- Risk of producing artifacts that diverge from the eventually-built code

### Option 3: Hybrid — design the high-stakes layers, prototype the rest

**Pros**
- Compromise; design where it matters, code where it doesn't
- Parallel progress

**Cons**
- "High-stakes" definition drifts under deadline pressure
- Hard to draw the line between layers; everything ends up touching auth
  or privacy somehow
- Loses the legibility of either pure approach

## Decision

> RallyRank's public site (Phase 1+) follows a design-first process.
> Architectural decisions are recorded as ADRs in `DESIGN/adr/` and must
> reach `accepted` status before code that depends on them is written.

Option 2. The "great from day 1" framing rules out Option 1; the legibility
loss of Option 3 isn't worth the parallel progress when there's a single
maintainer. The design phase is bounded by the gates in `DESIGN/README.md`:
all ADRs accepted, OpenAPI spec lints clean, threat model mitigations in
place, chat-eval threshold defined, security review scheduled. When those
gates pass, code begins.

## Consequences

### Enables

- Decisions are amendable, not lost — supersede with a new ADR
- New contributors can read `DESIGN/` and understand why things are the
  way they are without spelunking git history
- Stakeholder review (consent, visibility) can happen async on individual
  ADR PRs without blocking other planning
- Native-app slot in `src/native/` is a structural reality from day 1
- Chatbot safety isn't an afterthought — it has its own ADR (#024) and
  its own validation gate (chat-eval)

### Constrains / costs

- Phase 1 starts later than it would under code-first
- Some design effort will be wasted if reality changes (e.g., we draft
  ADR-014 hosting, then change hosts six months later — superseded ADR
  is the cost)
- Discipline required: drift to "I'll just code it" must be resisted on
  any decision that affects auth, privacy, contract, or chat

### Revisit triggers

- **Phase 1 stalls in design** with no movement toward code for >4 weeks
  → review which ADRs are blocking and consider scope-cutting; do not
  abandon the process, but tighten its scope
- **A second maintainer joins** → review whether the ADR format is
  serving them or getting in the way
- **A decision recorded in an ADR turns out to be wrong in a way that
  the ADR's "validation" section didn't catch** → improve the validation
  section template

## Validation

This process is working if:

- Every public-site PR cites the ADR(s) it depends on
- No public-site decision is made in code without a corresponding ADR
  (or an explicit "no ADR needed because X" note)
- Stakeholder feedback on consent / visibility lands on specific ADRs,
  not buried in chat threads
- The first security review (gate 3) finds zero "obvious" issues — all
  issues are subtle, second-order, or policy-level

## Related work

- `../../PLAN.md` §7 — phased roadmap; this ADR scopes the design phase
  inserted before Phase 1 implementation
- `../../TASKS.md` — design tasks added per ADR; track here
