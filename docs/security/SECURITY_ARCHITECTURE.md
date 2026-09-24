# Security Architecture

How the controls in the [threat model](THREAT_MODEL.md) are actually implemented in Pacify-X.

Where a control is implemented, this document names the owner. Where a control is declared but
not yet enforced, it says so — an architecture document that overstates is worse than none.

---

## 1. Authority model

Pacify-X uses **capability and authority gates**, not role trust.

The invariant:

> **same effect → same gate.** Whether a request arrives from the CLI, chat, an agent, a VS Code
> command, a workflow, or a model, the *effect* determines the gate. The caller does not.

| Layer | Responsibility | Does it grant authority? |
|---|---|---|
| Model | proposes, classifies, summarises | **no** |
| System-1 decision layer | recommends, scores | **no** (advisory by contract) |
| Capability routing | selects a governed capability | **no** |
| Authority gate | decides whether an effect is permitted | yes |
| Permission/policy | decides who may cause it | yes |
| Approval gate | requires explicit human confirmation where the contract demands | yes |
| Execution owner | performs the effect and receipts it | yes |

**Consequence:** a model with 0.99 confidence still passes every gate. Confidence is not
authority.

## 2. Least privilege

- **Deny by default.** An adapter, tool, or capability is unavailable until admitted.
- **Explicit grants.** A plugin or tool receives a named capability grant, not the ambient
  authority of the process.
- **No inheritance.** Installing a plugin does not confer Pacify-X's authority on it.
- **Revocation.** A grant can be withdrawn; withdrawal is recorded.

## 3. Sandboxing and contained execution

- Local model runtimes run as **owned child processes** with a bounded budget: startup, idle,
  and total timeouts; stdout/stderr limits; graceful and forced shutdown bounds.
- Process trees are closed on success, failure, timeout, cancellation, and restart — not just on
  the happy path.
- Loopback-only binding for local services; a literal loopback origin is required, so an ambient
  proxy cannot redirect a local model request.
- Compiled literal and ancestor indexes bound artifact projection traversal.

**Declared but not fully enforced:** per-plugin OS-level sandboxing. Plugin containment today is
capability grants plus process boundaries, not a separate sandbox. Recorded as a known gap.

## 4. Mutation admission

A material write follows:

```text
intent
  → resolve typed action
  → validate parameters against schema
  → preview/diff when meaningful
  → authority + policy gate
  → explicit confirmation when the contract requires it
  → canonical owner executes
  → previous/new value recorded in a receipt
  → outcome verification
  → evidence retained
```

A model cannot narrate its way past this. Completion authority stays outside the model.

## 5. Path handling

- Declared paths are validated against admitted roots; a path outside its root is rejected.
- Symlink and reparse points are detected and refused where they would escape a boundary.
- Repo-relative paths are required for declared artifacts; `..` traversal is rejected.
- Loops and oversized traversals are bounded.

The portability invariant (`no-machine-specific-paths-or-pii`) additionally prevents a
developer-specific path from shipping at all.

## 6. Secret handling

| Rule | Implementation |
|---|---|
| Credentials live in OS credential storage | extension credential provider |
| Never in the repository | release invariant `no-shipped-secrets` |
| Never in config files or examples | scanner allowlist patterns that cannot be mistaken for usable secrets |
| Never in events, logs, or the webview | provider responses are normalised; secrets are not included in receipts |
| Redacted from evidence | evidence records carries metadata, not credential material |
| A model cannot enumerate unrelated credentials | credential access is capability-bound |

## 7. Network egress

- There is **no Pacify-X-operated endpoint** (invariant `no-px-operated-remote-endpoints`).
- Loopback is the only implicit destination.
- External providers are **denied by default** and require explicit configuration and
  authorisation (invariant `explicit-provider-use-only`).
- **Hidden fallback to a remote provider is prohibited** (invariant `no-hidden-cloud-fallback`).
  A local failure is reported, not silently escalated.

The declared endpoint list is machine-checked; adding a new remote destination fails the check
until the policy is deliberately updated.

## 8. Plugin and tool permissions

A plugin/integration manifest is expected to declare: publisher, version, hash/signature,
licence, permissions, filesystem scope, network scope, credential access, memory access,
knowledge access, tool-execution rights, subprocess capability, environment-variable access,
data destinations, retention, telemetry, and update channel.

The enforcement posture is deny-by-default with explicit grants, version pinning, compatibility
checks, revocation, quarantine, and an audit trail.

**Known gap:** the manifest *schema and enforcement* for third-party plugins is not yet
implemented to that full list. Until it is, the correct control is that Pacify-X ships no
third-party plugin that requires it. Recorded as a repair item.

## 9. Audit integrity

- Material mutations produce a receipt: trigger, previous state, new state, policy decision,
  resource snapshot, reason, result, timestamp, and correlation id.
- Evidence is **append-only** where auditability requires it; a superseded record is marked, not
  rewritten.
- **Tamper detection:** evidence is bound to artifact hashes; generated state is verified against
  its producer inputs, so a hand-edited projection is detectable as stale rather than trusted.

## 10. Rollback and recovery

- Unknown, failed, or superseded material is **quarantined**, not hard-deleted.
- A reclaim must pass a safe-reclamation gate and leave a cleanup receipt.
- A release is never silently rewritten; a superseded release is marked and its record preserved.
- A failed run reconciles its resources rather than leaking them.

## 11. Model and runtime identity

- A model's identity is its **content hash**, never its filename.
- The runtime binary is fingerprinted; its capability set is probed from the actual executable
  rather than assumed from a version string.
- A launch is checked against the exact fingerprint; a control the binary does not advertise
  fails closed instead of being silently ignored.
- Admission binds the model hash, the runtime fingerprint, and the executing hardware.

## 12. Generated-state integrity

Derived registries, graphs, and projections are produced by canonical builders in dependency
order, then verified for **fixed point**: a second deterministic pass must produce no unexpected
change. A stale projection is an error to be fixed at its input, never by editing its output.

## 13. What this architecture does not yet have

Stated plainly so the document is trustworthy:

| Gap | Status |
|---|---|
| Per-plugin OS sandbox | not implemented (capability grants + process boundary only) |
| Full plugin manifest enforcement | schema and enforcement incomplete |
| Application-level encryption of local stores | not implemented (OS disk protection only) |
| Multi-tenant isolation | not applicable (no hosted service) |
| Independence of certification | self-certified, not third-party assessed |

Each gap is either not-yet-applicable to the current release or recorded as a repair item.