# PX NSAI Knowledge Library

This directory is a governed source library for normalized knowledge objects.

## Non-negotiable storage rule

Every knowledge item or formula is stored as **one pretty-printed UTF-8 JSON object in one `.json` file** under `objects/<namespace>/<slug>.json`.

There are no JSONL shards, chunk files, array-of-objects authority files, or embedded-vector authority files. An object's semantic ID has the form `nsai:<namespace>:<object_type>:<slug>` and its path is derived from that identity as `objects/<namespace>/<slug>.json`.

`index.json` is navigation only. It is rebuilt from the individual object files and can be deleted without losing authoritative knowledge content.

## Status

`draft` and `candidate` are unpromoted inputs. `validated` means the object's evidence/contract checks have passed the applicable PX validation process. `authoritative` is reserved for a separate governed promotion decision. `deprecated` and `rejected` remain addressable for lineage and negative-result preservation.

A status label does not grant execution, tool, memory-write, routing, learning-promotion, or policy authority. Every object carries `authority_granted: false`.

## Provenance

Every object must retain one or more source records with stable source ID, source kind, exact relative source path, and SHA-256. Archive/version/license/citation fields are retained when known. Claims carry evidence references; relationships use stable NSAI object IDs rather than filename inference.

## Formulas

Formula objects use `object_type: "formula"` and the dedicated formula contract. They preserve both verbatim and normalized expressions, variables, units/dimensions, parameters/constants, assumptions, constraints, time basis, dynamics, determinism, and linearity. Similar-looking symbols are not merged merely because their names resemble one another.

## Validation and regeneration

From the repository root:

```text
python scripts/validate_nsai_knowledge.py --root .
python scripts/build_nsai_index.py --root . --check
python scripts/build_nsai_index.py --root .
```

The validator reads individual object files directly. The index builder produces deterministic bytes: two builds over identical object bytes must produce identical `index.json` bytes.
