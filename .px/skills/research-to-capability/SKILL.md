---
name: research-to-capability
description: Convert papers, standards, benchmarks, and sourced technical research into bounded candidate capabilities with claims, methods, assumptions, prerequisites, operational value, lineage, limitations, tests, and admission evidence. Use when research may inform tooling or orchestration without treating publication as production proof.
---

# Research to Capability

1. Record the exact source, citation, version/date, license, and access boundary.
2. Extract claim, method, assumptions, prerequisites, evaluation setting, limitations, and unsupported extrapolations.
3. Read [candidate-contract.md](references/candidate-contract.md), select the matching contract under `contracts/research_ops`, and run `engineering-bootstrap research validate --kind <kind> --record <record.json>`.
4. Map operational value to an existing capability gap only after the typed record passes.
5. Prefer a proposal or experiment; never activate paper-derived behavior directly.
6. Add positive, negative, failure-boundary, and reproduction tests.
7. Admit only after local evidence supports the intended operating context.
