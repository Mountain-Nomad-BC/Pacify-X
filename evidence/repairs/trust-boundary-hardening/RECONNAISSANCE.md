# Trust-boundary hardening reconnaissance

Recorded: 2026-08-04

- Starting branch: `main`
- Starting commit: `267abe7f501280d5bc6fb0a5f820e92e5014e98c`
- Repair branch: `repair/trust-boundary-hardening`
- Target branch: `main`
- Remote: `git@github.com:Mountain-Nomad-BC/Pacify-X.git`
- Baseline focused suite: 33 passed.

## Existing systems reconciled

| Concern | Existing authority | Decision |
|---|---|---|
| Evidence signing | `runtime/release_signing.py`, `runtime/effect_grants.py`, `policies/effect-grant-trust.json` | Reuse canonical bytes, Ed25519/OpenSSH verification, and the existing signer allowlist through one shared resolver. |
| Outcome claims | `runtime/outcome_verifier.py` | Preserve as an explicitly non-authoritative classifier; add authoritative resolution in the same module. |
| Admission | `runtime/admission_controller.py` | Preserve deterministic classification; require signed receipt resolution before authoritative promotion. |
| Authorization | `runtime/execution_contract.py`, `runtime/effect_grants.py` | Preserve envelope and effect-grant enforcement; split simulation from signed-policy authorization. |
| Exit semantics | Final `valid` projection in `runtime/cli.py` | Replace local ambiguity with the canonical `runtime/exit_codes.py` mapping. |
| Python range | `policies/platform-support.json`, packaging and release validators | Make the existing policy the runtime doctor's source instead of copying a new range. |
| Release install | Existing signed release verifier | Document an exact-tag path and reuse `release verify` for exact-wheel installation; no second verifier. |
| Evidence custody | Release workflow and public evidence receipt | Add signed, content-addressed chunk custody outside the deployable Git tree. |
| CLI loading | Existing single entrypoint | Keep deterministic parser/help compatibility while moving command-family imports to their dispatch branches. |
| CI dependencies | `requirements-release.lock` | Reuse the hash lock in normal and scheduled CI and exact-pin the build backend. |

No `v2`, alternate registry, parallel policy engine, or competing release verifier was introduced.
