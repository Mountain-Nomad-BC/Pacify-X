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
10. After the final successor campaign succeeds, package the complete release evidence, exact wheel/sdist directory, immutable VSIX, and its installed-operational summary into content-addressed chunks. The local packager validates the full installed-host denominator, cross-binds its product/harness identity to the signed certificate, and signs the custody receipt with the operator-held key.
11. Push the admitted evidence commit and annotated tag, create a draft GitHub Release, and upload only the signed receipt, detached receipt signature, receipt-listed chunks, and the standalone byte-identical VSIX. Do not rebuild, re-certify, or place a private key in CI.
12. Manually dispatch `.github/workflows/release.yml` for that tag. It authenticates and reconstructs custody, independently verifies the certificate and Python artifacts, exercises the exact VSIX, publishes that VSIX to Marketplace with OIDC, and only then makes the existing GitHub draft public. Its duplicate-safe Marketplace step and draft-state check make a partial rerun idempotent.

For v0.7.0, prepare the local custody handoff only after the successful successor candidate certificate exists. Bind the package to the candidate and installed-operational summary that produced that certificate:

```powershell
$release = "0.7.0"
$tag = "v$release"
$assets = Join-Path $env:TEMP "pacify-x-$tag-draft-assets"
$work = Join-Path $env:TEMP "pacify-x-$tag-custody-work"
$artifactDir = "<artifact_dir returned by release finalize>"
$candidate = "<candidate_id from the installed-operational summary>"
$summary = "<path to that candidate's installed-operational summary>"
$vsix = "extension/dist/pacify-x-vscode-0.6.87.vsix"
New-Item -ItemType Directory -Path $assets | Out-Null
Copy-Item -LiteralPath $vsix -Destination $assets
python -B scripts/package_release_evidence.py `
  --root . `
  --input "evidence/releases/$release" `
  --input $artifactDir `
  --release $release `
  --source-commit (git rev-list -n 1 $tag) `
  --certificate "evidence/releases/$release/certificate.json" `
  --candidate-id $candidate `
  --vsix $vsix `
  --installed-summary $summary `
  --output $assets `
  --work-dir $work `
  --locator-base "https://github.com/Mountain-Nomad-BC/Pacify-X/releases/download/$tag" `
  --signing-key ".git/pacify-x-release-key-2026"
```

On an admitted network-capable operator host, create the draft and upload the exact denominator without a wildcard:

```powershell
$receiptPath = Join-Path $assets "pacify-x-v$release-complete-evidence-custody.json"
$receipt = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
gh release create $tag --draft --verify-tag --title "PACIFY-X $release"
gh release upload $tag $receiptPath "${receiptPath}.sig" (Join-Path $assets "pacify-x-vscode-0.6.87.vsix")
foreach ($chunk in $receipt.chunks) {
  gh release upload $tag (Join-Path $assets $chunk.filename)
}
gh workflow run release.yml -f "release_tag=$tag"
```

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
