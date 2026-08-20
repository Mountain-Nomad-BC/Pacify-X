# Operational visibility threat, privacy, and consent model

Status: implementation baseline for punch card `F04`

## Protected assets

- user source, prompts, terminal text, model input/output, credentials, and secret
  values;
- correlation identities, activity timelines, billing records, and operator
  decisions;
- ledger heads, receipts, observer health, configuration, and retention policy.

## Principal threats and controls

| Threat | Required control | Failure presentation |
|---|---|---|
| Spoofed agent/provider event | authenticated or locally mediated source, correlation ownership, integrity digest | unattested / Tier D |
| Missing or disabled listener | route reconciliation and observer heartbeat | degraded with named blind spot |
| Dropped/reordered events | sequence, previous-event digest, drop counters, replay boundary | incomplete ancestry |
| Secret capture | metadata-only default, field allowlist, value prohibition, export redaction tests | capture refused |
| Cross-project leakage | project-scoped correlation and bounded roots | operation denied |
| Forged “free” or zero cost | provider identity plus actual/estimated/unknown distinction | cost unknown |
| Stale telemetry | source timestamp, observed timestamp, TTL/freshness | stale, never healthy |
| Excessive OS surveillance | optional install, explicit consent, least privilege, bounded retention | unconfigured/unsupported |
| Unsafe cleanup | exact target, two matching snapshots, immediate identity recheck, confirmation, receipt | cleanup refused |
| UI overclaim | canonical projection only; coverage tier and freshness travel with data | release certification fails |

## Data classes

| Class | Examples | Default retention | Content rule |
|---|---|---|---|
| Evidence | approvals, verification receipts, ledger anchors | project policy; never automatic transient purge | hashes/references unless content is expressly authorized |
| Operational | lifecycle events, health, provider usage | bounded and configurable | metadata only by default |
| Transient | render deltas, short-lived sensor samples | shortest practical TTL | no secrets or full payloads |
| Secret | tokens, passwords, `.env` values | never captured by observability | names/schema may be inventoried; values prohibited |

## Consent boundary

Runtime mediation inside an explicitly opened PX project does not require a second
telemetry consent prompt when it records metadata already necessary to execute the
requested operation. Optional operating-system observers, cross-application
capture, content capture, external export, and expanded retention require explicit
purpose-scoped consent. Withheld consent is reported as `unconfigured`, not as a
healthy zero-event state.

