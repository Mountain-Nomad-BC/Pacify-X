---
canonical_id: "certificate"
kind: system
layer: release
currentness: changed-file
runtime_observed: false
certified: false
---
# Signed release certification

[[Layers/release]] · [[Views/Full_Architecture]]

## Purpose

Combines ordered gates, exact artifact identity and operational evidence into verifiable signed certification.

## Historical source state

Certificate, evidence manifest, signatures and trust policy.

## Limits and unknowns

User reports Marketplace publication and verification; this report does not independently re-certify or verify Marketplace status.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2861]] — changed-file
- [[Evidence/S2952]] — changed-file

## Directed relationships

- [[Systems/custody]] — binds certificate to retained evidence bytes (`E195`)
- [[Systems/exactharness]] — executes uncached exact tool release gate (`E310`)
- [[Systems/sanitationcontrols]] — assembles separate sanitation evidence (`E358`)
- [[Systems/completionprojection]] — supplies exact release verification when eligible (`E361`)
- [[Systems/coveragecounts]] — generates coverage and validates policy totals (`E744`)
- [[Systems/fullrepairlabels]] — checks ledger with finalizer pending exemptions (`E809`)
- [[Systems/buildcountfacts]] — has separate source-count evidence surface (`E816`)
- [[Systems/releasecontextpresence]] — requires repository authorities before gates (`E817`)
- [[Systems/releasegithistory]] — rechecks certificate Git references (`E823`)
- [[Systems/releasemanifestbytes]] — verifies signed-certificate-bound manifest file (`E824`)
- [[Systems/releaseskiplist]] — checks skip policy beside test totals (`E825`)
- [[Systems/preflightreceipt]] — revalidates receipt before finalization (`E838`)
- [[Systems/certificationfreeze]] — enters finalization after current preflight (`E840`)
- [[Systems/correctivecardledger]] — checks historical blocking labels (`E924`)
