# Pacify-X Adds Integration Disposition

## Intake identity

- Source: externally supplied `pacify x adds` intake (host path intentionally omitted)
- Snapshot A: 99 files, 258,490 bytes, SHA-256 `2ca4a76d04bce0fdc3f1890b7a4067ca14986c903695abcc15515a92733aad22`
- Snapshot B: 99 files, 258,490 bytes, SHA-256 `2ca4a76d04bce0fdc3f1890b7a4067ca14986c903695abcc15515a92733aad22`
- Source handling: read-only evidence; no source file was executed, copied wholesale, moved, or deleted.
- Intake state: open until the user explicitly closes it.

The two nested enhancement packs substantially duplicate each other. Their code is unlicensed reference material, so implementation was clean-room and behavior-led. The current Pacify-X repository remains canonical.

## Canonical owner map

| Responsibility | Canonical owner |
|---|---|
| Frozen treatment, retry, preflight, contamination, comparison, custody | `runtime/benchmark_operations.py` |
| Behavioral probes, case lineage, attribution, coverage frontier, assurance gates | `runtime/behavioral_assurance.py` |
| CPU/CUDA eligibility, equivalence, resource and fallback routing | `runtime/hardware_routing.py` |
| Release evidence archives and reconstruction | `runtime/evidence_custody.py` |
| Typed claim/evidence assembly | `runtime/evidence_assembler.py` |
| Capability and improvement admission | `runtime/admission_controller.py` |
| Authoritative completion decision | `runtime/outcome_verifier.py` |
| Contract validation and ownership | `runtime/contracts.py`, `registry/contract_ownership.json` |

## Dispositions

| Enhancement concept | Disposition | Result |
|---|---|---|
| Benchmark execution profile and treatment freeze | ADMIT_NEW | Native content-addressed profile and mutation detection |
| Retry budget as treatment | MERGE_INTO_EXISTING | Benchmark-specific decision wraps the existing bounded retry doctrine |
| Oracle/harness/dependency preflight | ADMIT_NEW | Failure-closed scoring gate |
| Cold benchmark contamination firewall | MERGE_INTO_EXISTING | Explicit cold-lane visibility and benchmark-informed-change checks |
| Matched PACIFY-X ON/OFF control | ADMIT_NEW | Comparison hash ignores activation only |
| Benchmark evidence custody | MERGE_INTO_EXISTING | Run-level hashing complements release custody without replacing it |
| Infrastructure versus graded failure | ADMIT_NEW | Multi-cause classification and non-graded boundary |
| Hardware equivalence | RETAIN_EXISTING | Existing hardware router remains authoritative; companion contract added |
| Behavioral probe | ADMIT_NEW | Positive plus discriminating control; constant-output mutation test |
| Evaluation lineage and visibility | ADMIT_NEW | Generated cases and judges cannot self-certify |
| Failure attribution | ADMIT_NEW | Multi-contributor, uncertainty-preserving, non-mutating result |
| Coverage frontier | ADMIT_NEW | Sanitized demand clustering remains candidate-only, never an oracle |
| Improvement candidate priority | ADMIT_NEW | Bounded score; admission required; mutation denied |
| Multi-axis assurance | ADMIT_NEW | Every axis must pass; averages cannot hide a failed gate |
| Duplicate nested files and tests | REJECT_DUPLICATE | No duplicate runtime, schema, or test trees imported |
| Reference implementation identifiers and packaging | REJECT_UNSAFE | No unlicensed source copied into runtime |
| Official external benchmark run | DEFER | Requires a named suite, authority, credentials, and run budget |
| Paid GPU or cloud run | DEFER | No workload in this integration justified external compute |

## Validation boundary

The implementation can certify its deterministic controls, contracts, packaging, and negative behavior tests. It does not claim performance on an external benchmark, model quality, cloud-provider behavior, or production effectiveness without executing those separately under a frozen profile.
