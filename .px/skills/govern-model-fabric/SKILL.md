---
name: govern-model-fabric
description: Govern admitted local-model profiles, pool residency, routing evidence, capacity, binary/model identity, health, cancellation and fallback without bypassing PX runtime authorities.
---

# Govern Model Fabric

Use this skill for **operational governance of already-admitted model lanes**. Planning model feasibility remains `plan-local-model-deployment`; device choice remains `hardware-aware-execution-routing`; isolated worker deployment remains `deploy-isolated-model-worker`.

## Operating sequence

1. Resolve the exact model ID, GGUF SHA, runtime profile ID/revision, runtime executable SHA/capability fingerprint, project scope, and requested lane.
2. Inspect pool residency, health, resource interlock, active route state, capacity/backpressure and current benchmark evidence before changing anything.
3. Prefer deterministic PX routing. Use the Qwen3.5-0.8B control lane only for bounded ambiguity/reranking work and the deep Qwen3-30B-A3B lane only when task complexity justifies it.
4. Treat load, unload, launch, restart, route promotion and profile activation as effects owned by their existing PX runtimes. This skill may plan/request them; it never invents authority.
5. Diagnose route collapse, repeated fallback, queue pressure, stale benchmark/profile identity, executable drift, model drift and resource conflicts from receipts rather than prose.
6. On failure, preserve cancellation custody, process ownership, resource reconciliation and the last known-good route/profile.
7. Promote no candidate model/profile/runtime without frozen identity plus the required target-host evidence.

## Hard boundaries

- A localhost endpoint is not an admitted model.
- Model output is never execution authority.
- Do not silently weaken privacy, context, quality, evidence or resource gates to make a route fit.
- Do not use this skill to install a runtime/model or modify source without the separate owning authority.
- Pool health and routing diagnosis are modes of this skill; do not create duplicate pool/routing authorities.

## Completion

Return the selected/admitted lane, exact identities, route reasons, capacity/resource evidence, requested effects, fallback/rollback and receipt/evidence requirements.
