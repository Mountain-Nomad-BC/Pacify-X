# Full New Project Commissioning Questionnaire

This is the combined intake. Answer in plain language. Skip anything that clearly does not apply. A commissioning AI should ask only the follow-up questions that materially affect the architecture, governance, cost, risk, or acceptance plan.

After completion, use `05_AI_COMMISSIONING_FACILITATOR_PROMPT.md` to generate the project documents.


---


# Project and User Discovery

Answer in plain language. “Unsure” is acceptable. Examples are encouraged.

## 1. Idea and outcome

### 1.1 What are you trying to build?

Describe it as if explaining it to someone who has never heard of it.

**Answer:**

### 1.2 What problem does it solve?

What is currently slow, expensive, difficult, risky, repetitive, confusing, or impossible?

**Answer:**

### 1.3 Who experiences the problem?

Examples: you, employees, customers, technicians, managers, students, patients, developers, another software system.

**Answer:**

### 1.4 What would success look like?

Describe what a user should be able to accomplish when the project works.

**Answer:**

### 1.5 What should the project not become?

List anything explicitly out of scope.

**Answer:**

### 1.6 Is this replacing something, improving something, or creating something new?

**Answer:**

### 1.7 What is the smallest version that would still be useful?

**Answer:**

### 1.8 What would make you reject the project even if it technically works?

Examples: too expensive, too complicated, insecure, difficult to maintain, inaccessible, inaccurate, too slow.

**Answer:**

---

## 2. Users and roles

### 2.1 Who will use it?

Select all that apply:

- [ ] Only me
- [ ] A small trusted group
- [ ] An internal team
- [ ] A department
- [ ] An entire organization
- [ ] Customers
- [ ] General public
- [ ] Partners or contractors
- [ ] Other software systems
- [ ] Automated agents
- [ ] Unsure

### 2.2 Does every user need the same access?

- [ ] Yes
- [ ] No
- [ ] Unsure

### 2.3 What roles may be needed?

Examples: viewer, user, editor, approver, manager, support, auditor, administrator, developer, service account, AI agent.

**Answer:**

### 2.4 For each role, what may it view, create, change, approve, export, delete, or administer?

**Answer:**

### 2.5 Should any action require two people, elevated approval, or a second confirmation?

**Answer:**

### 2.6 What mistakes or misuse are users likely to attempt accidentally?

**Answer:**

### 2.7 What misuse might someone attempt intentionally?

**Answer:**

---

## 3. User workflow

### 3.1 Describe the normal start-to-finish workflow.

Use numbered steps if possible.

**Answer:**

### 3.2 What are the three most important user actions?

1.
2.
3.

### 3.3 What information enters the system?

Examples: forms, files, email, API data, sensor data, images, audio, transcripts, database records.

**Answer:**

### 3.4 What should the system produce?

Examples: dashboard, recommendation, report, notification, file, API response, database update, automated action.

**Answer:**

### 3.5 Which actions must be reversible?

**Answer:**

### 3.6 Which actions must require confirmation?

**Answer:**

### 3.7 What should happen if a user leaves halfway through a task?

**Answer:**

### 3.8 What should happen if the system fails halfway through a task?

Select or describe:

- [ ] Save progress
- [ ] Retry automatically
- [ ] Roll back
- [ ] Notify someone
- [ ] Continue in reduced mode
- [ ] Stop and require review
- [ ] Unsure

### 3.9 Are there approvals, queues, handoffs, escalations, or status changes?

**Answer:**

---

## 4. Data

### 4.1 What data will the system handle?

Select all that apply:

- [ ] Public information
- [ ] Internal business information
- [ ] Customer information
- [ ] Personal information
- [ ] Authentication information
- [ ] Financial information
- [ ] Health-related information
- [ ] Proprietary documents
- [ ] Source code
- [ ] Images, audio, or video
- [ ] Logs and analytics
- [ ] AI prompts, responses, memories, or embeddings
- [ ] Sensor or telemetry data
- [ ] Unsure

### 4.2 Where does the data come from?

**Answer:**

### 4.3 Which system or person is the source of truth for each important data type?

**Answer:**

### 4.4 Where should the data be stored?

- [ ] Only on this device
- [ ] Local network
- [ ] Existing company database
- [ ] Cloud database
- [ ] Cloud object storage
- [ ] External platform
- [ ] Multiple places
- [ ] Unsure

### 4.5 How long should each data type be retained?

**Answer:**

### 4.6 What must never be stored?

**Answer:**

### 4.7 Should users be able to view, correct, export, or delete their data?

**Answer:**

### 4.8 What should happen when two systems disagree?

- [ ] This project wins
- [ ] External system wins
- [ ] Most recent update wins
- [ ] Highest-authority source wins
- [ ] Preserve both and require review
- [ ] Quarantine and log the conflict
- [ ] Unsure

### 4.9 Will incoming or outgoing data need translation?

Examples: field mapping, unit conversion, schema conversion, terminology normalization, file conversion, version compatibility.

**Answer:**

---

## 5. Existing assets and constraints

### 5.1 What already exists?

Examples: code, documents, diagrams, spreadsheets, APIs, databases, prototypes, design files, policies.

**Answer:**

### 5.2 What existing work must be preserved?

**Answer:**

### 5.3 Are there known failures, previous attempts, or lessons learned?

**Answer:**

### 5.4 Are there required technologies, platforms, vendors, or languages?

**Answer:**

### 5.5 Are any technologies, platforms, vendors, or languages forbidden?

**Answer:**

### 5.6 Is there a deadline or fixed event?

**Answer:**

### 5.7 Who will maintain the project?

**Answer:**

---

## 6. Budget and priorities

### 6.1 Build budget

- [ ] Free tools only
- [ ] Very limited
- [ ] Small project budget
- [ ] Department budget
- [ ] Enterprise budget
- [ ] Unknown

### 6.2 Monthly operating budget

**Answer:**

### 6.3 Are paid APIs or commercial services acceptable?

**Answer:**

### 6.4 Rank what matters most.

Use each number once or mark the top five.

- ___ Accuracy
- ___ Security
- ___ Accessibility
- ___ Speed to first usable version
- ___ Low operating cost
- ___ Performance
- ___ Scalability
- ___ Maintainability
- ___ Ease of use
- ___ Visual polish
- ___ Flexibility
- ___ Auditability
- ___ Offline operation
- ___ Automation

### 6.5 Preferred tradeoffs

**Speed vs. certainty**

- [ ] Build quickly and improve later
- [ ] Move slower with stronger validation
- [ ] Decide based on risk

**Cost vs. convenience**

- [ ] Minimize operating cost
- [ ] Pay more for easier operation
- [ ] Balance them

**Flexibility vs. simplicity**

- [ ] Support many configurations
- [ ] Use strong opinionated defaults
- [ ] Balance them

**Automation vs. control**

- [ ] Automate aggressively
- [ ] Require more approvals
- [ ] Decide based on risk

---

## 7. Communication and working style

### 7.1 How often should the system stop for approval?

- [ ] Only for high-risk actions
- [ ] At the end of each major phase
- [ ] Frequently
- [ ] Decide based on risk

### 7.2 How much explanation do you want?

- [ ] Decisions and results only
- [ ] Brief explanations
- [ ] Detailed engineering explanations
- [ ] Teach me while working

### 7.3 How should uncertainty be handled?

- [ ] Make reasonable assumptions and document them
- [ ] Ask whenever uncertain
- [ ] Continue only when risk is low
- [ ] Decide based on impact

### 7.4 Should the system challenge your assumptions when evidence disagrees?

- [ ] Yes
- [ ] Present options politely
- [ ] Only for high-risk issues
- [ ] No

### 7.5 What are you most worried will go wrong?

**Answer:**

### 7.6 What part are you most excited about?

**Answer:**

### 7.7 In one sentence, what should this project become?

**Answer:**


---


# Technology and Application Style Guide

This guide helps a nontechnical user describe the workload. The commissioning AI should recommend technologies after understanding the needs; it should not force the user to select a language they do not understand.

Before final selection, current versions, maintenance status, licensing, vulnerabilities, hosting support, and team skills must be researched.

---

## 1. Application style questions

### 1.1 What kind of experience is needed?

Select all that apply:

- [ ] Public website
- [ ] Internal web application
- [ ] Dashboard
- [ ] Administrative portal
- [ ] Customer portal
- [ ] Mobile application
- [ ] Desktop application
- [ ] Command-line tool
- [ ] Background service
- [ ] API only
- [ ] Data-processing pipeline
- [ ] AI or agent platform
- [ ] Browser extension
- [ ] Embedded or device software
- [ ] Offline-first application
- [ ] Real-time collaboration
- [ ] Unsure

### 1.2 Where must it run?

- [ ] Web browser
- [ ] Windows
- [ ] macOS
- [ ] Linux
- [ ] iOS
- [ ] Android
- [ ] Server
- [ ] Cloud
- [ ] Edge device
- [ ] Local network
- [ ] Multiple environments
- [ ] Unsure

### 1.3 Does it need to work without Internet access?

**Answer:**

### 1.4 Does it need real-time updates?

Examples: live dashboards, chat, collaboration, telemetry, job status.

**Answer:**

### 1.5 Will it perform long-running or heavy processing?

Examples: large file processing, AI inference, video, analytics, bulk imports, simulations.

**Answer:**

### 1.6 Does it need hardware access?

Examples: camera, microphone, Bluetooth, serial ports, sensors, GPU.

**Answer:**

---

## 2. Frontend technology guidance

### TypeScript + React/TSX

**Strong for**

- Large interactive web applications
- Dashboards and administrative systems
- Broad component ecosystem
- Shared types with a TypeScript backend
- Teams that need extensive tooling and integrations

**Watch for**

- Dependency sprawl
- State-management complexity
- Inconsistent component patterns
- Build-tool churn
- Accessibility regressions when components are poorly chosen

### Vue + TypeScript

**Strong for**

- Progressive adoption
- Clear component structure
- Small-to-large web applications
- Teams wanting a gentler learning curve than some React stacks

**Watch for**

- Smaller ecosystem than React
- Mixed project conventions when teams do not standardize patterns

### Svelte / SvelteKit

**Strong for**

- Lean interactive applications
- Lower client-side overhead
- Fast development with less boilerplate
- Public and internal web experiences

**Watch for**

- Smaller hiring and enterprise ecosystem
- Some libraries and patterns are less mature than React equivalents

### Angular + TypeScript

**Strong for**

- Large, governed enterprise applications
- Opinionated project structure
- Strong dependency injection and form tooling
- Large teams requiring consistent conventions

**Watch for**

- Higher learning curve
- More framework ceremony
- Can be excessive for small products

### Plain HTML, CSS, and JavaScript

**Strong for**

- Small sites
- Static documentation
- Simple tools
- Minimal dependencies and long-term stability

**Watch for**

- Complex applications become difficult to organize
- Teams may recreate framework features inconsistently

### Desktop options

**Electron**

- Strong web ecosystem and broad desktop support
- Larger memory and package footprint

**Tauri**

- Smaller desktop footprint and stronger native boundary
- Requires Rust-related tooling and more integration knowledge

**Native .NET, Swift, Kotlin, Qt, or similar**

- Strong platform integration and performance
- More platform-specific development and maintenance

### Mobile options

**React Native**

- TypeScript/JavaScript ecosystem and shared concepts with React
- Native integration can still require platform-specific work

**Flutter**

- Consistent cross-platform UI and strong developer experience
- Uses Dart and has a distinct ecosystem

**Native Swift / Kotlin**

- Best platform integration and access to current platform capabilities
- Two codebases when supporting both iOS and Android

---

## 3. Backend language and framework guidance

### Python

Common frameworks: FastAPI, Django, Flask.

**Strong for**

- AI, machine learning, automation, analytics, scripting
- Rapid API development
- Data processing and scientific tooling
- Integration-heavy systems

**Watch for**

- CPU-bound performance without parallel or native strategies
- Dependency and environment discipline
- Dynamic typing unless type checking is enforced
- Long-running background work should be separated from request handling

### TypeScript / Node.js

Common frameworks: NestJS, Fastify, Express, Hono.

**Strong for**

- Full-stack TypeScript
- Real-time applications
- API services
- Event-driven and I/O-heavy workloads
- Shared data contracts between frontend and backend

**Watch for**

- Async and dependency complexity
- Runtime validation is still required despite static types
- Package supply-chain volume

### C# / .NET

**Strong for**

- Microsoft ecosystems
- Enterprise APIs and services
- Strong tooling, typing, performance, and identity integrations
- Desktop and cloud workloads

**Watch for**

- Some AI and data workflows may still be easier in Python
- Platform conventions can become heavy for small projects

### Java / Spring

**Strong for**

- Large enterprise systems
- Mature security and integration ecosystem
- Long-lived services
- Large teams and strict conventions

**Watch for**

- More ceremony and configuration
- Slower iteration for small prototypes
- Framework complexity should match project scale

### Go

**Strong for**

- Networking, concurrency, infrastructure, APIs, and small deployable binaries
- Predictable performance and simple deployment
- Services requiring operational efficiency

**Watch for**

- Smaller AI/data-science ecosystem
- Some complex domain modeling can feel repetitive

### Rust

**Strong for**

- Memory safety
- Systems programming
- High performance
- Security-sensitive tooling
- Native extensions and resource-constrained services

**Watch for**

- Higher learning curve
- Slower development for ordinary business applications
- Smaller pool of developers

### Ruby on Rails

**Strong for**

- Rapid business application development
- Convention-driven CRUD systems
- Mature web-development patterns

**Watch for**

- Performance and scaling may require deliberate design
- Smaller current ecosystem than major TypeScript/Python stacks

### PHP / Laravel

**Strong for**

- Web applications
- Broad hosting support
- Rapid business development
- Mature framework conventions

**Watch for**

- Code quality varies widely without strict standards
- Complex real-time or AI workloads may require companion services

---

## 4. Architecture style questions

### 4.1 How large is the first version?

- [ ] Small and focused
- [ ] Medium with several workflows
- [ ] Large with many domains
- [ ] Unsure

### 4.2 Will different parts need to scale independently?

**Answer:**

### 4.3 Will multiple teams own different parts?

**Answer:**

### 4.4 Do parts need different languages or runtimes?

**Answer:**

### 4.5 How costly would distributed-system complexity be?

**Answer:**

### Architecture patterns

**Single application / monolith**

Best when the project is small, the team is small, and deployment simplicity matters.

**Modular monolith**

Best default for many serious products: one deployable system with strict internal boundaries that can later be separated.

**Microservices**

Useful when independent scaling, ownership, release cycles, or fault isolation justify operational complexity.

**Event-driven architecture**

Useful for asynchronous workflows, integrations, audit trails, and high-volume processing. Requires strong idempotency, retry, ordering, and observability design.

**Serverless**

Useful for bursty workloads and reduced infrastructure management. Watch cold starts, execution limits, vendor coupling, and distributed observability.

**Local-first / offline-first**

Useful when connectivity is unreliable or privacy requires local data. Requires conflict resolution, synchronization, and upgrade planning.

**Pipeline architecture**

Useful for ETL, AI, media, transcript, analytics, and staged processing. Requires checkpointing, reproducibility, contracts, and failure recovery.

---

## 5. Data storage guidance

### SQLite

Strong for local applications, prototypes, test environments, and low-concurrency systems.

### PostgreSQL

Strong general-purpose default for structured data, transactions, reporting, JSON support, and mature operations.

### MySQL / MariaDB

Strong for traditional web workloads and broad hosting compatibility.

### Document database

Useful when records vary substantially and transactional relational joins are not central. Avoid using schema flexibility as an excuse for undefined data contracts.

### Redis or equivalent cache

Useful for caching, queues, sessions, rate limits, and short-lived state. It should not casually become the only durable source of truth.

### Object storage

Useful for files, media, exports, models, archives, and large immutable artifacts.

### Search engine

Useful for full-text search, log search, faceting, and large searchable corpora.

### Vector database or vector extension

Useful for semantic retrieval. It does not replace source validation, metadata filters, access control, or evaluation.

### Graph database

Useful when relationships, paths, dependencies, and graph queries are central. It should be selected because graph operations are required, not because the project contains relationships.

### Time-series database

Useful for high-volume timestamped telemetry, metrics, and retention policies.

---

## 6. Deployment style questions

### 6.1 Preferred first deployment

- [ ] Local process
- [ ] Docker Compose
- [ ] Managed platform
- [ ] Virtual machine
- [ ] Serverless
- [ ] Kubernetes
- [ ] Mobile or desktop package
- [ ] Unsure

### 6.2 Who will operate it?

**Answer:**

### 6.3 How much infrastructure management is acceptable?

**Answer:**

### 6.4 Does it require automatic scaling?

**Answer:**

### 6.5 Does it require staged, blue/green, canary, or rollback-capable deployment?

**Answer:**

### 6.6 Is vendor portability important?

**Answer:**

---

## 7. Technology decision output

For each major technology choice, produce an Architecture Decision Record containing:

- Decision
- Status
- Problem being solved
- Confirmed requirements
- Options considered
- Strengths and weaknesses
- Cost implications
- Security implications
- Accessibility implications
- Maintenance implications
- Operational implications
- Why the recommendation fits
- Conditions that would invalidate the recommendation
- Confidence
- Approval required


---


# Capability, AI, RAG, Agent, and Integration Matrix

Select capabilities based on what the product must do. The commissioning AI should explain when a requested capability is unnecessary, risky, expensive, or better solved without AI.

---

## 1. Standard product capabilities

- [ ] User accounts
- [ ] Multiple roles and permissions
- [ ] Administrative console
- [ ] Search
- [ ] File upload and download
- [ ] Reporting
- [ ] Dashboards
- [ ] Notifications
- [ ] Email
- [ ] Calendar
- [ ] Real-time updates
- [ ] Workflow approvals
- [ ] Audit history
- [ ] Import and export
- [ ] Public API
- [ ] Internal API
- [ ] Webhooks
- [ ] Offline operation
- [ ] Multi-language support
- [ ] Mobile support
- [ ] Desktop support
- [ ] Browser extension
- [ ] Payments
- [ ] Subscription or licensing
- [ ] Mapping or geospatial features
- [ ] Document generation
- [ ] Media processing
- [ ] Telemetry or sensor processing
- [ ] Scheduled jobs
- [ ] Background queues
- [ ] Other:

For every selected capability, describe the user outcome it supports.

---

## 2. AI need assessment

### 2.1 Which problems appear to need AI?

- [ ] Natural-language conversation
- [ ] Summarization
- [ ] Classification
- [ ] Extraction
- [ ] Translation
- [ ] Recommendation
- [ ] Forecasting
- [ ] Anomaly detection
- [ ] Image understanding
- [ ] Audio or speech
- [ ] Code generation
- [ ] Planning
- [ ] Diagnostics
- [ ] Workflow automation
- [ ] Agentic action
- [ ] No AI required
- [ ] Unsure

### 2.2 Could rules, search, statistics, or normal software solve the same problem more reliably or cheaply?

**Answer:**

### 2.3 What is the cost of an incorrect AI result?

- [ ] Minor inconvenience
- [ ] Recoverable user error
- [ ] Business disruption
- [ ] Financial impact
- [ ] Privacy impact
- [ ] Legal or regulatory impact
- [ ] Physical or safety impact

### 2.4 What evidence should accompany AI output?

- [ ] Source citations
- [ ] Retrieved passages
- [ ] Confidence or uncertainty
- [ ] Rule or model version
- [ ] Tool-call evidence
- [ ] Human approval
- [ ] Audit record
- [ ] None
- [ ] Unsure

---

## 3. Model placement and connection

### 3.1 Where may models run?

- [ ] Local device only
- [ ] Private company infrastructure
- [ ] Private cloud
- [ ] Approved external AI API
- [ ] Multiple providers through a gateway
- [ ] No external AI
- [ ] Unsure

### 3.2 What information may be sent to an external model?

**Answer:**

### 3.3 What information must remain local?

**Answer:**

### 3.4 Is model-provider portability required?

**Answer:**

### 3.5 Is offline model operation required?

**Answer:**

### 3.6 What are the latency, token, throughput, and monthly cost limits?

**Answer:**

---

## 4. Knowledge and RAG capabilities

### 4.1 Does the system need to answer from private or specialized knowledge?

**Answer:**

### 4.2 Knowledge sources

- [ ] Documents
- [ ] Websites
- [ ] Database records
- [ ] Tickets or cases
- [ ] Emails
- [ ] Source code
- [ ] Logs
- [ ] Images
- [ ] Audio or transcripts
- [ ] Knowledge graph
- [ ] External APIs
- [ ] User-provided files
- [ ] Other:

### 4.3 Retrieval style

- [ ] Keyword search
- [ ] Semantic vector retrieval
- [ ] Hybrid keyword + vector retrieval
- [ ] Graph-assisted retrieval
- [ ] Structured database queries
- [ ] Multi-stage retrieval and reranking
- [ ] Unsure

### 4.4 Does retrieval need permission-aware filtering?

**Answer:**

### 4.5 How often does knowledge change?

**Answer:**

### 4.6 Should deleted or expired information disappear from retrieval immediately?

**Answer:**

### 4.7 How will retrieval accuracy be evaluated?

Examples: known-answer set, citation correctness, retrieval recall, relevance, groundedness, refusal behavior.

**Answer:**

### RAG guidance

**Basic RAG**

Useful for moderate document collections with clear sources and simple access rules.

**Hybrid RAG**

Combines semantic and lexical retrieval; often stronger when exact codes, names, identifiers, technical terms, or rare phrases matter.

**Graph RAG**

Useful when relationship traversal, dependencies, provenance, or multi-hop questions are central. It adds extraction, graph-quality, update, and governance complexity.

**Structured retrieval**

Prefer direct database or API queries when the answer is already represented as structured data.

**RAG warning**

Retrieval does not create truth. The design must evaluate indexing, chunking, metadata, permissions, freshness, citations, conflicting sources, and failure to retrieve.

---

## 5. Agentic capabilities

### 5.1 Does the system need agents, or would a deterministic workflow be enough?

**Answer:**

### 5.2 Agent capabilities

- [ ] Plan tasks
- [ ] Use tools
- [ ] Read files
- [ ] Write files
- [ ] Run code
- [ ] Query databases
- [ ] Call internal APIs
- [ ] Call external APIs
- [ ] Browse approved websites
- [ ] Send messages
- [ ] Schedule work
- [ ] Create or modify records
- [ ] Deploy software
- [ ] Create new reusable skills
- [ ] Coordinate other agents
- [ ] None
- [ ] Unsure

### 5.3 What may agents do without approval?

**Answer:**

### 5.4 What must always require approval?

**Answer:**

### 5.5 What must agents never do?

**Answer:**

### 5.6 Does each agent need its own identity, role, permissions, and audit trail?

**Answer:**

### 5.7 Should agents have memory?

- [ ] No persistent memory
- [ ] Session-only memory
- [ ] Project memory
- [ ] User-specific memory
- [ ] Structured task memory
- [ ] Vector memory
- [ ] Graph memory
- [ ] Unsure

### 5.8 How should memory be corrected, expired, exported, or deleted?

**Answer:**

### 5.9 Should the system create new skills when it discovers a repeated capability gap?

- [ ] No
- [ ] Propose only
- [ ] Draft and test, then request approval
- [ ] Activate automatically after governed validation
- [ ] Unsure

### 5.10 What containment boundary applies?

Examples: project directory only, local sandbox only, approved Docker networks, approved APIs only, no Internet, no production.

**Answer:**

---

## 6. Internal and external integration

For every integration, answer:

- Name of system
- Business purpose
- Required for first release?
- Read, write, or both?
- Data sent
- Data received
- Authentication method
- Expected volume
- Cost or rate limit
- Failure behavior
- Source of truth
- Retention impact
- Privacy impact
- Audit requirement
- Test environment available?
- Owner or approver

### Integration categories

- [ ] Email
- [ ] Calendar
- [ ] Messaging or collaboration
- [ ] Git hosting
- [ ] Issue tracking
- [ ] CRM
- [ ] ERP
- [ ] Identity provider
- [ ] File storage
- [ ] Document management
- [ ] Payments
- [ ] Analytics
- [ ] Monitoring
- [ ] AI provider
- [ ] Internal API
- [ ] External API
- [ ] Webhook
- [ ] Database
- [ ] IoT or telemetry platform
- [ ] Other:

---

## 7. Data adaptation and interoperability

### 7.1 Must outside data adapt to this system?

Examples: normalize fields, clean records, map roles, convert units, resolve identifiers, validate schemas.

**Answer:**

### 7.2 Must this system adapt its output to another system?

Examples: JSON contract, CSV template, document format, database schema, API payload.

**Answer:**

### 7.3 Can external schemas change?

**Answer:**

### 7.4 How should schema changes be detected and handled?

- [ ] Fail fast
- [ ] Version adapters
- [ ] Quarantine incompatible records
- [ ] Attempt safe conversion
- [ ] Human review
- [ ] Unsure

### 7.5 Is backward compatibility required?

**Answer:**

### 7.6 Is vendor-independent export required?

**Answer:**

---

## 8. Automation and orchestration

### 8.1 Trigger style

- [ ] User initiated
- [ ] Scheduled
- [ ] Event driven
- [ ] Queue based
- [ ] File arrival
- [ ] Webhook
- [ ] Monitoring condition
- [ ] Agent initiated
- [ ] Other:

### 8.2 Do workflows need checkpointing and resume?

**Answer:**

### 8.3 Do workflows need idempotency?

**Answer:**

### 8.4 What retry behavior is acceptable?

**Answer:**

### 8.5 What actions require compensation or rollback?

**Answer:**

### 8.6 Should repetitive high-volume work be offloaded to deterministic scripts?

- [ ] Python
- [ ] Node/TypeScript
- [ ] PowerShell
- [ ] Shell
- [ ] YAML workflow
- [ ] Database procedure
- [ ] Queue worker
- [ ] Unsure

---

## 9. Observability and improvement

- [ ] Structured logs
- [ ] Metrics
- [ ] Distributed traces
- [ ] Error tracking
- [ ] Audit logs
- [ ] Cost tracking
- [ ] AI token and latency tracking
- [ ] Retrieval-quality evaluation
- [ ] Agent action ledger
- [ ] User behavior analytics
- [ ] Health checks
- [ ] Auto-recovery
- [ ] Self-healing
- [ ] Capacity alerts
- [ ] Security alerts
- [ ] Other:

Describe required dashboards, alerts, and owners.

**Answer:**


---


# Governance, Security, Accessibility, and Operations

This module determines the level of control required before a project may be considered ready for official deployment.

It is not legal advice. The commissioning process must identify the applicable jurisdiction, organization, contract, industry, and deployment type, then verify the exact current requirements.

---

## 1. Accessibility and inclusive design

Accessibility must be assessed for every official deployment. It is not an optional decorative feature.

WCAG 2.2 Level AA is a strong current engineering target where no different governed standard is required. Some legal or procurement regimes require a specific version; for example, the U.S. Department of Justice Title II web and mobile rule for state and local governments uses WCAG 2.1 Level AA. The exact obligation must be verified for the project.

### 1.1 Deployment context

- [ ] Personal prototype
- [ ] Internal employee tool
- [ ] Customer-facing product
- [ ] Public website or application
- [ ] State or local government
- [ ] Federal government
- [ ] Educational institution
- [ ] Healthcare
- [ ] International or multi-jurisdiction
- [ ] Procurement-controlled environment
- [ ] Unsure

### 1.2 Countries, states, provinces, or jurisdictions

**Answer:**

### 1.3 Required standards

- [ ] WCAG 2.2 Level AA
- [ ] WCAG 2.1 Level AA
- [ ] Section 508
- [ ] EN 301 549
- [ ] European Accessibility Act-related requirements
- [ ] Organization-specific standard
- [ ] Procurement requirement
- [ ] Research required
- [ ] Unsure

### 1.4 Required interaction support

- [ ] Keyboard-only operation
- [ ] Screen-reader support
- [ ] Voice-control support
- [ ] Visible focus
- [ ] Skip navigation
- [ ] Zoom and reflow
- [ ] Touch target sizing
- [ ] Captions
- [ ] Transcripts
- [ ] Text alternatives
- [ ] Error identification and recovery
- [ ] Accessible authentication
- [ ] Reduced motion
- [ ] Other:

### 1.5 Theme and presentation controls

- [ ] Follow system light/dark setting
- [ ] Manual light/dark toggle
- [ ] High-contrast mode
- [ ] User-selectable themes
- [ ] Organization theme
- [ ] Adjustable font size
- [ ] Adjustable spacing
- [ ] Simplified-language mode
- [ ] Dyslexia-oriented font option
- [ ] Bionic/emphasized-text toggle
- [ ] Reduced motion
- [ ] User preference persistence
- [ ] No additional controls
- [ ] Unsure

Optional reading aids such as bionic text or specialized fonts must not be represented as substitutes for WCAG conformance or user testing.

### 1.6 Brand and color requirements

Provide required colors, forbidden colors, whether users may override the theme, and whether color is ever used as the only status indicator.

**Answer:**

### 1.7 Accessibility validation

- [ ] Automated scan
- [ ] Keyboard walkthrough
- [ ] Screen-reader walkthrough
- [ ] Contrast validation
- [ ] Zoom/reflow
- [ ] Mobile accessibility
- [ ] Reduced-motion testing
- [ ] Manual form and error review
- [ ] Assistive-technology user testing
- [ ] Formal conformance report
- [ ] Accessibility statement
- [ ] Exception register
- [ ] Unsure

---

## 2. Security level

Select the minimum level, then allow the commissioning AI to recommend a higher level based on data, users, integrations, and impact.

### Level 0 — Personal prototype

- One trusted user
- Local, non-sensitive data
- Basic secret hygiene
- Basic dependency checking
- No public exposure

### Level 1 — Small application

- Individual authentication when required
- Input validation
- Secure secret storage
- Basic role separation
- Dependency and vulnerability scanning
- Basic logs, backups, and update process

### Level 2 — Business application

- Central identity where practical
- Role-based access control
- Multi-factor authentication where appropriate
- Audit trails
- Data retention and deletion rules
- Backup and recovery
- Controlled deployments
- Security testing
- Incident handling

### Level 3 — Enterprise acceptance

- Least privilege
- RBAC and, when necessary, attribute-based controls
- Segregation of duties
- Centralized secrets management
- Token and key rotation
- Full audit correlation
- Supply-chain validation
- Static, dynamic, dependency, secret, and container scanning
- Resilience and recovery testing
- Formal approval gates
- Evidence-backed acceptance
- Defined SLOs and operational ownership

### Level 4 — High assurance

- Zero-trust assumptions
- Strong identity, device, and network controls
- Restricted egress and service boundaries
- Threat modeling
- Adversarial and red-team validation
- Continuous security verification
- Tamper-resistant audit evidence
- Formal incident and disaster-recovery exercises
- Additional legal, safety, or regulated controls

**Selected level:**

**Reason:**

---

## 3. Authentication, roles, and authorization

### 3.1 Account model

- [ ] No account
- [ ] Shared local account
- [ ] Individual local accounts
- [ ] Company identity provider
- [ ] Customer identity
- [ ] Passkeys
- [ ] MFA
- [ ] Service accounts
- [ ] Agent identities
- [ ] Unsure

### 3.2 Required authorization model

- [ ] No roles
- [ ] Simple owner/user split
- [ ] Role-based access control
- [ ] Attribute-based access control
- [ ] Relationship-based access
- [ ] Policy engine
- [ ] Unsure

### 3.3 Most damaging unauthorized action

**Answer:**

### 3.4 Actions requiring step-up authentication or approval

**Answer:**

### 3.5 Must UI, API, tool, and data-layer authorization be independently enforced?

- [ ] Yes
- [ ] No
- [ ] Unsure

---

## 4. Zero-trust external component intake

Every proposed package, extension, MCP server, container image, binary, model, plugin, script, and third-party tool must be treated as untrusted until reviewed.

### Intake stages

1. Identify exact source, owner, version, license, and purpose.
2. Download only into an approved quarantine or isolated inspection environment.
3. Verify signatures, checksums, package provenance, and official source where available.
4. Generate inventory and software bill of materials where practical.
5. Scan for known vulnerabilities.
6. Scan for secrets, malware indicators, suspicious install scripts, unexpected network behavior, and dangerous permissions.
7. Review transitive dependencies.
8. Evaluate maintenance status, release history, community health, and ownership changes.
9. Evaluate licensing and redistribution restrictions.
10. Test compatibility in isolation.
11. Produce evidence and a risk decision.
12. Require approval before integration.
13. Pin or constrain versions and record update policy.
14. Re-scan when versions change.

### 4.1 Required intake rigor

- [ ] Basic source and vulnerability check
- [ ] Isolated install and scan
- [ ] Full quarantine, SBOM, behavioral review, and approval
- [ ] Depends on risk
- [ ] Unsure

### 4.2 May the framework install machine-level software automatically?

- [ ] Never
- [ ] Only after explicit approval
- [ ] Only inside a disposable sandbox
- [ ] Under an approved allowlist
- [ ] Unsure

### 4.3 May packages make outbound network connections during installation or testing?

**Answer:**

---

## 5. Secret and credential handling

### 5.1 Secret types

- [ ] API keys
- [ ] Database credentials
- [ ] OAuth secrets
- [ ] Certificates
- [ ] Personal access tokens
- [ ] Signing keys
- [ ] Encryption keys
- [ ] Model-provider credentials
- [ ] None
- [ ] Unsure

### 5.2 Approved storage

- [ ] Operating-system credential manager
- [ ] Enterprise vault
- [ ] Cloud secret manager
- [ ] Encrypted local secret store
- [ ] Environment injection
- [ ] Hardware-backed store
- [ ] Unsure

Plaintext secrets, repository secrets, logs containing secrets, homemade reversible encoding, and one-way hashes intended for later authentication are not acceptable secret-storage designs.

### 5.3 Rotation, expiration, revocation, and break-glass requirements

**Answer:**

---

## 6. Privacy, retention, and data governance

### 6.1 Does the project process personal, sensitive, regulated, proprietary, or customer data?

**Answer:**

### 6.2 Is consent required?

**Answer:**

### 6.3 Data minimization rules

**Answer:**

### 6.4 Retention and deletion rules

**Answer:**

### 6.5 Data residency requirements

**Answer:**

### 6.6 Training and AI use restrictions

May user or company data be used for model training, evaluation, memory, analytics, or debugging?

**Answer:**

### 6.7 Required documents

- [ ] Privacy policy
- [ ] Data retention policy
- [ ] Data-processing agreement
- [ ] Records schedule
- [ ] Cookie or tracking notice
- [ ] AI-use disclosure
- [ ] Model card
- [ ] Data-flow diagram
- [ ] Data inventory
- [ ] Other:

---

## 7. Deployment gates

Official deployment must not proceed only because builds and tests are green.

### Required questions

- Is the target environment approved?
- Are environment variables and secrets correct?
- Are debug modes, mock identities, default credentials, and bypasses disabled?
- Are authentication and authorization enforced at every layer?
- Are database migrations reviewed, backed up, reversible, and tested?
- Are package, container, model, and artifact versions pinned or governed?
- Are SBOM and vulnerability results acceptable?
- Are licenses acceptable?
- Are accessibility requirements met or exceptions formally accepted?
- Are logs, metrics, traces, and audit events active?
- Are backups and restoration tested?
- Is rollback tested?
- Are SLOs, alerts, runbooks, owners, and escalation paths defined?
- Is data retention configured?
- Are external calls allowlisted and rate limited?
- Are cost limits and budget alerts active?
- Are destructive operations protected?
- Is evidence archived?

### 7.1 Deployment approval model

- [ ] Single owner
- [ ] Technical reviewer
- [ ] Security approval
- [ ] Accessibility approval
- [ ] Data/privacy approval
- [ ] Business owner approval
- [ ] Change board
- [ ] Automated gate plus human approval
- [ ] Unsure

### 7.2 Release strategy

- [ ] Direct release
- [ ] Staged environment
- [ ] Blue/green
- [ ] Canary
- [ ] Feature flags
- [ ] Ring deployment
- [ ] Manual package
- [ ] Unsure

---

## 8. Reliability, recovery, and operations

### 8.1 Availability target

- [ ] Best effort
- [ ] Usually available
- [ ] Business critical
- [ ] Continuous or safety critical
- [ ] Unsure

### 8.2 Recovery needs

- [ ] Automatic restart
- [ ] Resume from checkpoint
- [ ] Rollback
- [ ] Failover
- [ ] Reduced-function mode
- [ ] Manual recovery
- [ ] Unsure

### 8.3 Maximum acceptable data loss

**Answer:**

### 8.4 Maximum acceptable recovery time

**Answer:**

### 8.5 Backup requirements

**Answer:**

### 8.6 Monitoring and self-healing

- [ ] Health checks
- [ ] Structured logs
- [ ] Metrics
- [ ] Traces
- [ ] Alerts
- [ ] Auto-restart
- [ ] Auto-scaling
- [ ] Circuit breakers
- [ ] Queue recovery
- [ ] Automated rollback
- [ ] Human approval before repair
- [ ] Unsure

---

## 9. Testing and acceptance levels

### Basic

- Core user workflows
- Lint and type checks
- Unit tests
- Basic dependency, secret, and security checks
- Accessibility smoke checks

### Engineering

- Functional and integration tests
- Role and permission testing
- API contract testing
- Database and audit verification
- Dependency and supply-chain scanning
- Performance baseline
- Accessibility walkthrough
- Recovery testing
- Evidence reports

### Certification

- Verified control inventory
- End-to-end outcome contracts
- Cross-layer authorization verification
- Load and scaling tests
- Chaos testing
- Adversarial and red-team testing
- Accessibility conformance evidence
- Backup and disaster-recovery exercises
- Data-governance verification
- Operational readiness
- Documentation, licensing, and approval dossier

**Selected level:**

### Acceptance principle

A visual state change or successful HTTP response is not sufficient evidence of business correctness.

Where applicable, a pass should prove:

1. Authorized identity
2. Correct trigger
3. Expected API or service behavior
4. Correct persistence or non-persistence
5. Expected audit and telemetry event
6. Correct downstream effects
7. Correct resolved user interface
8. Correct repeat, retry, and idempotency behavior
9. No out-of-scope external activity

---

## 10. Governance approval gates

Explicit approval should be required before:

- Machine-level installation
- Global IDE or Git changes
- External account creation
- Paid service activation
- New MCP, plugin, package, model, or container integration
- External network access
- Authentication or authorization redesign
- Data migration or deletion
- Broad automated repair
- Production or customer data access
- External email or messaging
- Load, chaos, or red-team testing
- Production deployment
- Irreversible cleanup

List additional required gates.

**Answer:**
