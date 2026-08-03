# Architecture, Governance, and Risk

## Confirmed architecture

- Python 3.11+ standard-library runtime with an installable console command.
- Compact JSON/TOML registries and policy summaries at startup.
- Skill bodies retained in the installed framework, addressed by hash, and hydrated explicitly after selection.
- Project-local `.engineering-bootstrap/` namespace for durable control state and collision-safe adoption.
- Human-readable `PROJECT_MANAGEMENT.md` plus schema-backed state and append-only evidence/checkpoints.
- Separate capability, I/O, dependency/effect, and system graphs; admitted handlers execute bounded workflows.

## Governance

Read-only discovery precedes proposal. Writes, installs, network access, services, migrations, privileged actions, security-sensitive testing, and deployment require declared effects and approval. Existing owners are preserved. Cleanup moves hash-reconciled artifacts into recoverable quarantine. Completion requires independent postcondition evidence.

## Model and integration boundary

The framework records model capability and availability metadata but assumes no model, provider, tool, MCP, credential, or external integration is available. Optional adapters cannot override policy or project boundaries.

## Primary risks and mitigations

| Risk | Mitigation | Release evidence |
|---|---|---|
| Context overload | Metadata-only startup, three-candidate budget, explicit one-body hydration | startup and lazy-loader tests |
| Existing repository overwrite | per-file preserve/create plan and namespace-owned controls | existing-project adoption and clean-wheel tests |
| False completion | typed postconditions and independent verifier | outcome-verifier tests |
| Stale resume | identity/repository/effect drift validation | checkpoint-resume test |
| Packaging omissions | install wheel in fresh environment and execute both modes | installed-wheel end-to-end test |
| Irrecoverable cleanup | hash inventory, quarantine move, post-move reconciliation | quarantine tests and receipts |
| Untrusted external content | staged admission, provenance, effects, tests, and no automatic activation | admission and contained-execution tests |

## Residual boundary

Framework certification proves the bootstrap package and generic commissioning flows. It does not certify a user's future application, legal compliance, production deployment, external provider, or project-specific security posture.
