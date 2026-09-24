# Supply Chain

Pacify-X builds software, ships a VS Code extension, and can compile a local model runtime. Each
of those is a supply-chain surface. This document states the controls and the artifacts.

---

## 1. Surfaces

| Surface | Risk | Control |
|---|---|---|
| Python dependencies | malicious or vulnerable package | pinned versions; lockfile; SBOM; vulnerability scan |
| npm dependencies | malicious or vulnerable package | pinned versions; lockfile; SBOM; `npm ci --ignore-scripts` in the documented install |
| Vendored / embedded assets | unnoticed third-party code | declared in [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md); inventory gate |
| llama.cpp source (built locally) | tampered upstream source | pinned commit recorded in the runtime lock; explicit, approval-gated clone |
| CUDA toolkit | operator-installed binary | operator responsibility; recorded in the runtime identity |
| Model weights | poisoned or substituted model | content-hash admission; never auto-downloaded; provenance record |
| Build toolchain | compromised compiler | recorded compiler/toolset identity in provenance |
| Release packaging | tampered artifact | checksum verification; `Install-PacifyX.ps1` refuses on mismatch |
| Update channel | substituted update | Marketplace publisher identity; checksum verification |

## 2. Pinning

- Dependencies are **pinned to exact versions**.
- Lockfiles are part of the release artifact set.
- The local runtime records the **exact resolved commit** and the build flags used.
- A model's identity is its **content hash**, never its filename or URL.

## 3. Build provenance

Every public release records:

- exact source commit and release tag;
- dependency lockfiles;
- compiler / toolchain versions;
- artifact SHA-256 for each shipped artifact;
- VSIX hash;
- native binary hashes where Pacify-X builds them;
- model/runtime hashes where the operator supplies them;
- build flags;
- the SBOM.

Provenance binds the artifact to the build that produced it, so "the code passed the tests" is
replaced by "**these exact bytes** were built from this source by this toolchain."

## 4. Reproducibility and the freeze rule

- Build from the exact tagged source.
- Compare generated artifacts across a second pass.
- Identify and record any intentionally non-reproducible field (for example, a timestamp), so a
  difference is explainable rather than mysterious.
- **Certification binds to the exact artifact bytes.**

The rule that prevents the known failure loop:

> Anything that contributes to release identity — generated state, SBOM, notices, manifests,
> provenance, documentation — is produced **before** the freeze. Certification is then read-only
> with respect to the governed candidate. If the candidate mutates, the certification is invalid.

## 5. Scanning before release

| Scan | What it catches | Status |
|---|---|---|
| Secret scan | credential literals in the tree | **implemented** (release invariant `no-shipped-secrets`) |
| Path/PII scan | developer-specific paths, personal identifiers | **implemented** (invariant `no-machine-specific-paths-or-pii`) |
| Endpoint scan | a new remote destination | **implemented** (invariant `no-px-operated-remote-endpoints`) |
| Telemetry scan | an undeclared emitter | **implemented** (invariant `no-production-remote-telemetry` + extension guard) |
| Dependency/licence inventory | licence obligations | declared in `THIRD_PARTY_NOTICES.md`; automated generation is a **WS-6 repair item** |
| Vulnerability scan | known-vulnerable dependency | **WS-6 repair item** |
| SBOM generation | missing artifact inventory | **WS-6 repair item** (policy: [SBOM_POLICY.md](SBOM_POLICY.md)) |
| Malware scan on artifacts | unwanted code | **WS-6 repair item** |

Reported honestly: the four invariant scans are implemented and enforced today. The remaining
scans are required by the release gate and are recorded as repair items so the gap is visible
rather than assumed closed.

## 6. Git history

- Secret scanning extends to **git history**, not only the working tree.
- If a real secret is ever committed, the response is: rotate the credential first (history
  rewriting does not un-leak a live key), then remediate the history per
  [INCIDENT_RESPONSE.md](INCIDENT_RESPONSE.md).
- History is not rewritten to hide a defect.

## 7. Developer-practice mapping (NIST SSDF SP 800-218)

Pacify-X's existing discipline maps well onto the SSDF's four practice groups. This is a
**mapping**, not a certification:

| SSDF group | Pacify-X practice |
|---|---|
| **Prepare the Organization** (PO) | documented policy set; defined roles; security requirements in `policies/`; this document tree |
| **Protect the Software** (PS) | access control on the repository; pinned dependencies; provenance; SBOM; signed/verified artifacts |
| **Produce Well-Secured Software** (PW) | code review; regression tests; governed gates; fail-closed design; threat model; fixed-point verification |
| **Respond to Vulnerabilities** (RV) | intake channel; triage; severity ladder; regression; advisory; revocation; retained evidence |

**No NIST certification is claimed.** The mapping exists to show where the evidence lives, not to
assert conformance.

## 8. Release gate

A release does not proceed until:

- [ ] every release invariant holds (`scripts/verify_release_invariants.py`);
- [ ] the third-party inventory is present and consistent with the manifests;
- [ ] the model/data licence registry is present;
- [ ] the required policy documents exist;
- [ ] the SBOM and provenance are generated (**before freeze**);
- [ ] secret, path, endpoint, and telemetry scans are clean;
- [ ] artifacts are hashed and the hashes are published;
- [ ] the frozen candidate passes certification unchanged.

See [docs/compliance/RELEASE_COMPLIANCE_CHECKLIST.md](../compliance/RELEASE_COMPLIANCE_CHECKLIST.md).