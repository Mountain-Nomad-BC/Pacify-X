# Evidence authority index

PACIFY-X is the project and framework. `engineering-bootstrap` is its Python package and command-line control plane.

## Current authority

There is no deployment-authoritative release at present. Release 0.6.2 is explicitly revoked. Version 0.6.3 is a validated release candidate, but it remains non-authoritative until the finalizer binds one annotated Git tag to one exact wheel/sdist set, a trusted publisher signature, immutable evidence, and an independent public-download verification.

- Revocation decision source commit: `783b8b10d833eb4d6b0bda4291ad8b2afd7d55a8`
- Candidate release identity: generated from the eventual annotated `v0.6.3` tag; no expected commit or tree is predeclared.
- Revocation record: [`release-revocation-0.6.2.json`](release-revocation-0.6.2.json)
- Historical certificate: [`release-certification-0.6.2.json`](release-certification-0.6.2.json)
- Historical run: [`release-runs/rel-0.6.2-0a059f670913/`](release-runs/rel-0.6.2-0a059f670913/)
- Signing trust policy: [`../policies/release-trust.json`](../policies/release-trust.json)
- Verification command: `engineering-bootstrap release verify --release <version> --artifact-dir <exact-artifact-directory>`

Artifact hashes, commit/tree/tag identity, evidence-manifest hash, and signing identity are intentionally absent from the current-authority section because 0.6.3 has not yet passed final publication. The finalizer writes them from observed evidence; this index is updated only from that signed certificate and public download receipt, never from an expectation.

## Authority classes

- `releases/`: immutable, signed evidence for releases that passed their included validation profile.
- `revoked/`: indexes and explanatory records for certificates whose authority was withdrawn. Original records remain unchanged at their historical paths.
- `history/`: superseded development reports and self-assessments with no current release authority.
- `audits/`: external and internal audit inputs plus their dispositions.
- `migrations/`: source-intake, assimilation, and migration custody receipts.
- `release-runs/`: run-scoped historical evidence; a run has no authority unless referenced by a valid signed certificate.
- `declared-suite/`: reconstruction and domain-pack evidence, not a product release certificate.
- `bundles/`: retained archive-custody inventories.

## Revoked certificates

| Release | Status | Record | Limitation |
|---|---|---|---|
| 0.6.1 | Revoked | [`release-revocation-0.6.1.json`](release-revocation-0.6.1.json) | Superseded historical self-assessment. |
| 0.6.2 | Revoked | [`release-revocation-0.6.2.json`](release-revocation-0.6.2.json) | Did not authenticate exact public artifacts, Git identity, publisher identity, and all required evidence as one chain. |

## Limitations and audit disposition

Self-certification proves only that the included validation profile ran against the recorded inputs. It is not independent certification, a security warranty, or proof about undeclared environments. External audit findings and their repository disposition begin at [`external-audit-disposition-20260803.json`](external-audit-disposition-20260803.json); the 42-card full-repair ledger remains controlling until the exact published assets are independently reproduced.
