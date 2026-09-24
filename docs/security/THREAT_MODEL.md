# Threat Model

This document defines the trust boundaries of Pacify-X, what each boundary protects, what
crosses it, and what the system does when a boundary is stressed.

It is the reference for *where* a security claim applies. A control that protects one boundary
does not automatically protect another.

---

## 1. Trust boundaries

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ HOST                                                                         │
│                                                                              │
│  B1 ── VS Code client boundary ──────────────────────────────────────────    │
│  │   The extension webview + extension host process.                        │
│  │   Untrusted relative to the Python runtime: the webview is a projection,  │
│  │   never the authority. It can request; it cannot execute.                 │
│  │                                                                          │
│  B2 ── Python runtime boundary ──────────────────────────────────────────    │
│  │   The authority. Owns task state, routing, memory, knowledge, evidence,  │
│  │   and every governed mutation.                                           │
│  │                                                                          │
│  B3 ── Workspace / repository boundary ──────────────────────────────────    │
│  │   Project isolation. One active project per session. No cross-project    │
│  │   memory or knowledge leakage.                                           │
│  │                                                                          │
│  B4 ── Memory / knowledge boundary ──────────────────────────────────────    │
│  │   Local custody store. Private by default. Promotion is gated.           │
│  │                                                                          │
│  B5 ── Local model runtime boundary ─────────────────────────────────────    │
│  │   llama.cpp on loopback. Process is owned, bounded, and receipted.       │
│  │                                                                          │
│  B6 ── Plugin / tool / MCP boundary ─────────────────────────────────────    │
│  │   Anything that executes with a capability. Deny-by-default; explicit    │
│  │   grants; no inherited authority.                                        │
│  │                                                                          │
│  B7 ── Credential store boundary ────────────────────────────────────────    │
│  │   OS credential storage. Never the repository, config, events, webview.  │
│  │                                                                          │
│  B8 ── Update / package boundary ────────────────────────────────────────    │
│  │   VSIX and source distribution. Signature/checksum verification,         │
│  │   artifact identity, revocation.                                         │
│  │                                                                          │
│  B9 ── Build system boundary ────────────────────────────────────────────    │
│  │   Local runtime build, dependency resolution, provenance.                │
│  │                                                                          │
│  B10 ── Generated artifact boundary ─────────────────────────────────────    │
│  │   Derived registries, graphs, projections. Must converge deterministically│
│  │   and must not be hand-edited to satisfy a check.                        │
│  └──────────────────────────────────────────────────────────────────────────┘
└──────────────────────────────────────────────────────────────────────────────┘
                        │
                        │ B11 ── External provider boundary ── (only if you configure it)
                        ▼
        Provider you explicitly authorised. Its terms govern. Denied by default.
        PX never silently falls back here.
```

## 2. Boundary table

| # | Boundary | Protects | What crosses | Primary control |
|---|---|---|---|---|
| B1 | VS Code client | UI integrity, secret exposure | user input, rendered output | versioned message protocol; webview cannot execute; no secrets to webview |
| B2 | Python runtime | authority, state | all governed requests | capability/action registry; authority gates; approvals; receipts |
| B3 | Workspace | project isolation | file/effect scope | one active project; write boundary; explicit context reset |
| B4 | Memory/knowledge | privacy, provenance | stored facts | scopes never merged; provenance; deletion removes all projections |
| B5 | Local runtime | process integrity | model requests | loopback only; owned process tree; bounded; fingerprint-bound |
| B6 | Plugin/tool/MCP | effect scope | tool invocations | deny-by-default; capability grants; revocation; no inherited authority |
| B7 | Credentials | secret confidentiality | credential use | OS credential storage; never logged, never in repo, never in webview |
| B8 | Update/package | supply chain | released artifacts | hashes; identity check; revocation records |
| B9 | Build system | build integrity | compiled runtime | pinned revision; recorded flags; capability fingerprint |
| B10 | Generated artifacts | state correctness | derived state | deterministic builders; dependency order; fixed-point verification |
| B11 | External provider | data destination | prompts/outputs | denied by default; explicit authorisation; no hidden fallback |

## 3. Threat classes and posture

| Threat | Boundary | Posture |
|---|---|---|
| Malicious webview content trying to execute | B1 | webview has no execution authority; messages validated and unknown commands rejected |
| Prompt injection from retrieved content | B4, B2 | retrieved text is separated from system authority; a model cannot grant itself authority |
| Cross-project data leakage | B3, B4 | per-project custody; explicit context reset; no cross-project memory |
| Credential exfiltration via logs/prompts | B7 | credentials never rendered to logs, prompts, events, or webview |
| Plugin privilege escalation | B6 | deny-by-default; explicit grants; no authority inheritance from installation |
| Poisoned or malformed model file | B5, B9 | hash-bound admission; GGUF header/architecture checks; fail closed |
| Compromised update | B8 | checksum/hash verification; revoke-by-addition; never silently rewrite history |
| Supply-chain compromise | B9 | pinned dependencies; lockfiles; SBOM; provenance |
| Stale generated state masquerading as truth | B10 | builders in dependency order; fixed-point check; stale state is reported not hidden |
| Silent remote fallback leaking data | B11 | prohibited by release invariant `no-hidden-cloud-fallback` |
| Resource exhaustion / orphan process | B5 | owned process trees; bounded budgets; reconciliation on exit |

## 4. Explicit non-goals

- Pacify-X does **not** protect a machine from a user who is already an administrator on it.
- It does **not** claim to defeat a compromised operating system or a compromised VS Code host.
- It does **not** provide multi-tenant isolation; hosted multi-tenancy does not exist in 0.9.x.
- It does **not** claim application-level encryption of local stores.
- It does **not** defend against a malicious *dependency* being introduced by the maintainer
  without review; it provides the provenance and SBOM to make that review possible.

## 5. Assumptions

1. The host OS enforces user separation and disk protection and is not compromised.
2. VS Code is genuine and unmodified.
3. The operator reviews approvals before granting them.
4. Loopback is not intercepted by a hostile local process.
5. The operator's machine is not shared with an adversary holding their OS credentials.

If an assumption is false, the boundary's guarantee is void — and that should be stated, not
papered over.

## 6. References

- [SECURITY_ARCHITECTURE.md](SECURITY_ARCHITECTURE.md) — how each control is implemented.
- [VULNERABILITY_RESPONSE.md](VULNERABILITY_RESPONSE.md) — what happens when a boundary fails.
- [INCIDENT_RESPONSE.md](INCIDENT_RESPONSE.md) — incident classes and handling.
- [SUPPLY_CHAIN.md](SUPPLY_CHAIN.md) — B8/B9 in detail.
- [SBOM_POLICY.md](SBOM_POLICY.md) — artifact inventory policy.