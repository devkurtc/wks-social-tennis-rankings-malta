# ADR-014: Hosting + ingress — Proxmox LXC + Cloudflare Tunnel, portable to Hetzner

- **Status:** proposed
- **Date:** 2026-04-26
- **Deciders:** Kurt
- **Related:** ADR-015 (backups), ADR-016 (quality bar), `../../PLAN.md`
  §5.6, `../architecture.md`

## Context

The 2026-04-26 conversation locked the deployment posture:

- **Today:** self-hosted on a Proxmox LXC running on Kurt's home machine
- **Future:** migrate to a always-on host (Hetzner Helsinki / Falkenstein
  was named as a likely candidate)
- **Constraint:** the migration should be a config change, not a re-platform

PLAN.md §5.6 already commits to Proxmox LXC + docker-compose + Caddy as
the deploy shape. This ADR refines the ingress and portability story
specifically for a public-facing site, and supersedes the implicit
"Caddy + port-forward" assumption.

The two structural decisions that shape this ADR:

1. **Home network constraints** — exposing port 443 from a home router
   to the public internet introduces a real attack surface (open port
   on a residential ISP IP, no DDoS protection, no WAF, ISP TOS issues
   in some jurisdictions, dynamic IP if ISP doesn't offer static)
2. **Host portability** — the entire system (compose + volumes + secrets)
   must move to Hetzner without changing the public hostname, the TLS
   certificate, or anything DNS-visible

## Decision drivers

- **No inbound ports on home network** — public exposure of a residential
  IP is a security and operational liability we can avoid for free
- **Identical public surface across hosts** — DNS, hostname, and TLS
  must not change when migrating
- **GDPR / data residency** — Malta is EU; the future host should also
  be EU to avoid Standard Contractual Clauses overhead. Hetzner Helsinki
  and Falkenstein both qualify
- **Cost** — must be cheap at home (free apart from electricity) and
  cheap on the future host (target: under €15/month all-in)
- **Operational simplicity** — single maintainer; no exotic networking,
  no BGP, no manual DNS toggling at migration

## Options considered

### Option 1: Port-forward 443 from home router → Caddy in LXC

**Pros**
- Conceptually simple
- No third-party ingress dependency
- Caddy handles automatic Let's Encrypt TLS

**Cons**
- Exposes home IP publicly — privacy and security concern
- Subject to ISP outages, residential IP blocklists, dynamic IP
  unless ISP offers static
- No DDoS protection; no WAF; no rate-limiting at edge
- Migration to Hetzner requires re-issuing TLS, repointing DNS, re-IPing
- Some residential ISPs (in Malta and elsewhere) prohibit running public
  servers — TOS risk

### Option 2: Cloudflare Tunnel (cloudflared) + Cloudflare DNS

**Pros**
- **Zero inbound ports** on home router — `cloudflared` opens an
  outbound TCP connection to Cloudflare edge; all traffic flows that
  way. No ISP TOS issue, no DDoS exposure, no IP leakage
- **Free tier** is more than sufficient for this app's traffic
- **Free WAF + rate-limit + bot management** at the edge
- **TLS terminated at Cloudflare**; origin can run plain HTTP internally
  (or HTTPS with a self-signed cert that CF trusts)
- **Migration is a config change** — start `cloudflared` on Hetzner with
  the same tunnel ID, stop it at home; DNS unchanged, TLS unchanged,
  hostname unchanged
- Hides origin IP — no surface for direct attacks bypassing CF
- CF Access available later if we want zero-trust admin endpoints (per
  PLAN.md §5.6 future hardening)

**Cons**
- Adds Cloudflare as an ingress dependency (CF outage = site down)
- DNS must be on Cloudflare (acceptable; they're a competent registrar / DNS host)
- Tunnel client (`cloudflared`) is one more container to operate
- Some real-time / high-bandwidth use cases hit CF tunnel quotas; this
  app is nowhere near that scale

### Option 3: WireGuard tunnel from home → cheap Hetzner VPS as ingress

**Pros**
- No third-party ingress dependency beyond a VPS we control
- Hides home IP
- Migration to Hetzner main host = stop the tunnel, run docker-compose on
  the Hetzner main host directly
- Full control of WAF / rate-limit (or none — your choice)

**Cons**
- Need to operate, patch, and monitor the WireGuard VPS — more ops surface
- No free DDoS protection unless we layer Cloudflare on top anyway
- More moving parts (WG configs, key rotation, firewall rules) for the
  same outcome as Option 2
- Cost: ~€4/month for the VPS — still cheap, but not free

### Option 4: Tailscale Funnel

**Pros**
- Tailscale is excellent UX
- Free tier covers basic public exposure

**Cons**
- Less mature than Cloudflare Tunnel for production public sites
- Tailscale account becomes a hard dependency for ingress
- Funnel feature is newer; long-term pricing uncertain

## Decision

> RallyRank uses **Cloudflare Tunnel** for ingress in all environments.
> A `cloudflared` container runs alongside the application stack in
> `infra/docker-compose.yml`. The Cloudflare-managed DNS zone and the
> tunnel ID are environment-stable across hosts. Migration from Proxmox
> (home) to Hetzner is a tunnel-restart on the new host.

Option 2. The portability win and the elimination of inbound port exposure
together make Cloudflare Tunnel decisively the right choice for a
public-facing site that needs to be host-agnostic. The CF dependency is
real but acceptable: Cloudflare's uptime track record is strong, and the
free tier removes any cost lock-in concern. ADR-019 (observability)
will include CF tunnel health as a monitored signal.

## Consequences

### Enables

- Home router has zero open inbound ports — public surface is exclusively
  Cloudflare edge
- DNS, TLS certificate, and hostname are migration-invariant — moving
  hosts is a `cloudflared` restart on the new host
- Free edge WAF / rate-limit / bot management — useful baseline before
  any in-app rate-limiting design
- CF Access available if we later want zero-trust admin login (no
  password page, just CF identity check at the edge)
- Origin IP is hidden — eliminates a class of direct-to-origin DDoS
  vectors

### Constrains / costs

- Cloudflare is an ingress dependency. CF outage = site down. Mitigation:
  CF's SLA is very high; the worst-case mitigation is point DNS away from
  CF Tunnel temporarily — but doing so exposes the origin, so it's an
  emergency-only path
- DNS must be on Cloudflare (or use CF Tunnel + external DNS, which is
  awkward; just use CF DNS)
- `cloudflared` container is one more component to monitor (added to
  ADR-019's monitoring catalog)
- WebSocket and SSE through CF Tunnel work but are subject to CF's
  connection-time limits; at our scale this is not a constraint, but
  worth knowing
- Long-running uploads (admin file uploads in Phase 3) must complete
  within CF's request-time limits; chunked-upload design may be needed
  if ingestion files exceed the limit (current files are <5MB so this
  is theoretical)

### Revisit triggers

- **Cloudflare changes free-tier terms** in a way that materially
  affects this app → migrate to Option 3 (WireGuard + small VPS) without
  changing the rest of the architecture
- **A use case requires bidirectional, low-latency networking** that
  CF Tunnel can't carry well (e.g., large WebRTC, very long-running
  file uploads) → revisit per-use-case, possibly with a direct
  ingress for that one path
- **CF outage causes user-visible downtime more than once per quarter**
  → evaluate multi-ingress posture (e.g., Cloudflare primary, WireGuard
  failover)

## Validation

This decision is working if:

- Home router shows zero open inbound ports in a port scan
- A planned host migration (Proxmox → Hetzner) takes under 30 minutes
  of user-visible downtime, with no DNS, TLS, or hostname changes
- CF tunnel uptime is >99.9% measured monthly
- No origin IP appears in any public DNS / certificate-transparency log
- Admin file uploads (Phase 3) complete reliably for files up to 50MB

## Related work

- ADR-015 — Backup + DR (off-site backups, encrypted, restore-tested)
- ADR-016 — Quality bar (CF tunnel health monitored from day 1)
- ADR-019 — Observability (cloudflared health, CF analytics integration)
- `../architecture.md` — deployment topology diagrams
- `../../PLAN.md` §5.6 — original deploy plan, now refined here
- TASKS.md (TBD): "T-P1-INFRA-001 — Set up Cloudflare account, tunnel,
  domain; produce repeatable bootstrap script"
