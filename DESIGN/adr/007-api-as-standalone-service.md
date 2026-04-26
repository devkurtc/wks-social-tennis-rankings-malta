# ADR-007: API as a standalone service (amends PLAN.md §4)

- **Status:** proposed
- **Date:** 2026-04-26
- **Deciders:** Kurt
- **Supersedes:** the API-routes-inside-Next.js shape implied by PLAN.md §4
- **Related:** ADR-008 (API language), ADR-009 (auth), ADR-010 (realtime),
  ADR-014 (hosting), `../repo-layout.md`, `../../PLAN.md` §4, §5.1

## Context

PLAN.md §4 sketches the architecture as Next.js (web + API routes) +
Python worker for the rating engine, communicating via Redis. That shape
made sense when the design assumed a single web client.

The 2026-04-26 conversation locked two new constraints:

1. **Code lives in `/src/services` (plural) and `/src/webapp`.** The
   plural folder name signals multiple backend services, not a monolith.
2. **A native app is a planned future client.** Even if not built in
   Phase 1, the design must not preclude it.

Next.js API routes are tightly coupled to the Next.js runtime: server
actions, RSC-coupled fetches, and Next-specific middleware are great for
a web client and hostile to anything else. A native client would either
have to call those routes as if they were a generic HTTP API (giving up
the Next-specific conveniences anyway) or get its own separate API
service (creating two API surfaces to maintain).

## Decision drivers

- **Native-client future** — the API must be plain HTTP/JSON consumable
  by any client without Next.js-specific assumptions
- **Service ownership clarity** — putting API logic inside the webapp
  blurs which team / file owns "the public contract"
- **Language fit** — the rating engine and ingestion agent are Python
  (locked in PLAN.md §5.2 / §5.3). API in Python means no service-boundary
  cross when the API needs to compute or read rating math
- **Independent scaling and deployment** — UI deploys (frequent, low-risk)
  versus API deploys (less frequent, higher-risk) should not be coupled
- **Realtime surface** — SSE for chat streaming + WS for live updates
  (per ADR-010) is cleaner in a dedicated long-running server than in
  a Next.js function-shaped runtime

## Options considered

### Option 1: API inside Next.js (PLAN.md §4 status quo)

**Pros**
- Single deployable for the web stack
- Shared types between API and UI feel native (no codegen)
- Next.js middleware chain is unified for both

**Cons**
- Native client gets a generic HTTP API anyway, losing the "shared
  types" benefit
- Server actions / RSC-coupled fetches discourage building a clean
  HTTP contract — easy to ship endpoints that are awkward for non-Next
  clients
- Long-running connections (SSE, WS) are awkward in serverless-style
  Next.js handlers; possible but fights the framework
- Cross-language calls to the Python rating engine become inter-service
  hops (Next.js → Redis/HTTP → Python worker) for every rating-aware
  request

### Option 2: API as a standalone service in `src/services/api`

**Pros**
- API is a first-class service with its own lifecycle, tests, and deploy
- Native client and webapp consume the same contract — no second surface
- Long-running connections (SSE, WS) are natural in a dedicated server
- API can be co-located with the rating engine in Python (per ADR-008),
  eliminating one service hop for every rating-aware request
- Webapp becomes a pure UI concern — easier to reason about, easier
  to swap frontend frameworks if ever needed
- Matches the `/src/services` (plural) folder commitment naturally

**Cons**
- Two deployables (webapp, api) instead of one — slightly more deploy
  orchestration
- Webapp ↔ API is now a network call (loopback in dev/prod, but still
  a real protocol boundary)
- TypeScript types in webapp must be generated from OpenAPI rather than
  imported directly — codegen step to maintain

### Option 3: BFF (Backend-for-Frontend) — Next.js routes proxy to Python API

**Pros**
- Webapp gets typed Next.js routes with native conveniences
- Python API still exists for the native client

**Cons**
- Two API surfaces to keep in sync (BFF endpoints + underlying Python API)
- Doubled testing surface
- Extra hop on every request adds latency for no clear benefit at our scale
- Tends to drift: webapp-only logic creeps into the BFF, then the native
  client either misses features or has to re-implement them

## Decision

> The public API lives in `src/services/api/` as a standalone service,
> separate from the Next.js webapp. The webapp is UI-only and consumes
> the API over HTTP using a generated client. There are no Next.js API
> routes, server actions, or RSC fetches that bypass the API service.

Option 2. The native-client future and the Python-language alignment
together make Option 1's "shared types" win illusory and Option 3's BFF
overhead unjustified. The cost we accept is one network boundary between
webapp and api (negligible on loopback) and a codegen step for the
TypeScript client (which we'd need for the native client regardless).

## Consequences

### Enables

- Native client (when built) consumes the exact same API as the webapp,
  with the exact same auth, with no second contract to maintain
- API can ship realtime endpoints (SSE, WS) without fighting framework
  assumptions
- API can call directly into the Python rating engine without going
  through Redis/HTTP for synchronous reads
- Webapp deploys are decoupled from API deploys (smaller blast radius
  per release)
- The contract becomes a first-class artifact (OpenAPI in
  `src/contracts/openapi.yaml`) instead of a side-effect of route files

### Constrains / costs

- Two services to deploy, monitor, and version (mitigated by docker-compose
  orchestration — see ADR-014)
- TypeScript types are generated, not authored — adds a build step to
  webapp CI
- Loopback HTTP call between webapp SSR/RSC and API service — must be
  fast (sub-5ms) to not affect TTFB; this is realistic on the same host
- Authentication is now a cross-service concern (cookie domain or token
  forwarding) — handled in ADR-009

### Revisit triggers

- **OpenAPI codegen breaks down** for our use cases (e.g., file uploads,
  streaming responses can't be expressed cleanly) → consider hand-writing
  the TS client and capturing the contract another way
- **Webapp ↔ API loopback latency exceeds 10ms p99** in production →
  revisit co-location (e.g., move webapp into the same network namespace
  more aggressively, or revisit framework choice)
- **A second client needs a different shape** of the same data badly
  enough that we're considering BFF endpoints → write ADR-011's GraphQL
  revisit instead

## Validation

This decision is working if:

- The OpenAPI spec in `src/contracts/openapi.yaml` is the only source of
  truth for endpoints — no "shadow" endpoints in the webapp
- The native-client epic, when it lands, requires zero new endpoints
  (only new UI consuming existing endpoints)
- Webapp and API can be deployed independently without breaking the
  other (with the obvious caveat of contract version compatibility)
- Loopback p99 between webapp SSR and api stays under 10ms

## Related work

- ADR-008 — API language (FastAPI / Python)
- ADR-009 — Auth strategy (token-based, works for web + native)
- ADR-010 — Realtime: SSE + WS in the API service
- ADR-012 — Contract source-of-truth: OpenAPI codegen pipeline
- `../repo-layout.md` — `src/services/api/` folder responsibilities
- TASKS.md (TBD): "T-P1-001 — Scaffold src/services/api with health
  endpoint and OpenAPI generation"
