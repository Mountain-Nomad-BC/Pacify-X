# MS+Enterprise second-pass punch card

This pass began with a complete metadata-first audit of the Microsoft + Enterprise master and the current `zips 2` archive set. Nothing from an archive was installed or executed.

## Audit denominator

| Source | Accounted | Result |
|---|---:|---|
| Enterprise master | 23/23 files; 133,266 bytes | 23 text files scanned, 19 capability candidates, zero errors |
| Current archive set | 33/33 archives; 1,409,505,663 bytes | 112,905 central-directory entries, zero unreadable archives, licenses detected for all 33 |
| Handoff hash comparison | 31 exact archive matches | Two former Agent Academy archives are replaced by one newer MIT archive; Team Fabric v0.2.0 is the additional current input |
| High-value path map | 128 planned checks | 122 direct matches; six wildcard-reporting misses were manually verified present in Agent Skills and Power Platform |

Raw receipts are retained in `evidence/ms-enterprise-master-source-audit.raw.json`, `evidence/ms-enterprise-zips2-source-audit.raw.json`, and `evidence/ms-enterprise-archive-central-audit.json`.

## Additional mechanisms recovered in the second pass

| Card | First-pass gap | Second-pass treatment | Status |
|---:|---|---|---|
| E01 | Power Platform plan omitted Power Automate and mobile/offline app operations | Added explicit Power Automate, mobile apps, offline profiles, environment routing, ALM, DLP, and mutation-gate coverage | Implemented in enterprise catalog |
| E02 | Agent compatibility did not make per-user hosted session isolation explicit | Added user/tenant/session/thread/chat-history separation skill and independent auditor | Implemented |
| E03 | Human/tool approval was implicit | Added explicit user-approval, filtering middleware, tool authority, and prompt-injection boundary | Implemented |
| E04 | Structured output and chat-history consistency were underrepresented | Added these to Agent Fabric readiness and session isolation checks | Implemented |
| E05 | Hosted identity context could be confused with provider identity | Split hosted identity, authentication namespace, billing namespace, target aliases, and canonical memory | Implemented in schema and state manager |
| E06 | Agent behavior maturity and versioning were missing | Added maturity/versioning skill and staged-release orchestration | Implemented as offline knowledge/control metadata |
| E07 | Request-based versus message-driven communication was not a first-class decision | Added message-mode selection skill | Implemented as offline knowledge metadata |
| E08 | Enterprise FinOps was only a general cost note | Added a cost guard with explicit billing namespace, budget ceiling, rate controls, and no implicit paid fallback | Implemented |
| E09 | Cloud connector state could have leaked into local state | Created `px.ms-enterprise.state/1.0` under `.engineering-bootstrap/enterprise` with a distinct event/evidence ledger | Implemented and tested |
| E10 | UI exposure was described as filters only | Added MS+Enterprise tabs to Skills, Agents, and Workflows plus controls in Diagnostics, Assurance, Runtime, and Control Center | Implemented and tested |
| E11 | Cross-IDE access was missing | Added four enterprise MCP controls, guardrail evaluation, environment discovery tools, and enterprise catalog kinds | Implemented; expanded to 31 total MCP tools in 0.4.1 |
| E12 | Cost controls were descriptive rather than operator-configurable | Added a default-off master plus per-task/session/day cost, token, routing, provider, hardware, confidence, reuse, and approval gates | Implemented and tested |
| E12 | Pack toggles could be mistaken for service enablement | Pack controls change offline metadata only; host confirmation states what remains denied | Implemented and tested |

## Enterprise data model

The canonical enterprise catalog contains 18 packs, 20 skills, 12 agents, 8 workflows, 10 connectors, and 2 provider records. Every identity is prefixed `ms-enterprise/`. Enterprise project state, events, targets, and receipts are separate from coordination state and from session/project/state/system memory.

## Intentionally unavailable

Azure, Foundry, Power Platform, M365, Teams, Dynamics, Business Central, and other network connectors are disabled. DevSkim, ONNX Runtime GenAI, DAP, and TUI adapters are marked not installed. No tenant mutation, cloud deployment, credential provisioning, API key, subscription, or billable fallback was configured. Their catalog entries and readiness gates are operational; their external service adapters require a future explicit installation and authorization round.
