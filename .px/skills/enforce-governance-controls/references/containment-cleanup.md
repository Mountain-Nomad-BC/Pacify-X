# Admission, containment, trace, and cleanup controls

- Inventory staged packs without extraction or execution; record provenance, license, effects, and archive hazards.
- Run containment preflight before tools/services: trusted root, resource budget, network, secrets, rollback.
- Sanitize traces recursively with allowlisted fields; retain hashes and failure visibility.
- Select cleanup targets from deterministic manifests beneath explicit roots; preview before approval.
- Negative tests: traversal archive, unknown effect, secret in nested trace, ambiguous cleanup target, active owner.

Lineage: clean-room generalization of reviewed admission and containment patterns.
