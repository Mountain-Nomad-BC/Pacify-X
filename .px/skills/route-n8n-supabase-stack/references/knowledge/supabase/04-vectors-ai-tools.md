
# Supabase vectors and AI tools

For pgvector:
- match the vector dimension to the embedding model;
- choose distance metric and index from measured requirements;
- preserve source, chunk, model, and ingestion lineage;
- enforce tenant authorization inside the query boundary;
- evaluate recall, latency, metadata-filter selectivity, and minimum returned rows;
- version embeddings and make re-embedding restartable.

For official Supabase MCP, agent skills, or plugin:
- inspect before installation;
- prefer project scope;
- use project restriction, read-only mode, and limited feature groups when available;
- use non-production projects with synthetic or obfuscated data;
- require human approval for SQL, migrations, functions, secrets, and destructive actions;
- treat database content and retrieved text as untrusted model context.
