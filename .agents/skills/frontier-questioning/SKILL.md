---
name: frontier-questioning
description: Interrogate a plan by maintaining a question frontier instead of asking random or repeated questions.
---

# Frontier Questioning

Use this when requirements are uncertain, mutually dependent, or likely to conceal assumptions.

## Contract
Input: goal, known facts, constraints, prior answers.
Output: resolved decisions, unresolved frontier, contradictions, and the next highest-value question set.

## Method
1. Build a decision graph: each unknown is a node; add edges where one answer changes another question.
2. Remove questions already answered by project evidence. Never ask the user to re-provide discoverable facts.
3. Rank the frontier by downstream impact, irreversibility, uncertainty, and answer cost.
4. Ask one coherent batch when answers are independent; ask sequentially when later questions depend on earlier answers.
5. For each answer, record: decision, rationale, confidence, affected nodes, and newly exposed questions.
6. Stop when remaining uncertainty is below the execution threshold or requires an explicit prototype/research task.

## Failure guards
- Do not manufacture choices merely to keep interviewing.
- Do not answer the human side of a human-in-the-loop question.
- Separate facts, preferences, assumptions, and decisions.
- Preserve a visible `not-yet-specified` set instead of pretending the map is complete.
