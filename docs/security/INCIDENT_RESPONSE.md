# Incident Response

What happens when something has **already gone wrong**. [VULNERABILITY_RESPONSE.md](VULNERABILITY_RESPONSE.md)
covers a reported weakness; this document covers an active incident.

---

## 1. Incident classes

| Class | Examples | First move |
|---|---|---|
| **Credential compromise** | a provider key or signing key exposed | revoke the credential, then investigate |
| **Poisoned model or plugin** | a model/plugin behaves maliciously or is replaced | disable it, quarantine it, verify its hash |
| **Supply-chain compromise** | a dependency or the build toolchain is compromised | stop releases, identify the injected change, rebuild from known-good |
| **Malicious package** | a published artifact contains unwanted code | withdraw it, publish an advisory, fix and re-release |
| **Data exposure** | cross-project leakage, unintended remote egress | contain the path, assess what was exposed, notify |
| **Telemetry / egress leak** | data leaving when it should not | block the path, verify with a trace, fix the invariant violation |
| **Memory exposure** | private memory readable outside its scope | contain, assess, verify deletion removes all projections |
| **Signing key compromise** | release identity no longer trustworthy | rotate the key, revoke affected releases, re-sign going forward |
| **Active exploitation** | a known issue is being exploited | fastest available mitigation, then the normal process |
| **Generated-state corruption** | derived state diverges from its inputs and is trusted anyway | rebuild from canonical inputs in dependency order; verify fixed point |

## 2. Sequence

```text
1. DETECT      — how did we learn? (report, trace, invariant failure, monitoring)
2. CONTAIN     — stop the harm. Withdraw, disable, revoke, or block.
3. PRESERVE    — capture evidence BEFORE cleaning up. Logs, traces, hashes, artifacts.
4. ASSESS      — affected versions, boundaries, data, and users.
5. RECORD      — incident record with timeline and evidence references (append-only).
6. REMEDIATE   — the real fix, with a regression test.
7. VERIFY      — prove the fix against the same class of trigger.
8. NOTIFY      — advisory / user notification, per severity.
9. REVIEW      — why did this happen; what control would have caught it earlier.
```

**Preserve before cleaning.** The step that is most often skipped is the one that makes the
incident unlearnable afterwards.

## 3. Containment options

| Option | Applies to |
|---|---|
| Withdraw the version | compromised or malicious release |
| Add a revocation record | any released artifact that must not be used |
| Disable a capability | poisoned plugin/model, unsafe feature |
| Quarantine an artifact | suspect file, model, or package (never hard-delete) |
| Block an endpoint | unintended egress |
| Rotate a credential or key | compromise |
| Roll back to a verified release | a regression introduced by an update |

Containment must not destroy evidence. Quarantine rather than delete.

## 4. Regulatory reporting — decision point

If Pacify-X is determined to be a CRA manufacturer in scope, severe-incident reporting timelines
apply (24 hours early warning, 72 hours notification, 14 days final report). That determination
is recorded in [`docs/compliance/EU_CRA.md`](../compliance/EU_CRA.md) and is currently
**legal classification required**.

Regardless of classification, this document's sequence — contain, preserve, assess, record,
remediate, verify, notify — produces the evidence such a report requires. Building the process
now is not the same as claiming the obligation applies.

## 5. User notification

| Severity | Notification |
|---|---|
| Critical | publish an advisory immediately after containment; state the safe version |
| High | publish an advisory with the fix release |
| Medium / Low | batched into release notes |

Notification states facts: what is affected, what to do, what is fixed. It does not speculate.

## 6. Evidence preservation

All incident evidence is **append-only**. The repository never silently rewrites a release,
never hard-deletes evidence to make an inconsistency disappear, and never edits historical
records. If an incident reveals that a past record is wrong, a **new** record corrects it and the
old one is preserved and marked.

## 7. Post-incident review

Every incident produces, at minimum:

- a timeline;
- the affected boundary (from [THREAT_MODEL.md](THREAT_MODEL.md));
- the root cause;
- the control that would have caught it earlier;
- a repair or a documented acceptance of the risk;
- a regression test where a test can express it.

## 8. Contact

Report an active security incident privately to `bjc274@gmail.com`. Do **not** open a public
issue. See [SECURITY.md](../../SECURITY.md).