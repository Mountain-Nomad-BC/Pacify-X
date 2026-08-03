# Contributing to PACIFY-X

PACIFY-X is the project and framework. `engineering-bootstrap` is its Python package and command-line control plane.

## Before changing code

1. Read `START_HERE_FOR_AI.md`, `PROJECT_MANAGEMENT.md`, and the controlling contracts/policies.
2. Classify the change's effects and identify its authoritative owner, generated projections, and evidence obligations.
3. Preserve unknown or superseded material through inventory and quarantine; do not hard-delete it.
4. Preview project/workspace mutations before applying them.

## Change requirements

- Keep startup metadata-only and capability hydration bounded.
- Do not weaken path containment, project isolation, effect grants, signature checks, or fail-closed behavior.
- Add negative and denial-path tests for every new boundary.
- Regenerate owned maps with their declared builder; do not hand-edit generated outputs.
- Record new runtime, contract, workflow, policy, registry, and package surfaces in their ownership maps.
- Treat documentation claims as testable contracts. Use “self-certified against the included validation profile” unless an independent certifier is named and evidenced.

Run at least:

```text
python -m runtime.cli --root . audit structure
python -m runtime.cli --root . audit licensing
python -m runtime.cli --root . test-profile run fast
```

Release-affecting changes also require the full profile, executed branch coverage, exact-tool negative certification, artifact-manifest comparison, installed-wheel exercise, sanitation/security gates, and clean-clone release procedure documented in `docs/release-process.md`.

## Pull requests

Describe the requirement, effect boundary, authoritative files, generated projections, tests, fault/denial cases, compatibility impact, and rollback/quarantine path. A green test alone is insufficient when the assertion does not exercise the claimed behavior.
