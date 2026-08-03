# Orchestration

Operate through compact metadata and hydrate only the selected capability.

## Loop

Validate → inspect project state → classify goal → select at most three metadata candidates → hydrate one skill → declare effects → obtain approval when required → execute → verify → checkpoint → release context.

## Commands

`engineering-bootstrap validate`  
`engineering-bootstrap startup --project .`  
`engineering-bootstrap working-set --goal "<goal>"`  
`engineering-bootstrap hydrate --skill <selected-id>`

## Stop conditions

Stop on unknown mutation, secret exposure, project-root ambiguity, unresolved high-risk assumptions, registry failure, or unverifiable completion.
