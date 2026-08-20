---
name: gate-model-data-lifecycle
description: Gate training, evaluation, fine-tuning, adapter, and conversion inputs by provenance, license, consent, privacy, content hashes, split leakage, labels, drift, supply-chain integrity, and rollback evidence. Use before preparing datasets, behavior packs, model adapters, conversion jobs, or model promotion.
---

# Gate model and data lifecycle

1. Inventory records and artifacts without loading a model or running external conversion code.
2. Require source identity, content hash, license or authority, consent basis, label, split, and sensitive-data disposition.
3. Run `runtime.foundation_assurance.gate_model_dataset`; block duplicate IDs, invalid hashes, unapproved rights, privacy violations, invalid splits, and content/subject leakage.
4. Run `evaluate_numeric_shift` on declared numeric features; empty, constant, and non-finite inputs must be handled explicitly.
5. Pin and verify every model, adapter, converter, dependency, and remote script. Quarantine unpinned downloads or subprocess launchers pending supply-chain review.
6. Separate dataset admission, training execution, evaluation, packaging, and promotion into distinct approvals and receipts.
7. Promote only after independent benchmarks, negative tests, artifact hashes, rollback, and resource limits pass.

Read [model-data gate](references/model-data-gate.md) for the required ledger and lifecycle boundaries.

This skill performs metadata admission only. It never trains, converts, loads, deploys, or promotes a model.
