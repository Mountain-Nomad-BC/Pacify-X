---
name: deep-module-design
description: Design deep modules with small stable interfaces, strong locality, and explicit seams.
---

# Deep Module Design

A module earns its existence when it hides meaningful complexity behind a small interface.

## Analysis
- Enumerate everything callers must know: methods, invariants, ordering, failure modes, configuration, and performance constraints.
- Measure interface burden against behavior hidden, callers served, and change locality.
- Apply the deletion test: if deleting the module merely spreads its logic across callers, it is deep; if little complexity reappears, it was likely pass-through ceremony.
- Require actual variation before creating an adapter seam. One implementation is evidence of a possible seam, not proof.

## Design rules
- Accept dependencies; do not secretly construct them.
- Return decisions/results; isolate side effects behind explicit ports.
- Tests and callers should cross the same public seam.
- Prefer replacement of a bad boundary over layering another wrapper around it.
- Hide implementation directories from cross-package imports when the language permits it.
