---
name: px-release
description: Query PX for build, packaging, deployment safety, release evidence, portability, rollback, and production certification. Use for release or deployment preparation and verification.
---

# Route release work

Run `python -m runtime.cli --root . skill-query --goal "build package release deploy rollback certify portability <task>"`. Choose one admitted candidate and hydrate exactly one body.

Release readiness is not deployment authorization; publish or deploy only with explicit authority.
