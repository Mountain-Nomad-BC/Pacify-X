# PACIFY-X release process

PACIFY-X is the project and framework. `engineering-bootstrap` is its Python package and command-line control plane.

Release authority is created only from a clean tagged commit. The authoritative version is `project.version` in `pyproject.toml`; the runtime version, README projection, annotated Git tag, package metadata, artifacts, certificate, and publication receipt must match it exactly.

## Install the certified release

The simplest certified path is the immutable source tag shown in the README. To install the exact wheel that passed release certification instead:

```powershell
git clone --branch v0.6.3 --single-branch https://github.com/Mountain-Nomad-BC/Pacify-X.git
cd Pacify-X
New-Item -ItemType Directory release-assets | Out-Null
gh release download v0.6.3 --repo Mountain-Nomad-BC/Pacify-X --dir release-assets
python -m runtime.cli --root . release verify --release 0.6.3 --artifact-dir release-assets
python -m pip install .\release-assets\engineering_loop_bootstrap-0.6.3-py3-none-any.whl
engineering-bootstrap --version
engineering-bootstrap doctor
```

The verification command fails before installation if the certificate, signature, artifact hashes, source identity, or release authority do not agree. A checkout of `main` is a development installation and is not the immutable v0.6.3 release.

## Controlled sequence

1. Close every blocking corrective and full-repair card with executed evidence.
2. Prepare a hash-locked wheelhouse and verify it offline from a scrubbed environment.
3. Commit the release candidate, create the matching annotated `v<version>` tag locally, and do not change product inputs.
4. Capture repository, commit, tree, tag, clean-state, and product-manifest identity.
5. Generate the canonical source-to-wheel/sdist artifact manifest, then build both archives exactly once into a run-specific external staging directory.
6. Extract both archives and reject every omission, undeclared entry, or projection hash mismatch. Test and install those exact bytes; a test may consume the staged wheel but may not rebuild it.
7. Generate the evidence manifest, SBOM, provenance, checksums, and certificate.
8. Sign the canonical certificate with the trusted Ed25519 publisher key. The private key must remain outside the repository.
9. Verify signature, evidence, artifacts, Git identity, version parity, and published-byte parity independently.
10. Package the complete evidence set as content-addressed chunks, sign its custody receipt, and publish those chunks with the release so verification does not depend on temporary CI retention.
11. Commit only non-product evidence, then atomically push the evidence commit and annotated tag. Publish the exact staged files as GitHub Release assets without rebuilding.

## Key rotation and revocation

Trusted public keys and fingerprints live in `policies/release-trust.json`. A successor key is added before it is used. One overlap release should be verified with the announced successor before the old key is marked revoked. Private keys are stored only in operator-controlled storage or a protected CI secret.

If a key or release is compromised, add its fingerprint to `revoked_fingerprints`, publish a revocation record signed by an unaffected trusted identity, and mark every affected certificate revoked. Historical certificates and evidence remain immutable and addressable; revocation adds authority state and never rewrites history.

Unsigned development reports must use a non-release status and are never accepted by `release verify`.

The runtime wheel follows the lean model documented in
`docs/distribution-model.md`. Release certification is permitted only on the
Python minors and operating systems declared by
`policies/platform-support.json`, and the certificate records the exact Python
version, implementation, operating system, platform string, and architecture
used by the certification run.
