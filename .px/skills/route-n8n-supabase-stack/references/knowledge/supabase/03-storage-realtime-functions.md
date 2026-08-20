
# Supabase Storage, Realtime, and Edge Functions

## Storage
Use object RLS, explicit ownership, signed URLs for bounded private access, file size/type/content validation, resumable uploads when needed, and orphan cleanup. A public bucket is a publishing decision, not a policy shortcut.

## Realtime
Choose database changes, broadcast, or presence intentionally. Realtime is not a durable transaction log or queue. On reconnect, reconcile against durable Postgres state. Scope channels, filters, and authorization.

## Edge Functions
Use functions for bounded server-side work, webhook verification, and provider calls. Validate authentication and input, keep secrets server-side, set CORS intentionally, bound timeouts/retries, make side effects idempotent, and use Postgres transactions/functions for atomic data invariants.
