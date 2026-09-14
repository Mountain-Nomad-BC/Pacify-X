---
canonical_id: "foundrycalculation"
kind: system
layer: reasoning
currentness: changed-file
runtime_observed: false
certified: false
---
# Calculation AST and dimensional compiler

[[Layers/reasoning]] · [[Views/Full_Architecture]]

## Purpose

Checks restricted arithmetic AST and dimensions then emits Python/JavaScript/schema with formula-engine source hash.

## Historical source state

Generated raw functions and separate bounded Python interpreter.

## Limits and unknowns

Dimensional compatibility is not unit conversion; generated functions omit interpreter runtime guards.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2308]] — changed-file
- [[Evidence/S2310]] — changed-file

## Directed relationships

- [[Systems/foundrybundleidentity]] — adds generated code for parse-only certification (`E686`)
- [[Systems/formulaadmission]] — uses dimension checker without registering formula (`E687`)
- [[Systems/foundrylineage]] — hits calculation field mismatch during export (`E690`)
