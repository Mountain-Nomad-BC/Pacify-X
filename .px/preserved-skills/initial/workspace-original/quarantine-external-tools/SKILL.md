---
name: quarantine-external-tools
description: "Quarantine and assess packages, extensions, MCPs, binaries, containers, dependencies, and third-party integrations before execution. Use when proposing installation, connection, upgrade, or adoption of external tooling."
---

# External tool quarantine

## Workflow

1. Keep the component non-executable and non-integrated while intake is incomplete.
2. Record source, immutable hash, license, dependency tree, requested permissions, vulnerability findings, malicious indicators, compatibility, and policy decision.
3. Apply `contracts/external-tool-intake.schema.json` and `policies/external-tool-quarantine.json`.
4. Treat dynamic analysis as a separate approved phase requiring isolation, synthetic secrets, and a declared network policy.
5. Require explicit approval after static and any approved dynamic evidence passes.

## Completion

Use `runtime.assurance_controls.run_assurance_control`. Only `admit` permits later integration; every incomplete, vulnerable, malicious, incompatible, or unapproved component remains quarantined and blocked.
