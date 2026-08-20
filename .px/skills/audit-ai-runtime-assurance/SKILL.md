---
name: audit-ai-runtime-assurance
description: "Produce an opt-in, privacy-bounded cognitive assurance result and runtime passport from redacted identity, memory, knowledge, reasoning, correction, evidence, health, certification, drift, version, and benchmark signals. Use when an AI runtime, memory retrieval, persona, or model integration needs trust, poison, drift, health, or golden-benchmark certification."
---

# AI runtime and cognitive assurance

1. Require explicit opt-in and bounded retention before collecting telemetry.
2. Reject raw prompts, raw responses, secrets, tokens, credentials, or hidden reasoning.
3. Run `runtime.cognitive_assurance.evaluate_memory_trust` for each retrieved memory before use.
4. Validate runtime identity and personality against versioned baselines.
5. Measure behavior, knowledge, reasoning, prompt, and memory drift.
6. Run golden benchmarks and compute the cognitive EKG health signals.
7. Record only redacted hashes and evidence references through the append-only black-box recorder.
8. Build the ten-component runtime passport. Missing components, untrusted memory, drift, or benchmark failure yields degraded state.
9. Use the reality verifier to bind claims to current evidence and contradictions.
10. Perform no hidden network collection. Any exporter requires a separately admitted adapter and policy approval.

Apply `policies/runtime-assurance-privacy.json`. Certification covers observed, evidence-backed behavior only; it never certifies private reasoning or unobserved internals.
