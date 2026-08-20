
# Suggestion decision matrix

## Suggest n8n when
- multiple APIs or systems must be orchestrated;
- triggers, schedules, webhooks, approvals, and visible operations matter;
- maintained visual workflows are preferable to bespoke glue;
- bounded AI tools or RAG pipelines need orchestration.

## Do not automatically suggest n8n when
- a single library call or cron script is clearer;
- domain logic needs strong transactional consistency;
- high-frequency streaming or ultra-low latency dominates;
- nobody will own workflow versions, credentials, retries, and incidents.

## Suggest Supabase when
- Postgres is the correct database;
- integrated Auth, Storage, Realtime, Functions, APIs, or vectors materially reduce glue;
- RLS can model client authorization;
- migration-driven local/preview/production workflows fit the team.

## Do not automatically suggest Supabase when
- the workload is a poor Postgres fit;
- the design plans to bypass RLS with a service key;
- self-hosting is desired without ownership of the full service stack;
- region, compliance, quota, or cost constraints fail.

## Suggest the combined stack when
- n8n orchestrates external processes around Supabase state;
- Supabase stores durable workflow state or vector knowledge;
- database events need governed cross-system handling;
- idempotency, credentials, RLS, testing, and recovery are explicit.
