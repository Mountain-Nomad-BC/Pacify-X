# Execution Plan, Punch Cards, and Acceptance

This is the compact operational plan for maintaining and releasing PACIFY-X. `PROJECT_MANAGEMENT.md` and `.engineering-bootstrap/project-management/state.json` own the live card and lifecycle state; this document defines the reusable process and must not be pinned to a historical card.

## Execution waves

1. Reconcile the requested outcome, repository instructions, current state, and evidence.
2. Inventory affected owners and declare effects, approvals, dependencies, rollback, and acceptance evidence.
3. Implement one bounded card at a time; update registries and generated maps only after the implementation validates.
4. Run focused positive, negative, failure-policy, rollback, and integration checks.
5. Rebuild deterministic projections and reconcile package contents.
6. Run the full source, exact-tool, structural, sanitation, distribution, and installed-wheel gates.
7. Publish certification only through the atomic digest-bound finalizer.

## Punch-card contract

Every material card records an owner, scope, prerequisites, declared effects, approval boundary, implementation surfaces, tests, evidence, rollback, residual risk, and terminal disposition. A card is complete only when implementation, wiring, discovery, documentation, generated maps, and current evidence agree.

The active card and its evidence are listed in `PROJECT_MANAGEMENT.md`. Historical cards and revoked certificates remain audit evidence; they are not active instructions.

## Approval checkpoints

Preview must precede mutation. User-project writes, installs, network access, services, secrets, migrations, destructive or security-sensitive work, and deployment require explicit approval. Framework certification does not authorize deployment into an external environment.

## Test and verification strategy

- Exercise runtime, policy, schema, registry, loader, builder, memory, model, retrieval, governance, and orchestration behavior.
- Test new-project and existing-project commissioning, owner preservation, project isolation, tamper detection, checkpoint consistency, and recovery.
- Directly execute admitted exact tools with positive and fail-closed cases.
- Detect unreachable artifacts, stale maps, duplicate or dead surfaces, version drift, corrupted text, unfinished markers, import cycles, and documentation/implementation mismatch.
- Build and inspect clean wheel and source distributions, then repeat required behavior from an isolated installed environment.
- Require a zero-finding sanitation and release-artifact audit.

## Rollback and custody

Never hard-delete owned, unknown, superseded, generated, cache, or temporary material. Inventory and hash exact candidates, move them to recoverable custody outside the deployable project, verify the move, and retain a restoration receipt. Existing project owner files remain byte-preserved unless a separately approved change names them.

## Acceptance

- All discovered source tests pass with a nonzero denominator.
- Registry, contract, graph, integration, structural, dependency, generated-artifact, and project checks pass.
- Metadata-only startup hydrates zero skill bodies; bounded selection never exceeds three; explicit hydration loads only the selected body.
- Both commissioning modes work from the installed wheel without overwriting existing owners.
- Exact-tool, Python-surface, package-content, licensing, portability, and sanitation denominators are closed.
- No unclassified, quarantined, archived, temporary, cache, bytecode, backup, or embedded archive payload ships as product input.
- The final live product digest matches the sealed deployment certificate.
