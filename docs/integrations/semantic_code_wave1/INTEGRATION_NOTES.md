# Integration Notes

## Scope

Wave 1 is an additive semantic-code substrate for PACIFY-X. It provides deterministic, bounded source acquisition, structural analysis, symbol/reference queries, diagnostics, edit planning, guarded preview/application, lifecycle ownership, and receipts.

The implementation was reviewed and validated against the exact user-supplied `Pacify-X-main (1).zip` snapshot dated 2026-09-20. All 53 Wave-1 repository destinations are new in that snapshot.

It does **not** edit existing PX authorities such as generated-artifact ownership, Atlas, source inventory, release manifests, provider/model routing, memory/knowledge promotion, skills, orchestration, or certification scripts. Those integrations must be reconciled through their current owners after placement.

## Relationship to the PX tiny internal model

This substrate is intentionally suitable for the resident tiny CPU model that will later act as PX's governed librarian/concierge/grunt worker. The model may eventually use admitted operations from this layer to:

- locate symbols and implementation surfaces before preparing context for a larger model;
- inspect diagnostics and source topology;
- build bounded evidence packets for skills, workflows, maps, graphs, and knowledge retrieval;
- prepare revision-bound edit plans;
- verify that a planned source target still matches its expected revision.

The model does **not** receive filesystem authority from this package. Later orchestration/contract waves must mediate operation selection, effect grants, queue admission, learning triggers, graph/map mutation, knowledge promotion, and escalation to larger models. `SemanticCodeService(allow_writes=False)` remains the default.

## Intended model hierarchy

- **Resident internal operator:** Qwen3.5-0.8B is the primary tiny-CPU candidate, subject to target-machine benchmarking and structured-output reliability. It should remain resident if measured RAM/latency are acceptable.
- **Deep local model:** Qwen3-30B-A3B is the preferred initial deep sparse lane for difficult synthesis/reasoning/coding, subject to the later model-fabric benchmark/profile freeze.
- **Deterministic PX code remains first.** Exact IDs, authority, permissions, contracts, queue state, registry state, and admission decisions stay deterministic. Models consume those contracts; they do not replace them.

## Recommended placement order

1. Start from the exact intended PX snapshot/worktree and record its identity.
2. Copy the Wave-1 payload to the repository paths listed in the package `01_INSTALL_MAP.md`.
3. Run the focused semantic-code tests.
4. Run the neighborhood regression set documented in `03_VALIDATION.md`.
5. Run the current PX source-inventory / generated-authority reconciliation process. Do not copy generated authorities from this package.
6. Review any source-denominator, architecture-Atlas, capability, skill, workflow, or certification changes produced by the live repository's own current builders.
7. Only then admit higher-level model/tool/orchestration surfaces.

## Minimal read-only use

```python
from pathlib import Path
from runtime.semantic_code_service import SemanticCodeService

service = SemanticCodeService()
summary = service.project_summary(Path('.'))
result = service.find_symbols(Path('.'), 'FileLock', substring=True)
```

Mutation remains disabled unless a service is deliberately constructed with `allow_writes=True`, and later PX authority should sit above that constructor-level gate.
