# Project Management

This is the sole durable control point for building and releasing the Engineering Loop Bootstrap. Machine-readable state is in `.engineering-bootstrap/project-management/state.json`. Closed historical plans are recoverably externalized and indexed by `evidence/externalized-payload-index.json`; they are not product inputs.

## Objective

Deliver a model-agnostic, drop-in bootstrap that lets an LLM safely commission either a new project or an existing repository, preserve existing owners, manage work through durable project artifacts, select skills from metadata, hydrate only required bodies, execute bounded orchestrations, and verify outcomes with recoverable cleanup.

## Current state

Mode: `existing`  
Phase: `deployment certified`
Status: `complete`
Active card: `none`
Next action: monitor release 0.6.3 and open a new card before any material change.

Release 0.6.3 is the current signed, self-certified release. The annotated tag, exact public distribution files, trusted publisher signature, complete evidence set, checksums, SBOM, provenance, and fresh installed-wheel verification agree. Canonical evidence is under `evidence/releases/0.6.3/`; the public release is at [GitHub v0.6.3](https://github.com/Mountain-Nomad-BC/Pacify-X/releases/tag/v0.6.3).

Release 0.6.2 is historical and revoked for deployment. Its validation proved internal consistency under the included profile, but did not authenticate one immutable chain from Git commit through the exact tested and publicly distributed package bytes. Revocation evidence is retained at `evidence/release-revocation-0.6.2.json`; the original certificate remains unchanged as historical evidence.

Release 0.6.1 is historical and revoked for deployment. The live source suite reproduced a contract mismatch on 2026-08-03: `registry/declared_suite_formulas.json` emits `count`, while its authoritative consumer requires `formula_count`. Revocation evidence is retained at `evidence/release-revocation-0.6.1.json`; certification may be restored only by the atomic REL-010 finalizer against one unchanged product digest.

The earlier 0.2.0 certification is superseded for deployment purposes. A follow-up audit found an invalid JSON Schema, incomplete runtime binding for the contract corpus, and a working-set path that selected only the six core capability records rather than all admitted skills.

## Superseded release card - REL-001

- [x] Create the missing project-management dashboard and machine-readable state.
- [x] Generate the seven durable management controls and three compact commissioning outputs.
- [x] Add separate copy/paste prompts for new and existing projects.
- [x] Preserve existing owner files while applying namespaced controls.
- [x] Store existing-project inventory, adoption plan, project identity, and commissioning receipt.
- [x] Prove metadata-only startup and explicit one-skill hydration.
- [x] Complete a clean installed-wheel commissioning test for both modes.
- [x] Pass the final full suite and registry validation after all evidence hashes are refreshed.
- [x] Rebuild and inspect the final wheel, quarantine generated intermediates, and publish certification evidence.
- [x] Pass the final active-tree sanitization and archive audit.

Historical evidence is externalized; this certification is not deploy-authoritative.

## Corrective release card - REL-002

- [x] Identify the disconnected multi-project and memory surfaces.
- [x] Implement the concrete project drop root and central project registry.
- [x] Implement isolated tracking, bindings, leases, switching, and memory roots.
- [x] Expose workspace, project, memory, and workflow operations through the CLI.
- [x] Complete adversarial isolation, installed-wheel, package, and sanitation certification.

Historical evidence is externalized; this certification is not deploy-authoritative.

## Structural recertification card - REL-003

- [x] Parse, meta-validate, identify, version, own, package, and classify every shipped contract.
- [x] Route the bounded working set across every admitted skill while preserving metadata-only startup.
- [x] Replace raw source-note/reference trees with executable controls and compact provenance/coverage receipts.
- [x] Consolidate archive and external-intake maps; move superseded/raw material to parent `temp/quarantine` only.
- [x] Give integrations and graph projections one validated canonical home; remove false duplicate directory homes.
- [x] Rebuild the wheel and rerun source, installed-wheel, isolation, sanitation, and package-content certification.

Release evidence: `evidence/release-certification-0.3.0.json`.

## Capability assimilation card - REL-004

- [x] Reopen certification after evidence showed that source assimilation was incomplete.
- [x] Run separate broad, control-plane, staged-tooling, simulation-skill, and engineering-skill scans with explicit denominators and exclusions.
- [x] Convert admitted mechanisms into sanitized, lazy-loaded skill bodies and deterministic helper tools.
- [x] Reframe cached-address handling as Dynamic Service Discovery; keep proxy-specific configuration as one implementation.
- [x] Add explicit source dispositions, skill orchestration maps, runtime validation, schema ownership, and coverage evidence.
- [x] Merge cross-cutting completeness, replay, contract, secret-safety, and release-binding rules into existing core skills.
- [x] Pass focused tests, full source tests, registry validation, sanitization, installed-wheel certification, and package reconciliation.
- [x] Move completed raw audit inputs and reports to recoverable parent quarantine with restoration receipts.
- [x] Issue the 0.4.0 release certificate and close this card only when every required denominator is complete.

Release evidence: `evidence/release-certification-0.4.0.json`.

## Temporary-corpus completeness card - REL-005

- [x] Reopen certification before changing the source auditor or capability controls.
- [x] Open a mutation-tracked intake and capture the first complete 16,743-file snapshot.
- [x] Fix text-format, oversized-stream, excluded-boundary, and whole-inventory accounting gaps in the source auditor.
- [x] Reconcile every local inventory record, skill identity, incomplete marker, historical disposition, and external metadata class.
- [x] Implement and wire every newly admitted reusable mechanism; explicitly merge, reject, defer, or retain all others as external evidence.
- [x] Rerun the complete source audit and capture two matching full-tree snapshots immediately before intake closure.
- [x] Pass focused, full-source, registry, contract, package, installed-wheel, and sanitization gates.
- [x] Externalize the completed current intake to recoverable parent quarantine with hash-reconciled restoration evidence.

Current-corpus evidence: `evidence/source-corpus-completeness.json`.

## Final review and deployment certification card - REL-006

- [x] Open the user-held final-review corpus only when the user supplies its instructions.
- [x] Reconcile and implement any newly admitted mechanisms without weakening current contracts.
- [x] Rerun all final source, registry, contract, package, installed-wheel, isolation, and sanitation gates.
- [x] Issue the superseding deployment certificate only if every denominator is complete and every gate passes.

Release evidence: `evidence/release-certification-0.5.0.json`. This certificate is revoked: canonical-owner routing was not sufficient proof that absent-body outcomes were implemented and independently tested.

## Declared-suite reconstruction card - REL-007

- [x] Revoke the premature 0.5.0 deployment certificate and reopen project management.
- [x] Assign every genuinely absent declared artifact to exactly one reconstruction card or exact-recovery record.
- [x] Infer the advertised behavior from identifiers, pack domain, neighboring contracts, and current owners without claiming unavailable historical internals.
- [x] Classify each outcome as already-proven, partial, missing, consolidated replacement, or rejected noncapability using executable evidence.
- [x] Build every missing or partial contract, implementation surface, orchestration binding, registry entry, and recovery path.
- [x] Add positive, negative, failure-policy, rollback, and evidence assertions for every reconstructed outcome.
- [x] Validate each card independently, add it to canonical maps only after validation, and reduce the open denominator to zero.
- [x] Rerun source, official skill, registry, contract, package, installed-wheel, isolation, sanitation, and release gates; deployment certification remains intentionally revoked while REL-008 is open.

## Last-round authoritative assimilation card - REL-008

- [x] Open a mutation-tracked intake and inventory all 2,055 files and 4,481,519 bytes without exclusions or read errors.
- [x] Prove that all 1,233 previously absent declared artifacts have exact size-and-hash matches in the supplied authoritative suite.
- [x] Validate all eight authoritative packs and the metacognitive pack in isolated validation copies.
- [x] Give every source file and every declared capability an explicit disposition, canonical owner, target surface, and verification evidence.
- [x] Replace inferred declared-suite details with stronger authoritative contracts and behavior where compatible; retain consolidation and safety boundaries.
- [x] Integrate the metacognitive layer as bounded extensions over existing evidence, graph, memory, routing, improvement, and certification owners.
- [x] Implement sanitized operational tooling, formulas, schemas, policies, orchestration bindings, lazy skill metadata, and CLI access for admitted metacognitive behavior.
- [x] Run semantic-effect, privacy, negative, rollback, full-source, registry, contract, graph, installed-wheel, isolation, package, and sanitation tests.
- [x] Capture two matching source snapshots and an immediate pre-move equality check, then quarantine the closed intake with a restoration receipt.
- [x] Issue a new deployment certificate only after REL-008 reaches a zero-open denominator and every final gate passes.


Release evidence: `evidence/release-certification-0.6.0.json`. This certificate is revoked because its saved full-suite result predates final disposition mutation and the live post-finalization tree fails its own release test.

## Project-wide behavioral recertification card - REL-009

- [x] Repair final disposition states and ensure generated cache classifications precede test/evidence classifications.
- [x] Execute every admitted exact Python tool from its shipped file with isolated positive and fail-closed cases.
- [x] Map every Python source file to its deployment class, owner, and validation evidence.
- [x] Require tool certification, Python-surface certification, and a clean product tree in the installed-wheel gate.
- [x] Run the entire source suite after every release mutation; never certify from a pre-mutation log.
- [x] Rerun registry, contracts, graphs, integrations, orchestration, isolation, memory, package, sanitation, and wheel gates.
- [x] Issue a superseding certificate only after the final live tree passes with zero unresolved denominators.

Release evidence: `evidence/release-certification-0.6.1.json`.

This certificate is revoked for deployment by `evidence/release-revocation-0.6.1.json` after the live formula-registry contract test failed.

## Corrective atomic-recertification card - REL-010

- [x] Record the pre-change 1,285-file tree manifest and digest outside the deployable product.
- [x] Reproduce the declared formula registry failure through pytest.
- [x] Reopen human and machine project state before implementation changes.
- [x] Revoke release 0.6.1 without destroying its historical evidence.
- [x] Establish and validate the complete corrective-release coverage ledger.
- [x] Repair registry-envelope ownership and prevent count drift across registries.
- [x] Implement one atomic digest-bound release finalizer and independent certificate verification.
- [x] Add bounded test profiles, tool receipts/timeouts, reproducible release dependencies, and clean-artifact certification.
- [x] Harden formula execution, generated projections, runtime profiles, incomplete-marker review, and executable-effect ownership.
- [x] Run the complete final-tree source, exact-tool, registry, contract, graph, integration, sanitation, package, and installed-wheel gates.
- [x] Publish a new deployment certificate and close this card only through the authoritative finalizer.

Release evidence: `evidence/release-certification-0.6.2.json`.

## Authenticated exact-artifact full-repair card - REL-011

- [x] Revoke 0.6.2 without deleting or rewriting its historical evidence.
- [x] Implement and validate all 42 full-repair cards with required receipts.
- [x] Build the wheel and source archive once from the clean annotated `v0.6.3` tag.
- [x] Run the full certification profile against those exact distribution bytes.
- [x] Sign the canonical certificate with the repository-trusted publisher identity.
- [x] Publish the exact bytes and immutable supporting evidence as a public GitHub Release.
- [x] Download every public release asset separately, verify all bindings and hashes, and install the public wheel in a fresh environment.

Release evidence: `evidence/releases/0.6.3/certificate.json`, `evidence/releases/0.6.3/certificate.json.sig`, and `evidence/releases/0.6.3/public-release-verification.json`. The complete run bundle is retained outside the deployable repository and identified by the public verification receipt.

## Primary user entry points

- New project: `bootstrap/prompts/NEW_PROJECT_PROMPT.md`
- Existing project: `bootstrap/prompts/EXISTING_PROJECT_PROMPT.md`
- Installation and commands: `README.md`
- Project blueprint: `PROJECT_BLUEPRINT.md`
- Architecture/governance/risk: `ARCHITECTURE_GOVERNANCE_AND_RISK.md`
- Execution/punch cards/acceptance: `EXECUTION_PLAN_PUNCH_CARDS_AND_ACCEPTANCE.md`

## Management controls

- `.engineering-bootstrap/project-management/PROJECT_CONTEXT.md`
- `.engineering-bootstrap/project-management/ASSUMPTIONS.md`
- `.engineering-bootstrap/project-management/EXECUTION_PLAN.md`
- `.engineering-bootstrap/project-management/PUNCH_CARDS.md`
- `.engineering-bootstrap/project-management/ORCHESTRATION.md`
- `.engineering-bootstrap/project-management/RISKS.md`
- `.engineering-bootstrap/project-management/ACCEPTANCE_CRITERIA.md`

## Completion rule

Do not mark the release complete from source tests alone. Require the installed-wheel two-mode test, project integrity validation, registry validation, package-content reconciliation, zero-hit active-tree sanitization audit, recoverable quarantine receipts, and an updated release certification record.
