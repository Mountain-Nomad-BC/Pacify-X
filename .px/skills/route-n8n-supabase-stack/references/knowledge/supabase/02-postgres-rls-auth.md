
# Supabase Postgres, RLS, and Auth

Every Supabase project is a real Postgres database. Use constraints for invariants, migrations for change, and indexes based on measured queries.

RLS is the authorization boundary for client-accessible tables:
- enable it intentionally;
- deny by default;
- write operation-specific policies;
- test anonymous, authenticated, cross-tenant, revoked, and service paths;
- index policy predicates;
- harden security-definer functions and search paths.

The public/publishable key identifies the project; it is not authorization. User JWT plus RLS provides user-scoped authorization. Service-role keys bypass RLS and belong only in narrow trusted server contexts.

Authentication establishes identity. Authorization remains in RLS and trusted server logic. Validate redirect URLs, SSR session handling, provider configuration, recovery/deletion, and abuse controls.
