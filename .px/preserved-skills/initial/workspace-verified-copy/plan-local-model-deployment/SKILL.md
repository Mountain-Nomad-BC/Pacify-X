---
name: plan-local-model-deployment
description: Build a constraint-first feasibility matrix for local model inference, conversion, offload, streaming, quantization, retrieval augmentation, or remote fallback. Use when selecting a local model/runtime strategy, checking RAM/VRAM/disk fit, planning transformation caches, ranking constrained execution options, or defining validation and rollback gates before deployment.
---

# Plan Local Model Deployment

1. Inspect the model with `inspect-llm-architecture` when a trustworthy normalized profile is not already available.
2. Inventory available RAM, VRAM, disk, sustained storage bandwidth, accelerator/runtime compatibility, workload, privacy, latency, throughput, context, batch, and quality floors.
3. Run `scripts/plan_local_model_deployment.py --inventory INVENTORY.json` to produce a deterministic feasibility matrix.
4. Distinguish native fit, quantization, CPU/GPU offload, layer or expert streaming, smaller-model substitution, retrieval augmentation, and policy-allowed remote fallback.
5. Treat conversion and quantization outputs as fingerprinted build artifacts with source, temporary, rollback, and transformed storage preflight.
6. Rank only feasible or conditional options. Preserve why every rejected option failed.
7. Require compatibility, task-quality, cold/warm performance, cancellation, recovery, and artifact-integrity validation before activation.

Read [local-model-planning-contract.md](references/local-model-planning-contract.md) for the inventory schema, ranking rules, and deployment gates.

## Completion

Return the complete feasibility matrix, ranked candidates, blocking unknowns, required measurements, artifact budget, rollback plan, and explicit statement that no model, tool, or runtime was installed or executed by the planner.
