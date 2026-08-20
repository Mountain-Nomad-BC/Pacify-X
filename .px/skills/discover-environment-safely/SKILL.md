---
name: discover-environment-safely
description: "Inventory project-local tools, runtimes, IDE support, dependencies, and setup gaps without installing or changing anything. Use for bounded environment discovery, tool recommendations, unfinished-marker/stub census, and credential-storage guidance."
---

# Safe environment discovery

## Workflow

1. Define the explicit project root and observation budget.
2. Use existing bounded probes and user-supplied observations; do not install, connect, or mutate.
3. Record tool availability, versions, project/global scope, IDE recommendations, and unfinished-marker/stub findings.
4. Separate observations from recommendations and list every recommendation requiring approval.
5. Use an OS credential manager or ephemeral environment injection for credentials. A one-way hash cannot authenticate and must never be proposed as credential storage.
6. Return the structured result from `runtime.assurance_controls.run_assurance_control`.

## Completion

Complete only with a reproducible inventory, explicit missing-tool list, zero executed changes, and approval requirements for every mutating recommendation. Missing probes remain unknown rather than assumed absent.
