---
name: audit-source-capabilities
description: Inventory a large source or reference tree without mutation, identify reusable engineering mechanisms across skills, code, configuration, and process documents, reconcile candidates against an existing skill catalog, and produce deterministic coverage and disposition evidence. Use for source mining, migration intake, capability-gap audits, or any task where sampling could miss valuable operational behavior.
---

# Audit Source Capabilities

Run the bundled scanner before manually selecting interesting files:

```powershell
python scripts/audit_source_capabilities.py --root <SOURCE> --output <RAW_REPORT> --existing-catalog <SKILL_CATALOG>
```

When a prior inventory and migration dispositions exist, reconcile every record
against historical evidence, current owners, and narrow supersession rules:

```powershell
python scripts/reconcile_source_inventory.py --inventory <INVENTORY.jsonl> --current-root <PRODUCT> --disposition <MAP.json> --rules <RULES.json> --output <REPORT.json> --require-complete
```

For a large external skill corpus, reconcile every `SKILL.md` identity without
hydrating all bodies:

```powershell
python scripts/reconcile_skill_identities.py --inventory <INVENTORY.jsonl> --structured-text <STRUCTURE.jsonl> --catalog <CATALOG.toml> --specialty-admission <SPECIALTIES.json> --aliases <ALIASES.json> --output <REPORT.json> --require-complete
```

Finally, reconcile every classified asset and every retained inventory error:

```powershell
python scripts/reconcile_classified_assets.py --inventory <INVENTORY.jsonl> --classified <CLASSES.jsonl> --policy <DISPOSITIONS.json> --skill-report <SKILLS.json> --direct-audit <AUDIT.json> --error-log <ERRORS.jsonl> --output <REPORT.json> --require-complete
```

Reconcile every scanner record to its admitted capability owners with
`scripts/reconcile_mechanism_records.py`; an unknown mechanism keeps the intake open.

When staged material declares capabilities through mixed physical bodies and
manifest-only records, run `scripts/reconcile_staged_capabilities.py`. Its policy
must resolve every typed `(kind, id)` exactly once. A manifest-only declaration
may be retained as a reference lead, deferred, or rejected, but it cannot count as
implementation or validation evidence.

When source punch cards exist, run `scripts/validate_planning_card_coverage.py`
so every card has a current owner and executable acceptance test.

When a staged suite declares absent bodies, run
`scripts/build_declared_suite_reconstruction.py` to turn every absent operational
outcome and supporting artifact into a fail-closed reconstruction card. A route to
an existing owner is only assignment. Do not close a card until the behavior,
implementation, orchestration wiring, recovery policy, and executable acceptance
evidence all exist in the current product.

Keep the raw report outside the deployable product when source paths or content are private. Retain only a sanitized receipt, explicit candidate dispositions, and the raw report hash in the product.

## Workflow

1. Inventory and hash every regular file. Record generated/cache exclusions, oversized files, symlinks, and read failures separately with explicit file and byte denominators.
2. Extract skill metadata and scan code, configuration, and documentation for concrete mechanisms—not keyword frequency alone.
3. Compare candidates with the current catalog. Treat exact matches and strong overlaps as merge candidates, not new skills.
4. Inspect the strongest source artifacts and require a concrete trigger, reusable procedure, safety boundary, and verification method.
5. Reconcile every source record and give every reviewed candidate one disposition: `implement`, `merge`, `defer`, `reject`, or `external_evidence_only`.
6. Implement clean-room, product-neutral skills. Never copy credentials, private identifiers, environment paths, or destructive commands.
7. Validate the skill package, mapping, orchestration, tests, package contents, and sanitization before marking the candidate complete.

## Completeness rules

- Do not equate a passing framework audit with complete source assimilation.
- Do not silently skip unreadable or oversized files.
- Stream-scan oversized text and line-oriented catalogs; a size threshold may limit in-memory parsing but may not remove a file from capability discovery.
- Treat JSON Lines, CSV, Markdown variants, and configuration formats as operational text unless evidence shows they are binary.
- Do not promote a prose-only claim without inspecting its implementation or evidence.
- Keep vendor skill collections visible in coverage totals but do not bulk-admit them.
- A candidate without an explicit disposition remains open work.
- Detect manifest-to-filesystem disagreement before admission. Preserve the
  denominator, validate every present hash, and never infer absent bodies from a
  suite manifest.
- A missing historical path is not proof of cleanup: require a current owner or a narrow, validated supersession rule.
- A current owner is not proof of behavioral coverage. Require direct tests for
  every reconstructed outcome and exact one-card coverage for every absent path.
