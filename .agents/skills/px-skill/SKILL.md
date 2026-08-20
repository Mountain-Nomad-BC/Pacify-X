---
name: px-skill
description: Route skill creation, admission, packaging, catalog maintenance, provenance, backup, adaptation, and retirement work through the PX-native broker. Use for any task about skills themselves.
---

# Route skill lifecycle work

Run `python -m runtime.cli --root . skill-query --goal "skill creation admission packaging provenance backup adaptation <task>"`. Choose one admitted candidate from the maximum three returned, then hydrate exactly that ID with `skill-hydrate`.

Keep preserved originals immutable and recoverable. Treat adaptation as a new provenance-bound candidate; never overwrite or auto-purge a preserved skill. Nonstandard domains require explicit intent and a matching PX grant.
