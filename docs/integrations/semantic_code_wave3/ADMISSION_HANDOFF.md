# Wave 3 Admission Handoff

Wave 3 is intentionally a **non-authoritative integration layer**. It exposes and normalizes semantic capabilities, but it does not mutate PX registries, grant effects, promote skills, or install model authority.

## What is ready after this wave

- explicit project-id → canonical-root registration
- read-only cross-project semantic queries through Wave 1
- capability projection by client context and operating mode
- read-only inspection of existing PX authority owners
- project-map/Atlas evidence normalization through the existing project-map retrieval owner
- semantic evidence binding into the existing evidence assembler
- deterministic query receipts and derived-evidence provenance
- dependency-clean hooks for Wave 4 retrieval, memory, and model-context modules

## Tiny internal model role

The resident tiny model is treated as a **governed PX operator**: librarian, concierge, and bounded grunt worker. The `local-model` context therefore exposes `READ`, `PLAN`, and `PROCESS` capabilities up to R1 so it can invoke PX-owned read tooling such as admitted LSP services. It does **not** expose `WRITE`.

Later learning triggers, graph/map maintenance, knowledge updates, and similar actions should be represented as explicit PX operations/workflows. The tiny model may request or trigger those operations when their conditions are met, but the authoritative owner, effect grant, policy decision, repository claim, and verification path remain outside the model.

## Governed follow-up

1. Install only after Waves 1 and 2 are present.
2. Re-run the focused Wave-3 suite and the combined semantic suites in the live repository.
3. Reconcile projected operations with current capability/effect/risk owners before authoritative registry admission.
4. Admit Wave-4 retrieval/memory/model-context modules separately; Wave 3 does not pretend those modules are installed.
5. Bind any graph/project-map updates only through the current project-map/Atlas builder authority.
6. Bind learning triggers only through the current learning-promotion and evidence owners.
7. Add release/installed-host certification contracts only after the live architecture accepts the new files.
8. Run current frozen source/release/installed-host certification under the then-current authority set.

Do not copy candidate metadata directly into authoritative registries without reconciliation.
