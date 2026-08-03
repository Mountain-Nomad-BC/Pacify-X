# New Project Commissioning Pack

## What this is

This pack turns a plain-language idea into an evidence-based project blueprint before an AI coding agent starts changing files.

It is designed for people who may know exactly what they want the product to do without knowing which language, framework, database, security model, deployment method, AI capability, or governance process should be used.

The pack supports two paths:

1. **Human-completed intake** — fill out the questionnaire directly.
2. **Guided commissioning conversation** — paste the questionnaire and facilitator prompt into a capable AI assistant and answer its follow-up questions.

## Start here

### Fast path

1. Open `00_FULL_COMMISSIONING_QUESTIONNAIRE.md`.
2. Answer what you can in plain language.
3. Paste your answers with `05_AI_COMMISSIONING_FACILITATOR_PROMPT.md` into an AI assistant.
4. Ask for **Compact Output Mode** or **Full Output Mode**.
5. Review the proposed architecture, governance gates, costs, risks, and execution plan.
6. Approve or revise the plan before implementation begins.

### Modular path

Use the separate modules when a user needs more explanation or when the project is complex:

- `01_PROJECT_AND_USER_DISCOVERY.md`
- `02_TECHNOLOGY_AND_APPLICATION_STYLE_GUIDE.md`
- `03_CAPABILITY_AI_RAG_AGENT_AND_INTEGRATION_MATRIX.md`
- `04_GOVERNANCE_SECURITY_ACCESSIBILITY_AND_OPERATIONS.md`

## Output modes

### Compact Output Mode

Produces three practical handoff files:

1. `PROJECT_BLUEPRINT.md`
2. `ARCHITECTURE_GOVERNANCE_AND_RISK.md`
3. `EXECUTION_PLAN_PUNCH_CARDS_AND_ACCEPTANCE.md`

### Full Output Mode

Produces a complete commissioning dossier:

1. Project brief
2. Confirmed facts, assumptions, unknowns, and contradictions
3. Functional requirements
4. Non-functional requirements
5. Users, roles, and workflows
6. Accessibility and inclusive design plan
7. Data, privacy, and retention plan
8. Security and trust model
9. Capability and integration plan
10. Architecture options
11. Recommended architecture
12. Architecture decision records
13. Deployment, recovery, and operations plan
14. Cost and capacity estimate
15. Test and acceptance strategy
16. Risks and mitigations
17. Execution waves and punch cards
18. Initial project prompt and orchestration contract

## Core operating rule

The commissioning system must distinguish:

- **Confirmed facts**
- **User preferences**
- **Engineering recommendations**
- **Assumptions**
- **Unknowns**
- **Decisions requiring approval**

It must not silently convert an assumption into a requirement.

## Implementation boundary

The questionnaire and generated documents are planning artifacts. They do not authorize:

- machine-level software installation;
- use of paid services;
- creation of external accounts;
- connection to production systems;
- authentication or authorization changes;
- data migrations or deletions;
- external communication;
- load, chaos, or red-team testing;
- deployment outside the approved environment.

Those actions require explicit user approval.

## Files in this pack

- `00_FULL_COMMISSIONING_QUESTIONNAIRE.md` — all questions in one place
- `01_PROJECT_AND_USER_DISCOVERY.md` — idea, users, workflows, data, priorities
- `02_TECHNOLOGY_AND_APPLICATION_STYLE_GUIDE.md` — plain-language stack and architecture guide
- `03_CAPABILITY_AI_RAG_AGENT_AND_INTEGRATION_MATRIX.md` — capability selection
- `04_GOVERNANCE_SECURITY_ACCESSIBILITY_AND_OPERATIONS.md` — security, accessibility, deployment, governance
- `05_AI_COMMISSIONING_FACILITATOR_PROMPT.md` — prompt used to conduct the interview and generate outputs
- `06_OUTPUT_DOCUMENT_CONTRACT.md` — required contents of generated documents
- `07_ARCHITECTURE_DECISION_RECORD_TEMPLATE.md` — reusable ADR template
- `08_ANSWER_SHEET_TEMPLATE.md` — shortened answer sheet
- `questionnaire_answers.template.yaml` — optional machine-readable answer structure
- `SOURCES_AND_STANDARDS.md` — official standards used as reference points

## Design position

This framework does not attempt to make a model magically smarter. It reduces avoidable failure by forcing the work through discovery, clarification, architecture, governance, acceptance, and evidence before broad implementation.
