# Telemetry

**Current state: PACIFY-X emits no production telemetry.**

This is not a promise in a document. It is a verified property of the code, enforced by a
machine-verifiable release invariant and by a guard that runs on every extension check.

---

## 1. What is collected

**Nothing is transmitted.**

| Category | Collected? | Transmitted? |
|---|---|---|
| Prompts, outputs, model responses | no | no |
| Source code, filenames, paths, repository names | no | no |
| Persistent memory or knowledge content | no | no |
| Credentials or tokens | no | no |
| Crash reports | no | no |
| Usage or feature statistics | no | no |
| Performance metrics | no | no |
| Anonymous identifiers or a persistent install ID | no | no |
| Machine or hardware identifiers | no | no |

There is no telemetry endpoint, no analytics vendor, no crash reporter, and no update-check
call in production PACIFY-X code.

---

## 2. How this is verified (not merely stated)

| Control | Location |
|---|---|
| Release invariant `no-production-remote-telemetry` | `policies/release-invariants.json` |
| Runtime/extension emitter scan | `scripts/verify_release_invariants.py` |
| Extension-side guard, run on every `npm run check` | `extension/scripts/check-telemetry-guard.js` |
| Regression coverage, both directions | `tests/test_release_invariants.py` |

The guard passes in one of two ways:

- **no emitter exists** → PASS (the current state); or
- an emitter exists **and** is gated by VS Code's `isTelemetryEnabled` /
  `onDidChangeTelemetryEnabled` **and** a `telemetry.json` manifest exists → PASS
  (a deliberate, reviewed future change).

It **fails** if an emitter is introduced without that gating. That is the point: a future
telemetry addition cannot land silently.

---

## 3. Local operational data is NOT telemetry

This distinction matters and is deliberate.

PACIFY-X produces **local** operational records:

- logs;
- execution traces;
- certification and audit evidence;
- diagnostics;
- benchmark results.

These stay on your machine. They are files you own, in directories you control. They are
**not** telemetry, because nothing transmits them anywhere. Removing them is a local file
operation.

The invariant's own wording records this:

> Local operational logs, traces, certification evidence, and diagnostics that remain on the
> user's machine are NOT remote telemetry.

---

## 4. If telemetry were ever added

The policy that would govern a future implementation, so the decision is not improvised later:

1. **It must be disclosed here before release** — not after. This document must state exactly
   what is collected, why, where it goes, and how long it is kept.
2. **It must honour VS Code's global telemetry setting.** An extension-specific setting must
   never override a user's global opt-out. `isTelemetryEnabled` and
   `onDidChangeTelemetryEnabled` must both be respected.
3. **It must ship a `telemetry.json` manifest** documenting every event and field.
4. **It must never include** source code, prompts, outputs, filenames, paths, repository names,
   memory content, knowledge content, credentials, or secrets.
5. **It must never include PII** in the VS Code sense.
6. **It must be disclosed in the Marketplace listing** and in the first-run walkthrough.
7. **It must pass an updated privacy/telemetry reclassification** recorded in
   `docs/compliance/REGULATORY_APPLICABILITY_MATRIX.md`.
8. **A test must prove** that with telemetry disabled, **no** remote telemetry traffic is
   emitted.

Telemetry will not be added merely to satisfy a compliance checklist. Its absence is the
current, correct state.

---

## 5. Opt-out and inspection

There is nothing to opt out of today, and nothing to inspect.

If you want to verify the claim yourself:

```powershell
python scripts/verify_release_invariants.py --root .      # scans for emitters and endpoints
cd extension; node scripts/check-telemetry-guard.js        # extension-side guard
```

Both are read-only and report the evidence they used.

---

## 6. Reporting a discrepancy

If you can show that a PACIFY-X build transmits data it should not, that is a **security
issue**, not a documentation issue. Report it privately per [SECURITY.md](SECURITY.md) rather
than opening a public issue.