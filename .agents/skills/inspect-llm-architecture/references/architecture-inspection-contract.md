# Architecture inspection contract

## Required evidence

- Original field name for every normalized value.
- Explicit marker for inferred defaults.
- Unresolved fields and contradictions.
- Formula version and workload assumptions.
- Security statement confirming that no model or remote code was executed.

## Core estimates

- Head dimension: `hidden_size / query_heads`.
- KV cache: `layers * 2 * kv_heads * head_dim * tokens * batch * beams * bytes_per_element`.
- Attention projections: query, key, value, and output matrices with GQA/MQA head counts respected.
- Dense FFN: two projections; gated FFN: three projections.
- Embeddings and output head: count one copy when weights are tied and two otherwise.
- Weight storage: `parameters * bits_per_weight / 8`; runtime allocations and quantization metadata are additional.

MoE estimates must distinguish total expert parameters from active routed expert parameters. Treat routing balance, shared experts, capacity factors, and communication overhead as unresolved until the actual implementation is inspected.

## Hostile-input limits

Reject non-integer dimensions, booleans, non-positive sizes, incompatible head divisibility, excessive dimension/count limits, and inputs that would create unbounded calculations. A locally stored configuration is not automatically trusted.

## Validation boundary

Architecture estimates do not certify runtime support, effective context, throughput, numerical quality, kernel availability, or peak memory. Measure those in the intended runtime and environment.
