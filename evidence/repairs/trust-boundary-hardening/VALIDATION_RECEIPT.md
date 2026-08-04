# Validation receipt

Status: local integrated validation passed; merge and public CI pending.

## Source tests

- Baseline focused suite: 33 passed.
- Shared trust and contract integration: 56 passed and 178 contract subtests.
- Lazy loading, custody, platform, public surface, and dependency checks: 22 passed.
- Broader integrated focused suite: 90 passed and 187 subtests in 200.97 seconds.
- Post-format focused regression: 40 passed in 14.73 seconds.
- Full source invocation: 632 passed, 2 failed, and 465 subtests passed in 1139.63 seconds.
- The two failures were an installed-wheel doctor source-path assumption and release-audit cache hygiene. The doctor now resolves installed declared resources; all disposable caches were recoverably quarantined outside the repository.
- Failed-only reruns then passed: installed-wheel E2E passed and all 4 release-audit tests passed in 105.77 seconds.
- Aggregate result after bounded failed-only reruns: all 634 tests passed and 465 subtests passed. This is deliberately reported as an aggregate, not misrepresented as one uninterrupted clean run.
- An attempted `PYTHONNOUSERSITE=1` invocation found no pytest because pytest is installed in the user site; it executed no tests and is not counted.

## Independent assurance gates

- Registered gates: contracts, dependencies, platform, generated projections, registry, licensing, and structural integrity.
- Each receipt is sealed to its declared file hashes and dependency receipt hashes outside the deployable tree.
- The initial run executed and passed all seven gates.
- An immediate unchanged run reused all seven receipts.
- Later source changes reused unaffected passing receipts and reran only stale dependents.
- Finalization executes no tests and accepted 7 of 7 current, untampered passing receipts.
- Gate receipts are retained in the parent workspace's temporary evidence custody, outside the deployable tree.

## Generated and structural projections

- Contracts: 86 of 86 owned and valid.
- Python surfaces: 375 of 375 syntax-valid; 328 packaged; 63 direct-behavior; 54 evidence-associated; 40 source-only structural.
- Python dependency owners: 61 modules.
- Effect surfaces: 442 records.
- Artifact reachability: 329 records.
- Semantic capability index: 89 records.
- Commissioned skill registry: 60 skills with no changed or stale records.
- Registry envelope: 47 records.
- Generated-artifact validator: all 12 source projections current.
- Structural audit: all 21 mature-framework checks passed across 15 categories.

## Build and installed artifact

- The clean source copy and build were created in parent-workspace temporary custody, outside the repository.
- Wheel install used a fresh virtual environment and `pip install --no-deps`.
- Installed `engineering-bootstrap --version`: 0.6.3.
- Installed `doctor`: valid on Python 3.14.5 with the declared `>=3.11,<3.15` policy.
- Installed `validate`: valid with all 6 active capabilities.
- The installed CLI exposed the independent gate commands.
- Final wheel SHA-256: `ea2ce5d34f936a7523dc01faed2df1435271409b3879470f219b7f2f0f398dce`.
- Final source archive SHA-256: `b86b63f77486813040b33239dfbeecdbca92195d3e6f480e4cfe8d589999dfd3`.
- Wheel contained all new runtime modules and all 86 contracts; it contained no embedded ZIP.

After the first target-branch checkout, the generated gate detected that the semantic capability index generator had written platform-translated line endings before Git normalized the file. The generator now writes explicit LF bytes, dependent projections were regenerated, and a fresh checkout-state run finalized all seven gates. The hashes above are from the post-repair build.

## Hygiene and sanitation

- Cache cleanup used recoverable quarantine only; no hard delete occurred.
- Final active-tree sanitation: valid across 1,459 files and 16,377,817 bytes, with zero prohibited-identifier hits, legacy placeholders, active ZIPs, or scan errors.
- Final cache dry run: zero cache directories, bytecode files, or inventoried cache files.
- Historical release and revocation evidence remains unchanged.

## Remaining limitation

The current v0.6.3 tag and certificate were not moved or rewritten. Durable complete-evidence assets and these hardening bytes will become release-authoritative only through a future authorized, signed release workflow.
