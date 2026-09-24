# Credential Handling

How Pacify-X handles provider credentials, including the migration of a workspace value into
VS Code SecretStorage.

**Owner decision 2026-09-23** (recorded in `policies/release-invariants.json` under
`owner_decisions`).

---

## 1. The rule

> **SecretStorage is the only operational credential source. A workspace value is a migration
> source, never a fallback.**

A credential that lives in `.vscode/` or another workspace config file is typically committed. It
is not a safe place for a live key, and Pacify-X will not read it as if it were.

## 2. Required behaviour

| # | Behaviour |
|---|---|
| 1 | **Detect** that a key-like value exists in `.vscode` or workspace config |
| 2 | **Do not silently consume** it during normal runtime |
| 3 | **Offer** a one-time migration into VS Code SecretStorage |
| 4 | **Verify** retrieval from SecretStorage after storing |
| 5 | **Advise** the user to remove the plaintext value; offer to scrub it only if Pacify-X has authority over that exact config |
| 6 | **Never** write the secret into logs, evidence, diagnostics, telemetry, exception text, state snapshots, or generated artifacts |
| 7 | **Store only non-secret status**: `configured=true`, provider name, last validation timestamp |
| 8 | If **both** exist, SecretStorage wins and the plaintext copy raises a **warning**, not a fallback |

## 3. Why explicit, not automatic

Automatic migration with no interaction would mean Pacify-X **reads and persists a credential
based merely on discovery**. That inverts the authority model: discovery is not authorisation.

A bounded `credential detected → import?` action preserves the authority semantics the rest of
Pacify-X is built on. The rejected alternative is recorded alongside the decision.

## 4. What is never stored

| Never stored | Where it would leak |
|---|---|
| the key itself | logs, evidence, diagnostics, telemetry |
| the key in exception text | an error path is still an output |
| the key in a state snapshot | snapshots are read by other components |
| the key in a generated artifact | generated state is often shared |

Only presence and metadata are recorded:

```json
{
  "provider": "openai",
  "configured": true,
  "source": "secret_storage",
  "last_validated_at": "2026-09-23T00:00:00Z"
}
```

Note there is no `value` field — not even a redacted one. A redacted secret still leaks length and
shape, and still trains people to read that field.

## 5. Conflict behaviour

| Situation | Behaviour |
|---|---|
| SecretStorage only | normal operation |
| Workspace only | **not** used operationally; the user is offered migration |
| Both present | **SecretStorage wins**; the workspace copy produces a warning |
| SecretStorage retrieval fails | the provider is unavailable; **no** fallback to the workspace copy |

The last row is the one that matters most. A missing credential must surface as *missing*, not as
*quietly taken from a file that was committed*.

## 6. Where this is enforced

| Control | Location |
|---|---|
| Decision record | `policies/release-invariants.json` → `owner_decisions[Q8-workspace-credential-migration]` |
| Credential-shape scan | `scripts/verify_release_invariants.py` → invariant `no-shipped-secrets` |
| Workspace-credential guard | `extension/scripts/check-credential-handling.js` |
| Regression evidence | `tests/test_credential_handling.py` |

## 7. Related

- [PRIVACY.md](PRIVACY.md) §5 — credentials stay in host storage.
- [SECURITY_ARCHITECTURE.md](docs/security/SECURITY_ARCHITECTURE.md) §6 — secret handling rules.
- [PROVIDER_DATA_HANDLING.md](PROVIDER_DATA_HANDLING.md) — what leaves the machine once a provider
  is configured.