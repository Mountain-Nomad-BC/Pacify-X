# Admission contract

## Dispositions

- `adopt`: use an independently safe candidate with minimal change.
- `merge`: combine compatible patterns into a canonical implementation.
- `pattern_only`: retain design knowledge without importing executable code.
- `reference_only`: keep source inert for research.
- `defer`: postpone until prerequisites or evidence exist.
- `reject`: exclude unsafe or unsuitable behavior.
- `duplicate`: point to the canonical owner instead of adding another implementation.

## Minimum promotion evidence

Require a unique ID, owner, version, I/O contract, effects, dependencies, provenance, license review, focused tests, failure-path tests, and approval. High-risk effects additionally require a governed adapter, sandbox validation, runtime approval, and evidence collection.

## Atomic promotion

Keep a candidate out of the active map until the contract, implementation, focused evidence, and ledger record agree on ID, version, status, and effects.
