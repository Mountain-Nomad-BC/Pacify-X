---
name: audit-incomplete-implementations
description: Find and classify unfinished-task markers, stubs, placeholder returns, unimplemented branches, mocks, fabricated fallbacks, and silent degradation using syntax-aware and text-aware scans with deterministic evidence. Use for completeness audits, production-readiness reviews, inherited repositories, or verifying that unfinished behavior is not hidden behind passing tests.
---

# Audit Incomplete Implementations

1. Inventory source boundaries, languages, generated/vendor exclusions, and maximum file sizes.
2. Use syntax-aware detection where available and bounded text patterns elsewhere.
3. Assign a deterministic finding ID from path, line, rule, and source hash; avoid storing sensitive source text.
4. Classify each finding as test fixture, documentation, explicit safe degradation, unreachable dead code, deferred feature, or unsafe runtime incompleteness.
5. Require a project-owned review registry for intentional fallbacks; never embed product-specific allowlists in the scanner.
6. Fail closed on unclassified high-risk runtime candidates, fabricated success, authorization bypass, or data-loss fallback.
7. Reconcile findings against scope and report reviewed/unreviewed denominators.
8. Preserve open findings in project management until implementation or explicit rejection is evidenced.

Use `scripts/audit_incomplete.py` for a deterministic first pass. Pass a project-owned `--review-registry` for intentional findings. Unreviewed or stale findings make `complete` false; the tool does not certify reachability or intent by itself.

For historical or external reports, use `scripts/reconcile_incomplete_findings.py` with a project-owned boundary policy. Keep those dispositions separate from the active-source review registry.
