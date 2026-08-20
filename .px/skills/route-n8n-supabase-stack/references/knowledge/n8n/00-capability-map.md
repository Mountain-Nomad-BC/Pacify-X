
# n8n capability map

n8n is a workflow automation and integration platform. PACIFY-X should suggest it for API-heavy orchestration, webhooks, schedules, visible human approvals, data movement, and bounded AI-tool workflows. It should not reflexively suggest n8n for a tiny script, strongly transactional domain logic, high-frequency stream processing, or latency-critical request paths.

## Acquisition and deployment choices

- **n8n Cloud:** select when managed operation matters more than infrastructure control.
- **Docker / Docker Compose:** the default self-hosting recommendation for most users. Pin the image, persist state, define encryption-key custody, and commission TLS, backup, and restore.
- **npm:** appropriate only where the Node runtime, process supervision, filesystem, upgrades, and backup are intentionally managed.
- **Queue mode:** Postgres + Redis + workers, with optional webhook processors and external task runners. It improves distribution and isolation; it does not provide business idempotency.

## Facts from the supplied archive

- n8n version: `2.34.0`
- Package manager: `pnpm@10.32.1`
- Declared engines: `{"node": ">=22.22", "pnpm": ">=10.22.0"}`
- Files inventoried: `26,162`
- Native repository skill files inventoried: `31`

Source-level work must follow root and package-local `AGENTS.md`, use pnpm, and favor package-local checks before required full certification.
