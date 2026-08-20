---
name: orchestrate-security-validation
description: Plan and run dependency-aware security validation across secret, source, infrastructure, supply-chain, dynamic, accessibility, fuzz, and load scanners, then aggregate payload-minimized findings. Use when a security campaign involves multiple tools, prerequisites, execution barriers, partial scanner failures, or a unified evidence report.
---

# Orchestrate Security Validation

1. Discover installed tools and versions without installing or upgrading anything.
2. Freeze the target, authorization boundary, network allowance, budgets, and output directory.
3. Run independent static checks in parallel only when resource budgets allow.
4. Generate an SBOM before any scanner that consumes it.
5. Serialize network-active scanners to protect the target and preserve attribution.
6. Record a failed or missing scanner as `failed` or `blocked`; never replace it with a pass.
7. Run `scripts/aggregate_security_findings.py` on normalized JSON envelopes.
8. Report pass, fail, blocked, skipped, and uncertain counts with both eligible and total denominators.

Require explicit approval before installing tools, contacting external services, fuzzing, load testing, or changing the target. Keep raw payloads and possible secrets out of model context and summary reports.
