# Security policy

PACIFY-X 0.6.2 is revoked. Version 0.6.3 remains a release candidate until its exact signed assets are published and independently verified. Do not deploy a revoked release or treat an unpublished candidate as security-authoritative.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability, exposed credential, unsafe path/effect boundary, signature problem, or cross-project data leak. Email `bjc274@gmail.com` with:

- the affected commit, tag, package version, and platform;
- the smallest reproducible input and observed result;
- whether confidentiality or destructive effects are involved;
- any relevant artifact, certificate, or evidence hashes;
- a safe contact method for coordinated follow-up.

Do not include real secrets, private source, personal data, or live exploitation instructions. Use inert fixtures and redact tokens while preserving their shape.

## Response and disclosure

Reports are triaged against the permission, path, project-isolation, effect-grant, evidence, and release-signing boundaries. Confirmed findings receive a tracked repair card, regression test, and—when release authority is affected—an additive revocation record. Historical evidence is preserved; it is not silently rewritten or deleted. Public disclosure follows remediation and a reasonable upgrade window unless active exploitation requires faster notice.

## Verification boundary

A PACIFY-X release is self-certified only against its included validation profile. A passing certificate is not a warranty, penetration test, or independent security certification. Verify the signature, exact artifacts, evidence manifest, Git identity, revocation index, and supported platform before relying on a release.
