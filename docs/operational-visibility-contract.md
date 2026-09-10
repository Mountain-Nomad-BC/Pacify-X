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

## Observer input boundary

Observer consent is an actual immutable `ObserverConsent` record. Grants are
actual Booleans; count, byte and duration limits are actual positive integers,
with ceilings of 10,000 events, 16 MiB and 3,600 seconds. Allowed effects are a
unique tuple of one to four registered effect names. A syntactically valid
consent record does not establish who authorized it.

Consent and command plans carry a unique tuple of one to 16 opaque scope
references. Observations carry the same references as an actual list and must
remain within consent. Supported forms are:

- `process-id:` followed by a canonical positive decimal PID up to 4,294,967,295;
- `executable-sha256:`, `path-sha256:` or `endpoint-sha256:` followed by 64 lowercase
  hexadecimal characters;
- `project:` followed by one to 128 ASCII letters, digits, underscores, dots or
  hyphens, starting with a letter or digit.

These are reference grammars, not proofs of process identity, executable bytes,
path ownership, endpoint identity or native collection filtering. Native plans
still require their authoritative admission and identity checks.

Observer scalar metadata is actual nonempty UTF-8 text bounded to 160 bytes;
scope references are bounded to 200 bytes. Observation records have exactly five
fields. The validator returns a detached scope list and refuses malformed or
out-of-scope data before copying it. Operation names and observation identities
remain supplied metadata; their shape does not attest content provenance.

Plan input validation precedes hashing: exactly three command profiles, one to
32 tuple arguments per profile, at most 4,096 UTF-8 bytes per argument and 16 KiB
across arguments. These bounds do not authenticate command content or prevent
later mapping mutation. Builders validate scope before executable discovery or
watched-directory access. Existing canonical command hashes remain unchanged.

Timestamp parsing requires bounded actual text and an explicit timezone.
Optional comparison clocks must be aware datetimes; freshness switches are
actual Booleans. Capture batch limits are actual integers from one to 1,000.
This input boundary does not establish observation chronology within a consent
window, autonomous lease expiry, restart recovery, bounded decoder execution or
real operating-system collection. Those remain separate lifecycle and assurance
obligations.
