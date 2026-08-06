---
name: hardware-aware-execution-routing
description: Discover local CPU, CUDA, VRAM, provider, Windows, WSL2, Linux, and container capabilities; classify workloads; and choose an explainable execution device using compatibility, resource limits, current end-to-end benchmark evidence, correctness, determinism, bounded retries, and CPU fallback. Use for GPU acceleration, CUDA/ONNX/PyTorch routing, hardware reports, workload placement, VRAM/OOM policy, optional WSL2 analytics, or deciding whether acceleration is justified.
---

# Hardware-Aware Execution Routing

Use `runtime.hardware_routing` as the canonical decision runtime. Read
`references/routing-policy.md` before adding an accelerator, changing precision,
or treating benchmark evidence as current.

## Workflow

1. Classify the workload before probing a device.
2. Keep filesystem traversal, operating-system calls, ordinary database work,
   serialization, safety rules, and reports on CPU.
3. Probe hardware and optional libraries gracefully; record missing dependencies
   and probe failures without failing CPU startup.
4. Enumerate only compatible backends for the actual environment. Keep native
   Windows NTFS traversal on Windows; use WSL2 only for optional Linux-first
   analytics over batched exchange files.
5. Apply the free-VRAM reserve, configured VRAM fraction, minimum workload size,
   batching, determinism, and correctness gates.
6. Require current end-to-end benchmark evidence for automatic GPU routing. Count
   initialization, transfers, synchronization, and result transfer.
7. Declare CPU fallback, bounded OOM retries, and the exact routing reason.
8. Execute with telemetry, validate CPU/GPU equivalence, and invalidate evidence
   when hardware, driver, runtime, model, or provider fingerprints change.

## Runtime interface

- Report: `python -m runtime.cli hardware report`
- Route: `python -m runtime.cli hardware route --kind embedding --items 100000 --bytes 209715200 --batchable`
- Supply benchmark evidence with `--benchmark <json>`; automatic routing otherwise
  stays on CPU.

## Boundaries

- Never route work merely because CPU utilization is high or a GPU exists.
- Never move the core file walk, cleanup authorization, or destructive decision to
  probabilistic or GPU inference.
- Never install optional accelerator stacks into the base environment implicitly.
- Never transmit inventories or paths externally through this skill.
