# Runtime contract

## Activation order

Validate configuration and registry, navigate compact metadata, validate inputs, authorize effects, then resolve exactly one handler. Never resolve a handler to decide whether it is allowed.

## Execution envelope

Declare capability ID, effects, timeout, tool-call budget, and postconditions. Non-read effects require a policy approval ID and idempotency key. Capability effects must be a subset of both its manifest and the policy decision.

## Lifecycle

Checkpoint registry validation, selection, authorization, activation, execution, evidence assembly, and verification. Release the handler and task-specific context at the step boundary. A retry must be sequential, within budget, and supported by evidence not present in the preceding failed attempt.

## Completion

Distinguish `completed`, `blocked`, `failed`, and `incomplete`. A successful tool call is not completion. Require current task-scoped evidence for each material claim and passing postconditions.
