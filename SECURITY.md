# Security policy

PACIFY-X is a local-first engineering and agent control plane. This document states the
supported release lines, how to report a vulnerability, what we commit to, and the exact
boundary of a PACIFY-X security claim.

## Supported release lines

| Line | Status | Security updates |
|---|---|---|
| 0.9.x | **current development line** | yes, once certified |
| 0.7.x | superseded release candidate | no |
| 0.6.3 | previous certified release | critical fixes only |

A line is *supported* only after its frozen candidate passes governed certification. Until
then, no tag or artifact may be described as a supported release.

## Security model in one paragraph

PACIFY-X is distributed as source and as a VS Code extension (VSIX). The core runs on your
machine, contacts no PACIFY-X-operated endpoint, and emits no production telemetry. It does not
ship or automatically download model weights. It can execute tools and make governed
mutations only through its own authority, permission, and approval gates. Its security claim is
limited to what its certification evidence proves against an exact artifact — it is not a
warranty, a penetration test, or an independent security certification.

## Reporting a vulnerability

**Do not open a public issue** for a suspected vulnerability, exposed credential, unsafe
path/effect boundary, signature problem, or cross-project data leak.

Email **`bjc274@gmail.com`** with:

- the affected commit, tag, package/extension version, and platform;
- the smallest reproducible input and the observed result;
- whether confidentiality or destructive effects are involved;
- any relevant artifact, certificate, or evidence hashes;
- a safe contact method for coordinated follow-up.

Do **not** include real secrets, private source, personal data, or live exploitation
instructions. Use inert fixtures and redact tokens while preserving their shape.

### What to expect

| Stage | Target |
|---|---|
| Acknowledgement of your report | within 5 business days |
| Initial triage and severity assessment | within 10 business days |
| Fix or documented mitigation plan for confirmed issues | best effort, prioritised by severity |
| Public disclosure | after remediation and a reasonable upgrade window |

This is a single-maintainer open-source project. These are good-faith targets, not a
contractual SLA.

## Severity handling

Reports are triaged against the permission, path, project-isolation, effect-grant, evidence,
and release-signing boundaries.

| Severity | Examples | Handling |
|---|---|---|
| Critical | release-signing compromise, cross-project data exposure, unapproved remote egress | fixed before any further release; revocation record if release authority is affected |
| High | authority/permission bypass, unapproved destructive effect, credential exposure | fixed in the next release; advisory published |
| Medium | degraded isolation, fail-open behaviour where fail-closed is required | scheduled fix with regression test |
| Low | hardening, defence in depth, documentation gaps | batched into normal maintenance |

## Coordinated disclosure

We follow coordinated disclosure. Confirmed findings receive a tracked repair card, a
regression test, and — when release authority is affected — an additive revocation record.
Historical evidence is preserved; it is never silently rewritten or deleted. Public disclosure
follows remediation and a reasonable upgrade window, unless active exploitation requires
faster notice.

## Dependency, supply-chain, and vulnerability process

- Release candidates carry an SBOM, artifact hashes, and build provenance.
- The repository is scanned for shipped secrets and for machine-specific paths or personal
  identifiers before release; both are enforced release invariants
  (`policies/release-invariants.json`).
- Dependencies are pinned; lockfiles are part of the release artifact set.
- Vulnerability reports against dependencies are triaged with the same severity ladder above.
- A security advisory is published when a confirmed issue affects a supported line.

## Secure update and revocation

- Released assets are published with checksums; verify them before use.
- The extension is updated through the VS Code Marketplace under its published identity.
- If a release is found to be compromised or unsafe, a revocation record is added and the
  affected version is withdrawn from recommendation. Revocation is additive: existing evidence
  is preserved so the history remains auditable.

## Verification boundary

A PACIFY-X release is self-certified only against its included validation profile. A passing
certificate is **not** a warranty, penetration test, or independent security certification.
Verify the signature, exact artifacts, evidence manifest, Git identity, revocation index, and
supported platform before relying on a release.

See [`docs/security/THREAT_MODEL.md`](docs/security/THREAT_MODEL.md),
[`docs/security/SECURITY_ARCHITECTURE.md`](docs/security/SECURITY_ARCHITECTURE.md), and
[`docs/security/VULNERABILITY_RESPONSE.md`](docs/security/VULNERABILITY_RESPONSE.md).
