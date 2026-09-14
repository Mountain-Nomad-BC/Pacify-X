---
canonical_id: "tests"
kind: system
layer: release
currentness: changed-file
runtime_observed: false
certified: false
---
# Governed section and profile gates

[[Layers/release]] · [[Views/Full_Architecture]]

## Purpose

Uses source-bound section/group receipts and explicit full-profile ownership to determine current test coverage.

## Historical source state

Section/group receipts, source inputs and test execution results.

## Limits and unknowns

Tests referenced by this report were inspected, not rerun; report validation is separate from PX certification.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3217]] — changed-file
- [[Evidence/S3204]] — changed-file
- [[Evidence/S3223]] — changed-file
- [[Evidence/S1961]] — changed-file
- [[Evidence/S2953]] — changed-file
- [[Evidence/S2132]] — same-file-bytes
- [[Evidence/S2813]] — same-file-bytes

## Directed relationships

- [[Systems/evidence]] — produces source-bound test receipts (`E105`)
- [[Systems/package]] — precedes owned packaging stage (`E106`)
- [[Systems/testorchestrationlease]] — claims physical or inherited ownership (`E847`)
- [[Systems/faultcampaignrunner]] — offers separate declared fault campaign (`E853`)
- [[Systems/testphaseadmission]] — checks exact processing stage before governed work (`E854`)
- [[Systems/testsectionpartition]] — resolves affected section and chunk commands (`E855`)
- [[Systems/testgroupindex]] — builds or reads group partition (`E856`)
- [[Systems/fixturecopyboundary]] — uses canonical ignore callback in scope fixture (`E1399`)
- [[Systems/bytecodestartup]] — specifies package startup cache allowance (`E1400`)
- [[Systems/quickstartlifecycle]] — defines an end-to-end demonstration fixture (`E1404`)
- [[Systems/completiontestauthority]] — defines projection and fixed routing fixtures (`E1414`)
