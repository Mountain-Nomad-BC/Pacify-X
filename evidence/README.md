# Evidence authority index

PACIFY-X is the project and framework. `engineering-bootstrap` is its Python package and command-line control plane.

## Current authority

Release 0.6.3 is the current deployment-authoritative, self-certified release. The clean annotated tag, exact wheel and source archive, trusted publisher signature, immutable run evidence, and a separate public-download verification agree. Release 0.6.2 remains explicitly revoked.

- Revocation decision source commit: `783b8b10d833eb4d6b0bda4291ad8b2afd7d55a8`
- Current release: [`v0.6.3`](https://github.com/Mountain-Nomad-BC/Pacify-X/releases/tag/v0.6.3)
- Release commit: `20dd8da01ba1307eb853ff64f2db42d94e0fad79`
- Certificate: [`releases/0.6.3/certificate.json`](releases/0.6.3/certificate.json)
- Detached signature: [`releases/0.6.3/certificate.json.sig`](releases/0.6.3/certificate.json.sig)
- Certification workflow: [GitHub Actions run 30882737975](https://github.com/Mountain-Nomad-BC/Pacify-X/actions/runs/30882737975), artifact SHA-256 `f3fb7b5eb7c848cd51aef724d9d18ae3e6694f9e599c1f7298c198644772d343`
- Public-download verification: [`releases/0.6.3/public-release-verification.json`](releases/0.6.3/public-release-verification.json)
- Publisher fingerprint: `SHA256:aQC1XhpHq6hbFMK2vv7cKFgxLEXJVmnprjfZKTn12Ms`
- Wheel SHA-256: `f5163781a6bfe6258a361a17eb130876ea3e026ed4871260c6c2524e7d843dee`
- Source archive SHA-256: `ae4f736ea7e08bc7bb4e3c68c6dc486d5675fb559e3148d890552f89683bf9af`
- Revocation record: [`release-revocation-0.6.2.json`](release-revocation-0.6.2.json)
- Historical certificate: [`release-certification-0.6.2.json`](release-certification-0.6.2.json)
- Historical run: [`release-runs/rel-0.6.2-0a059f670913/`](release-runs/rel-0.6.2-0a059f670913/)
- Signing trust policy: [`../policies/release-trust.json`](../policies/release-trust.json)
- Verification command with the certificate evidence materialized at its recorded paths: `engineering-bootstrap release verify --release 0.6.3 --artifact-dir <downloaded-release-asset-directory>`

The values above come from the signed certificate and observed public downloads, not from predeclared expectations. The complete run bundle is retained outside the deployable Git tree because its uncompressed coverage record exceeds GitHub's 100 MB per-file limit; its GitHub artifact digest and external custody are recorded in the public verification receipt. The release tag remains immutable; later documentation or planning commits on `main` do not change the certified source tree.

## Authority classes

- `releases/`: immutable, signed evidence for releases that passed their included validation profile.
- `revoked/`: indexes and explanatory records for certificates whose authority was withdrawn. Original records remain unchanged at their historical paths.
- `history/`: superseded development reports and self-assessments with no current release authority.
- `audits/`: external and internal audit inputs plus their dispositions.
- `migrations/`: source-intake, assimilation, and migration custody receipts.
- `release-runs/`: run-scoped historical evidence; a run has no authority unless referenced by a valid signed certificate.
- `declared-suite/`: reconstruction and domain-pack evidence, not a product release certificate.
- `bundles/`: retained archive-custody inventories.
- `repairs/`: bounded reconnaissance, punch-card, compatibility, merge, and validation receipts for post-release development repairs; these do not alter an existing release certificate.

The current trust-boundary hardening package begins at [`repairs/trust-boundary-hardening/PUNCH_CARD_LEDGER.md`](repairs/trust-boundary-hardening/PUNCH_CARD_LEDGER.md), with validation in [`VALIDATION_RECEIPT.md`](repairs/trust-boundary-hardening/VALIDATION_RECEIPT.md) and deferred external actions in [`DEFERRED_FINDINGS.md`](repairs/trust-boundary-hardening/DEFERRED_FINDINGS.md).

## Revoked certificates

| Release | Status | Record | Limitation |
|---|---|---|---|
| 0.6.1 | Revoked | [`release-revocation-0.6.1.json`](release-revocation-0.6.1.json) | Superseded historical self-assessment. |
| 0.6.2 | Revoked | [`release-revocation-0.6.2.json`](release-revocation-0.6.2.json) | Did not authenticate exact public artifacts, Git identity, publisher identity, and all required evidence as one chain. |

## Limitations and audit disposition

Self-certification proves only that the included validation profile ran against the recorded inputs. It is not independent certification, a security warranty, or proof about undeclared environments. External audit findings and their repository disposition begin at [`external-audit-disposition-20260803.json`](external-audit-disposition-20260803.json). The 42-card full-repair ledger is closed by the signed release evidence and separate public-asset reproduction receipt.
