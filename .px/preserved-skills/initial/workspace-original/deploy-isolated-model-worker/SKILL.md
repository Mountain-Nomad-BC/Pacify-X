---
name: deploy-isolated-model-worker
description: Design, provision, validate, and recover an isolated accelerator-backed worker for inference, embedding, or reranking without coupling model dependencies to the primary application. Use when a project needs a local GPU/accelerator service, model warmup, health contracts, or a replaceable ML worker boundary.
---

# Deploy Isolated Model Worker

Treat deployment as an explicit external effect.

1. Record accelerator, memory, model, context, concurrency, privacy, and latency requirements.
2. Produce a worker manifest and environment template without credentials or machine-specific paths.
3. Pin dependencies in an isolated environment; never force-upgrade the host environment.
4. Expose versioned health, readiness, warmup, inference, embedding, and reranking contracts only as required.
5. Bind to the narrowest interface, authenticate callers, bound payloads/timeouts/concurrency, and redact logs.
6. Start through the platform service manager when possible. If detached execution is approved, record PID, command hash, logs, and stop procedure.
7. Verify cold start, warm start, resource pressure, cancellation, model unload, and fallback behavior.
8. Preserve a rollback plan that restores the prior worker endpoint and dependency set.

Do not download models, install packages, open ports, or start processes without explicit approval.
