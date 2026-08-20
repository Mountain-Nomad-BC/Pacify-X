# Local model planning contract

## Inventory

Provide:

- `hardware`: available RAM/VRAM, free disk, sustained disk read bandwidth, accelerator/runtime compatibility.
- `model`: estimated weight size, transformed size, architecture support, streaming support, and optional quantized sizes.
- `workload`: context, batch, KV-cache estimate, latency/throughput goals, quality floor, privacy requirement, and remote-fallback permission.

Unknown values remain blockers or conditional gates; they are never silently replaced by optimistic guesses.

## Strategy rules

- Native accelerator execution requires bounded VRAM headroom.
- CPU/GPU offload requires combined memory headroom and a measured transfer budget.
- Quantization requires task-quality comparison against a representative baseline.
- Layer/expert streaming is a memory strategy whose storage traffic and low-throughput risk must be visible.
- Retrieval augmentation is not a substitute for evaluating retrieval quality and authorization.
- Remote fallback is forbidden when privacy policy or caller constraints disallow it.

## Artifact budget

Preflight source, transformed, temporary, and rollback generations independently. Transformation must be fingerprinted, resumable, idempotent, verified before source retirement, and recoverable.

## Release gates

Require model/runtime compatibility, task-quality, cold/warm latency, throughput, peak RAM/VRAM, storage traffic, cancellation, corruption handling, rollback, and evidence freshness. A strategy matrix is a plan, not permission to install or execute a runtime.
