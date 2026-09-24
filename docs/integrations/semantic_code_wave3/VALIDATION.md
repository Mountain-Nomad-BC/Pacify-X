# Wave 3 Validation — Current PX Snapshot

Validation was performed on 2026-09-20 against the supplied `Pacify-X-main (1).zip` snapshot with the finished Wave 1 and Wave 2 payloads overlaid first.

## Boundary repair

The original semantic Wave-3 source release contains 66 payload files. The pre-implementation placement plan intentionally divided those into:

- **41 Wave-3 integration-core files**
- **25 Wave-4 memory/model/retrieval files**

A clean 41-file overlay initially exposed three illegal forward dependencies at test collection (`semantic_memory_relocation`, `semantic_local_model_bridge`, and `semantic_orchestration`). This implementation pass repaired the boundary instead of pulling Wave 4 forward.

Wave-4 surfaces are now lazy/optional, shared test support no longer imports Wave 4 eagerly, and the project-map degradation test exercises the core boundary directly.

## Wave-3 focused suite

**28 passed**.

Coverage includes:

- deterministic context/mode capability projection
- local-model read/plan/process exposure with no write exposure
- automatic denial of unavailable Wave-4 operations
- cross-project authorization, expiry, project/operation scope, strict argument typing
- explicit project catalog identity and concurrent borrowing
- read-only semantic querying
- project-map evidence normalization and non-finite score rejection
- missing-project-map behavior without loss of independent semantic reads
- read-only authority inspection
- deterministic bounded query receipts
- derived evidence provenance
- duplicate evidence identity rejection
- evidence-assembler binding
- dependency-clean top-level integration service
- strict project registration/label semantics

## Combined semantic regression

Wave 1 + Wave 2 + Wave 3 focused semantic suites:

**127 passed**.

## Current-PX neighborhood regression

Relevant neighboring callers were run separately to avoid one large outer-process timeout masking results:

- file lock contention: 9 passed, 1 skipped
- runtime lifecycle: 3 passed
- process-lifecycle WAL boundaries: 21 passed
- WAL transaction: 26 passed
- WAL generation: 66 passed
- platform support: 7 passed
- workspace manager: 32 passed

Total: **164 passed, 1 skipped**.

## Compile/static checks

- targeted Python `compileall`: **PASS**
- Ruff: not installed in this container, so no Ruff claim is made

## Real-tree smoke

Against the assembled current PX snapshot:

- registered the repository as an explicit read-only semantic project
- found `runtime.authority_topology.resolve_effect_authority`
- verified observational `workspace-write` authority is denied
- resolved `provider_execution` authority to `runtime/provider_gateway.py::execute_provider_request`
- inventory reported 20 currently available operations across Waves 1–3

## Remaining limitations

- This is not whole-repository certification.
- Windows-specific installed-host/process behavior still requires the live Windows certification path.
- Wave-4 retrieval/memory/model-context behavior is deliberately absent from this package and must be validated in the next wave.
- No authoritative registry, project-map generator, release identity, or certification contract is changed by this wave.
