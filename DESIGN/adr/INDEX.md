# ADR index

The full roster of architecture decisions for the public-site phase of
RallyRank. Numbers are assigned at draft-time and never re-used. Status
flows: `proposed → accepted → superseded`.

Topical grouping is for human readability; the file numbering is purely
chronological.

## Trust, legality, privacy (highest stakes — drive everything else)

| # | Title | Status | Drives |
|---|---|---|---|
| 002 | Player consent model — opt-in vs opt-out vs public-by-default | not drafted | schema, visibility matrix, takedown SOP |
| 003 | Visibility matrix — who sees what (anon / member / captain / admin) | not drafted | API response shaping, page specs |
| 004 | Player real-name display — full / initials / handle | not drafted | every player-facing UI |
| 005 | Disagreement / takedown channel | not drafted | privacy.md, runbooks |
| 006 | Audit retention vs GDPR right-to-erasure | not drafted | schema (audit_log handling), privacy.md |

## Architecture & operations

| # | Title | Status | Notes |
|---|---|---|---|
| 001 | [Design-first process for the public site](001-design-first-process.md) | accepted | Meta-decision; this dossier exists |
| 007 | [API as standalone service (amends PLAN.md §4)](007-api-as-standalone-service.md) | proposed | Driven by `/src` layout + native-app future |
| 008 | [API language: FastAPI / Python](008-api-language-fastapi.md) | proposed | Driven by Python rating engine + WS support |
| 009 | Auth strategy: JWT bearer + refresh (web + native) | not drafted | Native future kills cookie-only auth |
| 010 | Realtime: SSE for chat streaming, WS for bidirectional | not drafted | Most "I need WS" is actually SSE |
| 011 | GraphQL deferred — REST + OpenAPI is the contract | not drafted | Records the deferral + revisit-trigger |
| 012 | Contract source-of-truth: OpenAPI YAML → TS + Python codegen | not drafted | Webapp + native + chat all consume |
| 013 | Monorepo tooling | not drafted | pnpm + uv vs Turborepo vs minimal |
| 014 | [Hosting + ingress: Proxmox LXC + Cloudflare Tunnel](014-hosting-cloudflare-tunnel.md) | proposed | Portable to Hetzner with config-only changes |
| 015 | Backup + DR — encrypted off-site, quarterly restore test | not drafted | Untested backups don't exist |
| 016 | Quality bar — production-grade from day 1 (definition) | not drafted | Drives test/CI/observability scope |
| 017 | API versioning + deprecation policy | not drafted | `/api/v1/` from day 1; OpenAPI as truth |
| 018 | Performance SLOs — concrete numbers | not drafted | TTFB, chat p50, leaderboard load, query caps |
| 019 | Observability — log format, metrics catalog, alerts | not drafted | Self-hosted vs Sentry-hosted |

## Data & UX semantics

| # | Title | Status | Notes |
|---|---|---|---|
| 020 | URL strategy — player permalinks, slug rules, merge handling | not drafted | 301 from merged-away IDs; SEO stability |
| 021 | Caching strategy — ISR per page type, invalidation triggers | not drafted | "ratings_updated" pub/sub → cache flush |
| 022 | Snapshot semantics — historical "as of" queries vs live-only | not drafted | Affects rating-history immutability story |

## Chatbot

| # | Title | Status | Notes |
|---|---|---|---|
| 023 | Chat architecture — LLM provider, tool-calling, auth, cost cap, retention | not drafted | Champion: Anthropic Sonnet 4.6; informed by [research](../research/2026-04-26-llm-options.md) |
| 024 | Chat safety — prompt injection, hallucination, citation, eval | not drafted | Eval threshold required before launch |
| 025 | Ingestion LLM strategy | not drafted | Champion: Anthropic Sonnet 4.6 + Batch API; informed by [research](../research/2026-04-26-llm-options.md) |

## Reserved / parking lot

Numbers reserved for ADRs we know we'll need but haven't yet drafted.
Add to this section rather than the topical sections above when the
trigger to write it hasn't arrived yet.

(none currently)

## Order of work

The two **leftmost** prerequisite groups gate everything else:

1. **Trust + legality (002–006)** — needs stakeholder input (committee?
   external lawyer?). Schedule a longer planning session.
2. **Architecture commitment (007, 008, 014)** — drafted in this batch,
   pending acceptance.

Once both are settled, the remainder can be drafted largely in parallel.
