---
name: adapt-human-learning-loop
description: Clean-room adaptive-learning and progress-tracking mechanisms with strong
  human-safety boundaries. Candidate external-intake bundle; keep inactive until PACIFY-X
  admission and owner review.
---

# Adapt Human Learning Loop

## Purpose

Clean-room adaptive-learning and progress-tracking mechanisms with strong human-safety boundaries.

## Loading rule

Load this candidate metadata only after semantic selection. Load one capability reference at a time. Raw external source material is quarantined as reference-only and must never execute merely because it is present.

## Candidate capabilities

### `maintain-learner-profile-boundary`

Keep each learner or trainee profile, activity history, rewards, observations, and permissions isolated so adaptation is scoped to the correct person and program.

**Use when:** training or simulation adapts per person; multiple learners share one system; progress history must remain attributable.

**Mechanisms:** profile identity; guardian or supervisor association; activity ownership; scoped history; role separation.

**Hard boundaries:** no health diagnosis or protected-trait inference; collect only necessary data; do not merge profiles from similarity.

**Proposed PACIFY-X owner:** `long-horizon-progress-ledger`

### `sequence-adaptive-learning-exercises`

Select and sequence bounded exercises using observed performance, modality, difficulty, fatigue signals supplied by authorized users, and explicit learning goals.

**Use when:** a training system offers several exercise types; difficulty should adjust from demonstrated performance; repetition must remain purposeful.

**Mechanisms:** exercise catalog; difficulty bands; modality rotation; bounded repetition; performance-conditioned next activity; human override.

**Hard boundaries:** no clinical treatment claims; do not infer fatigue or impairment without explicit evidence; avoid manipulative engagement optimization.

**Proposed PACIFY-X owner:** `govern-metacognitive-evolution`

### `capture-human-observer-assessment`

Capture structured human observations after an activity with timestamp, context, rubric, free-text notes, confidence, and clear separation from machine inference.

**Use when:** automated signals cannot observe the full outcome; a supervisor or caregiver must score performance; qualitative reactions matter.

**Mechanisms:** observer identity; activity binding; rubric score; free-text comment; positive/negative/neutral labels; timestamp.

**Hard boundaries:** label observations as subjective; do not convert one observer score into a diagnosis; preserve corrections and disputed entries.

**Proposed PACIFY-X owner:** `human-handoff-state-transfer`

### `maintain-behavior-event-ledger`

Record append-only, contextualized behavior or performance events with date, type, description, observer comments, source activity, and correction history.

**Use when:** progress must be reviewed over time; human observations need traceable context; reward changes require supporting events.

**Mechanisms:** append-only event record; typed event; observer comment; activity linkage; chronological history; correction record.

**Hard boundaries:** do not reduce people to positive or negative labels; avoid punitive ranking; support correction and deletion where policy requires.

**Proposed PACIFY-X owner:** `long-horizon-progress-ledger`

### `govern-reinforcement-token-economy`

Represent optional points or tokens as a transparent, bounded reinforcement mechanism with explicit earning and spending rules, immutable transactions, balance checks, and human oversight.

**Use when:** training uses points to acknowledge completion; rewards must be auditable; balances currently mutate without trace.

**Mechanisms:** transaction ledger; balance invariant; earn/spend reason; bounded awards; insufficient-balance handling; human override.

**Hard boundaries:** never tie essential access, dignity, care, or safety to tokens; avoid coercive or addictive mechanics; no hidden variable rewards.

**Proposed PACIFY-X owner:** `execution-contract-enforcer`

### `evaluate-cue-recall-and-recognition`

Evaluate short cue exposure followed by recall, recognition, association, or missing-item selection while separating accuracy, repeated attempts, timing, and hint use.

**Use when:** training memory or association; exercise performance needs structured metrics; hints and repeated attempts must be distinguished.

**Mechanisms:** timed cue presentation; recognition choices; recall attempts; duplicate-attempt handling; hint accounting; success criteria.

**Hard boundaries:** not a medical or cognitive diagnosis; normalize for accessibility and user-selected pacing; do not punish errors.

**Proposed PACIFY-X owner:** `active-evaluation-selector`

### `summarize-learning-progress`

Summarize activity completion, performance trends, observer notes, reward transactions, and data gaps over a defined time range without converting correlation into diagnosis.

**Use when:** a learner or supervisor needs a progress view; several activity types must be compared over time.

**Mechanisms:** time-window aggregation; exercise-level metrics; observer-note separation; trend uncertainty; missing-data disclosure.

**Hard boundaries:** no diagnosis, prognosis, or protected-trait inference; show sample size and uncertainty; do not hide negative or contradictory observations.

**Proposed PACIFY-X owner:** `long-horizon-progress-ledger`

### `design-replayable-exercise-state-machine`

Model exercises as explicit states and transitions so timers, exposure, attempts, completion, replay, reward, and exit behavior can be tested deterministically.

**Use when:** timed activities have inconsistent UI transitions; replay duplicates rewards or stale state; exercise logic is embedded in event handlers.

**Mechanisms:** idle/present/hidden/respond/complete states; timer events; attempt counter; replay reset; completion postcondition; reward-once invariant.

**Hard boundaries:** reward only after verified completion; reset all ephemeral state on replay; do not let UI labels become canonical state.

**Proposed PACIFY-X owner:** `bounded-workflow-topology-selector`

### `separate-supervisor-and-learner-roles`

Separate who performs an activity from who can register profiles, score observations, change rewards, inspect history, or export progress.

**Use when:** one interface currently mixes learner and supervisor actions; sensitive history or rewards need controlled access.

**Mechanisms:** role matrix; action-level permission checks; observer attribution; least privilege; audit trail.

**Hard boundaries:** learner autonomy and privacy remain explicit; no shared credentials; high-impact edits require traceable authorization.

**Proposed PACIFY-X owner:** `permission-diff-auditor`

### `safeguard-human-learning-systems`

Apply privacy, consent, accessibility, anti-coercion, age-appropriate design, human oversight, and non-diagnostic boundaries to adaptive learning and behavior-tracking systems.

**Use when:** software tracks children, patients, learners, or employees; reward systems or behavior labels are used; adaptive logic may influence people.

**Mechanisms:** data minimization; consent and role review; accessibility controls; anti-coercion review; human override; non-diagnostic labeling.

**Hard boundaries:** never claim therapy or diagnosis from app activity; do not manipulate vulnerable users; do not expose sensitive history by default.

**Proposed PACIFY-X owner:** `enforce-governance-controls`

## Admission requirements

- Validate behavioral need against the current PACIFY-X owner and semantic index.
- Prefer merging a mechanism into an existing owner over creating a competing control plane.
- Run negative, conflict, rollback, license, and retrieval tests.
- Keep all learned or external content candidate-only until explicit admission.

## Provenance

Sources: hyperlearning-clean-room. Everything Claude Code material is MIT licensed and preserved with attribution. HyperLearning-derived entries are clean-room mechanism abstractions only because no source license was found.
