
# n8n + Supabase architecture

Use n8n as the orchestration plane and Supabase/Postgres as the durable data and authorization plane.

Integration choices:
- built-in n8n Supabase node for supported row CRUD;
- HTTP Request for unsupported Data API or RPC operations;
- Postgres access for trusted server-side SQL and transactions;
- database webhook or Edge Function to notify n8n;
- outbox or queue for delivery-critical cross-system events;
- Supabase Vector Store for n8n RAG retrieval.

Keep user-facing data access user-scoped and RLS-governed. Use service-role credentials only in narrow trusted workflows. n8n access control does not replace database RLS.

Cross-system work is not one transaction. Use idempotency records, unique constraints, outbox/inbox patterns, retry classification, compensations, and reconciliation.
