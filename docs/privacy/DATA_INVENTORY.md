# Data Inventory

Machine-oriented companion to [DATA_FLOW.md](../../DATA_FLOW.md). Same facts, table form.

**Current position: every data category below is local. No category has a Pacify-X-operated
destination.**

| ID | Category | Source | Destination(s) | Processor | Retention | Encryption | User control |
|---|---|---|---|---|---|---|---|
| D1 | Source code / workspace | user repo | local; provider **only if configured** | user | VCS policy | user disk | full |
| D2 | Prompts and outputs | user / agent | local; provider **only if configured** | user | session + local logs | user disk | full |
| D3 | Persistent memory | PX (if enabled) | local custody | user | user policy | user disk | full |
| D4 | Knowledge and indexes | PX generators | local custody | user | derived, rebuildable | user disk | full |
| D5 | Operational logs / traces | PX | local | user | local rotation | user disk | full |
| D6 | Certification / audit evidence | PX certification | local evidence tree | user | append-only by policy | user disk | full |
| D7 | Credentials | user | OS credential storage | user OS | user OS | OS-managed | full |
| D8 | Model files (GGUF) | user | local custody | user | user policy | user disk | full |
| D9 | Telemetry | — | **none** | — | — | — | n/a |
| D10 | Account / billing | — | **does not exist** | — | — | — | n/a |

## Categories deliberately absent

| Category | Why absent |
|---|---|
| User accounts / profile | no hosted service |
| Billing / payment records | no paid service |
| Crash reports | no crash-reporting endpoint |
| Device / install identifiers | nothing is collected |
| Support uploads | no support intake service |
| Team workspace data | no team features |
| Cloud sync data | no cloud service |
| Provider-side prompt storage | provider behaviour, not PX behaviour — see `PROVIDER_DATA_HANDLING.md` |

## Verification

The inventory is checked against code by static evidence (`.tmp/stage1/COMPLIANCE_WS1_RUNTIME_TRUTH.md`)
and by machine-checked release invariants:

```powershell
python scripts/verify_release_invariants.py --root . --json
```

A future data category cannot be added silently: introducing a PX-operated destination fails the
`no-px-operated-remote-endpoints` invariant, and introducing telemetry fails the
`no-production-remote-telemetry` invariant, until the policy is deliberately updated **and** this
inventory is revised.