---
name: px-govern
description: Query PX for policy, authority, effects, contracts, admission, lifecycle, compliance, and operating-kernel governance. Use when deciding what may act, under whose authority, and with which evidence.
---

# Route governance work

Run `python -m runtime.cli --root . skill-query --goal "govern policy authority effects contracts admission lifecycle <task>"`. Select one admitted candidate from the bounded metadata result and hydrate exactly one.

Keep Codex-host approval, PX policy, repository claims, and executor ownership distinct; the strictest applicable denial wins.
