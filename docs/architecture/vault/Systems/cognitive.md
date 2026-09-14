---
canonical_id: "cognitive"
kind: system
layer: reasoning
currentness: changed-file
runtime_observed: false
certified: false
---
# Deterministic cognitive reasoning

[[Layers/reasoning]] · [[Views/Full_Architecture]]

## Purpose

Exposes bounded logic, constraints, Bayesian hypotheses, causal/temporal analysis, formula evaluation and strategy selection.

## Historical source state

Explicit reasoning payload, result and input/result hashes.

## Limits and unknowns

These are read-only analytical operations over supplied inputs, not a persistent self-directed reasoning agent.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1886]] — changed-file
- [[Evidence/S1883]] — changed-file
- [[Evidence/S1875]] — changed-file
- [[Evidence/S1865]] — same-file-bytes

## Directed relationships

- [[Systems/analogy]] — dispatches structural comparison (`E071`)
- [[Systems/logic]] — dispatches bounded reasoning kernels (`E124`)
- [[Systems/formula]] — dispatches formula operations (`E125`)
- [[Systems/belief]] — dispatches scoped belief revision (`E129`)
- [[Systems/strategy]] — dispatches reasoning strategy selection (`E130`)
- [[Systems/abduction]] — dispatches abductive explanation search (`E131`)
- [[Systems/decision]] — dispatches tradeoff and robust decision analysis (`E132`)
- [[Systems/voi]] — dispatches experiment value of information (`E133`)
- [[Systems/constraints]] — dispatches bounded constraint search (`E134`)
- [[Systems/temporal]] — dispatches temporal consistency analysis (`E135`)
- [[Systems/formulauncertainty]] — wraps result and selected errors in read-only facade (`E695`)
- [[Systems/logicforward]] — dispatches explicit supplied reasoning payload (`E696`)
- [[Systems/abductiveportfolio]] — dispatches explicit supplied reasoning payload (`E697`)
- [[Systems/bayesianupdates]] — dispatches explicit supplied reasoning payload (`E698`)
- [[Systems/informationvalue]] — dispatches explicit supplied reasoning payload (`E699`)
- [[Systems/constraintsearch]] — dispatches explicit supplied reasoning payload (`E700`)
- [[Systems/causalgraph]] — dispatches explicit supplied reasoning payload (`E701`)
- [[Systems/temporalanalysis]] — dispatches explicit supplied reasoning payload (`E702`)
- [[Systems/decisionintervals]] — dispatches explicit supplied reasoning payload (`E703`)
- [[Systems/beliefprojection]] — dispatches explicit supplied reasoning payload (`E704`)
- [[Systems/analogysignature]] — dispatches explicit supplied reasoning payload (`E705`)
- [[Systems/strategymodes]] — dispatches explicit supplied reasoning payload (`E706`)
