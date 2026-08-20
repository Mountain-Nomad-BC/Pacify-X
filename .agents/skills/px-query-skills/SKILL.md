---
name: px-query-skills
description: Query the PX-native skill broker semantically or by exact ID, return at most three eligible metadata candidates, and hydrate exactly one selected body. Use as the primary entry point whenever detailed PX capability guidance may help.
---

# Query PX skills

1. Run `python -m runtime.cli --root . skill-query --goal "<task>"` or add `--skill-id <id>` for exact selection.
2. Inspect no more than the returned three metadata candidates and their rationale; do not scan `.px/skills` directly.
3. Select one admitted candidate, then run `python -m runtime.cli --root . skill-hydrate --skill <id>`.
4. Follow the hydrated body and load resources only when it directs you to them.

Default to `px-standard`. Never add Microsoft/vendor, enterprise-restricted, user-preserved, or unadmitted grants yourself. Use another domain only when the user explicitly asks for it and PX policy supplies the matching grant. Catalog visibility is not execution authority.
