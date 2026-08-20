# Security domain operations

Load only the selected domain section and its chosen provider records.

- **AI agents and MCP:** inspect prompt/data separation, tool-description poisoning, shadowing/rug pulls, toxic flows, memory contamination, confused-deputy paths, egress, secrets, delegation, and supply-chain integrity. Use read-only fixtures by default.
- **Application, API, and web:** map trust boundaries, authentication, object/function authorization, input handling, sessions, business logic, APIs, dependencies, abuse cases, and regression oracles.
- **Cloud, containers, and Kubernetes:** assess identities, effective permissions, exposure, data controls, logging, images, admission, workload/runtime policy, network policy, and control-plane configuration.
- **Cryptography and PQC:** inventory algorithms, protocols, certificates, keys, signing, hardware roots, lifecycle/rotation, crypto agility, exposure, ownership, and migration sequencing.
- **DevSecOps and supply chain:** cover source/dependency provenance, SBOM, secret scanning, SAST, dependency/IaC/image analysis, signing, CI identities, build isolation, attestations, release gates, and reproducibility.
- **Identity and zero trust:** validate identity lifecycle, authentication strength, effective access, privileged access, device/workload trust, segmentation, revocation, and continuous verification.
- **Incident response and forensics:** preserve custody while moving through preparation, triage, containment, acquisition, analysis, eradication, recovery validation, and lessons learned. Emergency authority is bounded and retrospectively reviewed.
- **Network traffic and segmentation:** review architecture, exposures, firewall intent/effective state, segmentation, telemetry coverage, encrypted traffic handling, anomalous communication, and change verification. Default to passive/read-only.
- **OT/ICS:** prioritize process safety, availability, passive collection, vendor constraints, maintenance windows, fail-safe behavior, and recovery. Security policy cannot override physical safety.
- **Privacy, compliance, and controls:** map data, risks, control objectives, implementation evidence, gaps, owner, due date, residual risk, and verification. A framework mapping is not implementation proof.
- **Threat hunting and detection:** state falsifiable hypotheses, identify telemetry, run read-only searches, map behavior, test detections, measure false positives/negatives, tune, and preserve hunt evidence.
- **Vulnerability lifecycle:** normalize and verify observations, prioritize exploitability/exposure/asset criticality/controls, assign ownership, remediate, and independently verify closure.
- **Purple-team validation:** use isolated-lab or explicitly approved non-production scope, bounded techniques, expected telemetry, stop conditions, kill switch, cleanup, and detection objectives. Deny unauthorized or production-active requests.
- **Reporting and remediation:** maintain observation -> candidate finding -> verified/false-positive -> accepted risk/remediation -> verification state, with evidence hashes and residual risk.

Framework mappings (ATT&CK, D3FEND, ATLAS, NIST CSF, NIST AI RMF, and F3) support discovery and explanation. They do not prove relevance, control implementation, or authorization.
