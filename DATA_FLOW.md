# Data Flow

A factual inventory of where data goes in PACIFY-X 0.9.x. This describes the **released
build's actual behaviour**, verified by evidence; where a behaviour is not yet proven it is
marked as such.

Controller/processor roles in the GDPR sense are left to your own determination — this document
records facts, not legal characterisation.

---

## 1. Summary diagram

```text
                       ┌──────────────────────────────┐
                       │        YOUR MACHINE          │
                       │                              │
  ┌─────────┐          │  ┌────────────────────────┐  │
  │  You    │  input   │  │  VS Code extension     │  │
  └────┬────┘ ────────►│  │  (PX Agent Console)    │  │
       │               │  └───────────┬────────────┘  │
       │               │              │ loopback only │
       │               │              ▼               │
       │               │  ┌────────────────────────┐  │
       │               │  │  PX Python runtime     │  │
       │               │  │  gateway • memory •    │  │
       │               │  │  knowledge • evidence  │  │
       │               │  └───────┬────────┬───────┘  │
       │               │          │        │          │
       │               │   ┌──────▼──┐  ┌──▼───────┐  │
       │               │   │ local    │  │ custody  │  │
       │               │   │ model    │  │ store    │  │
       │               │   │ runtime  │  │ (disk)   │  │
       │               │   └──────────┘  └──────────┘  │
       └───────────────┴──────────────────────────────┘
                                    │
                     ONLY IF YOU EXPLICITLY CONFIGURE IT
                                    ▼
                       ┌──────────────────────────────┐
                       │  External provider you chose │
                       │  (its terms govern that data)│
                       └──────────────────────────────┘
```

---

## 2. Data inventory

| # | Data category | Source | Destination | Processor | Retention | Encryption | User control |
|---|---|---|---|---|---|---|---|
| D1 | Source code / workspace | your repository | stays local; sent to a provider only if you configure one and a task requires it | you | your VCS | your disk | full |
| D2 | Chat prompts & outputs | you / the agent | local runtime; provider only if configured | you | session + local logs | your disk | full |
| D3 | Persistent memory | PACIFY-X (when enabled) | local custody store | you | your policy (`DATA_RETENTION_AND_DELETION.md`) | your disk | full |
| D4 | Knowledge / indexes | PACIFY-X generators | local custody store | you | derived; rebuildable | your disk | full |
| D5 | Operational logs / traces | PACIFY-X | local | you | local rotation | your disk | full |
| D6 | Certification / audit evidence | PACIFY-X certification | local evidence tree | you | append-only by policy | your disk | full |
| D7 | Credentials | you | OS credential storage | your OS | your OS | OS-managed | full |
| D8 | Model files (GGUF) | you (never auto-downloaded) | local custody store | you | your policy | your disk | full |
| D9 | Telemetry | — | **none** | — | — | — | n/a (§4) |
| D10 | Account / billing data | — | **does not exist** | — | — | — | n/a |

No row has a PACIFY-X-operated destination. There is no PACIFY-X-operated infrastructure in the
data path.

---

## 3. The three boundaries

### B1 — Local boundary (everything by default)

The extension talks to the Python runtime over a **loopback** connection. No local data leaves
the machine. This covers D1–D8 and D10.

### B2 — Provider boundary (only when you configure it)

If you configure an external provider, the content of the request you send crosses this
boundary. From that point, the provider's terms govern:

- whether prompts are retained;
- whether content may be used for training;
- available zero-data-retention options;
- region handling.

PACIFY-X does not assert provider behaviour on the provider's behalf. Confirm it with the
provider. See [PROVIDER_DATA_HANDLING.md](PROVIDER_DATA_HANDLING.md).

Providers are **denied by default** and require explicit configuration and authorisation.
PACIFY-X never silently falls back to a provider (invariant `no-hidden-cloud-fallback`).

### B3 — PACIFY-X-operated boundary (does not exist)

There is no boundary B3 in the 0.9.x core.

Introducing one — hosted memory, accounts, cloud sync, managed routing, teams, remote telemetry
— is a **formal reclassification trigger** requiring a privacy/data-flow/compliance review
**before** it can be part of a release. See
`docs/compliance/REGULATORY_APPLICABILITY_MATRIX.md`.

---

## 4. Telemetry flow

None. See [TELEMETRY.md](TELEMETRY.md).

Local logs, traces, and diagnostics are **not** telemetry: they are not transmitted.

---

## 5. Network endpoints

**Declared:** none operated by PACIFY-X.

The only network hosts referenced in authored source are:

| Host | Role |
|---|---|
| `127.0.0.1` / `localhost` | loopback to the local runtime |
| `json-schema.org`, `www.w3.org`, `slsa.dev`, `in-toto.io`, `schemas.microsoft.com` | identifiers in schema/provenance documents, not destinations |
| `github.com` | the project repository URL and the explicit, approval-gated llama.cpp build clone |
| `marketplace.visualstudio.com` | extension Marketplace metadata |

This list is machine-checked by invariant `no-px-operated-remote-endpoints` in
`policies/release-invariants.json`; adding a new remote destination fails the check unless the
policy is deliberately updated.

**Not yet proven:** live-session socket behaviour at runtime. Recorded as an adversarial-audit
item.

---

## 6. Keeping this honest

This document is only useful if it stays true. The controls that keep it true:

- `policies/release-invariants.json` — the assertions, each with a reclassification trigger;
- `scripts/verify_release_invariants.py` — proves the tree satisfies them;
- `tests/test_release_invariants.py` — regression, in both directions;
- the compliance gate in the certification order — a release cannot be certified while an
  invariant fails.

If the software's behaviour changes, this document must change **before** the release, not after.