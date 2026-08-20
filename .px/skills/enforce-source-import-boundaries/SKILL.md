---
name: enforce-source-import-boundaries
description: Detect and reject imports that escape package roots, reach internal implementation paths, cross declared service/container ownership, or consume mirrored contracts without parity proof. Use for monorepos, shared packages, generated clients, service extraction, or architecture-boundary certification.
---

# Enforce Source Import Boundaries

1. Define canonical package/service roots, public entry points, allowed dependencies, and mirrored contract pairs.
2. Scan supported source files without following symlinks or entering generated/vendor roots.
3. Normalize each relative or aliased import to its resolved owner.
4. Reject package-relative escapes, private deep imports, undeclared cross-service imports, and cycles forbidden by policy.
5. Hash mirrored contracts and fail when parity cannot be proven.
6. Report exact source location, resolved owner, violated rule, and suggested public boundary.
7. Distinguish type-only, test-only, generated, and runtime imports without silently exempting them.
8. Re-run after generators/builds so derived imports cannot reintroduce drift.

Use `scripts/audit_import_boundaries.py` with a project-owned JSON policy. The script is read-only and does not rewrite imports.
