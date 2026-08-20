
# Supabase CLI, local development, and environments

Install the CLI either:
- as a pinned project development dependency, invoked through npm, pnpm, yarn, or bun; or
- globally through a supported OS package channel such as Homebrew, Scoop, or Linux packages.

The npm route is project-local; it does not create a normal global `supabase` command. The npm-run CLI requires Node 20 or later. Local Supabase requires a compatible container runtime.

Core sequence:
1. initialize the project;
2. commit the generated `supabase/` directory;
3. start local services;
4. create migrations, seeds, functions, and tests;
5. reset from a clean state to prove reproducibility;
6. explicitly link and verify a remote project before deployment.

Keep local, preview, staging, and production project refs, credentials, callback URLs, and data separate. Never rely on remembered CLI linkage.
