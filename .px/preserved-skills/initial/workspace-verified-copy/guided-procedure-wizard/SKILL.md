---
name: guided-procedure-wizard
description: Generate a resumable human-guided procedure for setup, migration, or other manual state transitions.
---

# Guided Procedure Wizard

Model the procedure as a state machine. Each step has prerequisites, instructions, expected evidence, validation, rollback, retry policy, and persisted completion state.

Secrets must be entered into approved secret stores or environment files excluded from version control; never echo or log values. The wizard may open documentation URLs but must not claim completion until evidence validates the state transition.

Support resume, dry-run, non-destructive cancellation, and a final receipt.
