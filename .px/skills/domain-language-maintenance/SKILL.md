---
name: domain-language-maintenance
description: Maintain a canonical project vocabulary and challenge ambiguous or overloaded terms during work.
---

# Domain Language Maintenance

Treat project language as executable architecture metadata, not decorative documentation.

## Procedure
1. Extract candidate terms from conversations, code identifiers, schemas, tickets, manuals, and UI labels.
2. For each term record: canonical name, definition, aliases, rejected meanings, examples, owner domain, source, and validity scope.
3. Detect collisions: one term with multiple meanings, multiple terms for one concept, or code vocabulary that disagrees with domain vocabulary.
4. Resolve collisions with the domain owner; never silently pick the most common string.
5. Propagate approved terms into maps, skills, retrieval aliases, contracts, and new code. Existing code changes require a scoped migration plan.
6. Link major terminology decisions to an ADR.

## Retrieval behavior
Expand queries through approved aliases but return the canonical term. Rank exact domain matches above generic lexical similarity.
