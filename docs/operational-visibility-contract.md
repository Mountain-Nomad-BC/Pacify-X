# Operational visibility contract

Status: implementation baseline for punch card `F03`  
Canonical event identity: `px.operation-event/1`

## Promise

PACIFY-X reports complete visibility only over its admitted execution routes. Each
advertised route must be registered and classified as exactly one coverage tier:

- `A` — PX mediates the operation and emits an authoritative receipt.
- `B` — an independent, health-reporting observer sees the operation, with declared
  platform and loss limits.
- `C` — the actor or provider self-reports a correlated, integrity-checkable
  attestation.
- `D` — the route is unobserved, unsupported, unhealthy, or not configured.

Tier D is a first-class visible state. An admitted Tier-D route blocks claims that
the system is fully observed, safe, idle, free, or complete.

## Truth rules

1. Unknown stays `unknown`; it is never converted to zero, free, idle, healthy, or
   complete.
2. Declared effects and observed effects are separate fields.
3. Actor, task, claim, orchestration, provider, request, and budget identities are
   correlated when known and explicitly null when unknown.
4. Timestamps carry source and freshness state; wall-clock ordering alone is not
   treated as causality.
5. Payload content is excluded by default. Metadata, bounded references, and
   cryptographic digests are preferred.
6. Every observer reports health, consent state, dropped-event information where
   the platform exposes it, and its blind spots.
7. No UI may claim stronger coverage than the canonical registry and current
   observer-health projection support.

## Irreducible limits

PACIFY-X cannot truthfully expose private model reasoning, encrypted content it
does not terminate, activity on uninstrumented hosts, provider billing facts a
provider does not expose, or actions deliberately taken outside admitted routes.
It can expose those boundaries, missing attestations, stale sensors, and coverage
gaps. “Universal visibility” therefore means universal accounting of admitted
routes, including visible uncertainty—not omniscience.

## Admission and certification

An execution route is admitted only when its registry entry declares its owner,
effect classes, instrumentation mechanism, coverage tier, observer health,
consent requirement, blind-spot state, retention class, and acceptance evidence.
Certification fails if an advertised route is absent, a tier/mechanism pairing is
invalid, or a Tier-D route remains in the release scope.

