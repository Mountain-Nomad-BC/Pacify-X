# Pacify-X Local AI Install Prompt (for the installing AI assistant)

You are the AI assistant commissioning Pacify-X on this machine. Read this whole file before
taking any action, then work the phases in order. Use `START_HERE_FOR_AI.md` and `AGENTS.md`
for the repository's own authority rules; this file only adds the **local AI stack** phases.

## Non-negotiable rules

1. **Never perform an effect the user has not approved.** Every step below is marked
   `READ-ONLY` or `NEEDS APPROVAL`.
2. **Never download a model, install a runtime, or enable a provider on your own initiative.**
   Those are `NEEDS APPROVAL` steps with named owners.
3. **Do not fabricate capability.** If a discovery step finds nothing, say so and stop that
   branch. Missing facts stay missing; report them as unknown.
4. **Do not edit generated artifacts to make a check pass.** Find the canonical builder and
   change the input.
5. **Keep every path relative to the repository root** in anything you write into the repo.

---

## Phase 0 — Read the machine (READ-ONLY)

Run:

```powershell
python scripts/px_install.py --non-interactive
```

This prints discovered facts (OS, Python, Git/Node/VS Code, GPU, VRAM, RAM, disk, whether the
canonical local runtime is built, which GGUF models are present) and an **ordered plan** with
the recommended profile. Read it before doing anything else.

If it reports `missing-prerequisite` (no Git or no `ssh-keygen`), stop and tell the user
exactly what is missing. Do not install it yourself.

---

## Phase 1 — Ask the user the model decisions (NEEDS APPROVAL)

Pacify-X does not ship a model. Ask the user these questions **before** any download, and
present the trade-offs honestly. Suggested script:

> Three decisions shape your local AI stack. Pacify-X runs no local model until you choose.

### Decision 1 — Which profile?

| Profile | What you get | Needs | Disk |
|---|---|---|---|
| **minimal** | Deterministic PX only. No local model. | nothing extra | ~2 GB |
| **librarian-only** | One resident CPU-first librarian (retrieval, classification, PX upkeep) | 24 GB RAM | ~8 GB |
| **workstation** *(recommended when a GPU is present)* | Resident librarian **plus** an on-demand local deep worker under an exclusive lease | GPU ≥ 6 GB VRAM, 24 GB RAM | ~30 GB |
| **hybrid-escalation** | The above plus a policy-gated remote provider slot | credentials + spend policy | ~30 GB |

The installer already suggests one from measured facts; confirm or override.

### Decision 2 — Which models fill the lanes?

Use the roles, not model names. The registry is capability-based, so a swap should not require
re-architecting anything.

- **resident librarian** — small, fast, CPU-first, stays loaded. Must handle bounded
  structured output reliably. A thinking-mode model must be configured with thinking disabled
  for bounded calls, or given a token budget that accommodates it.
- **on-demand usage worker (deep)** — larger MoE-class model, loaded only when a task needs it,
  held under an exclusive lease, never autoloaded.

For each: agree on source repository, immutable revision, exact GGUF filename, quantization,
and expected size. Record the SHA-256 after download — the model identity is the hash, never
the filename.

### Decision 3 — Any external provider?

If the user wants frontier escalation, agree which provider, confirm the credential will live
in host secret storage (never in the repository), and set the spend/privacy policy. Pacify-X
must deny privacy-sensitive requests remote routing.

**Stop here until the user answers.** Then record their choices.

---

## Phase 2 — Reconcile the engine (READ-ONLY, then safe write)

```powershell
python -m runtime.cli validate
python scripts/reconcile_capability_map.py --root . --apply
python -m runtime.cli validate
```

`reconcile_capability_map.py` derives the capability surface from the admission ledger and the
skill catalogue. It only emits capabilities whose ledger record already says `active`; it never
invents an admission. After it runs, rebuild the dependent projections in dependency order:

```powershell
python scripts/build_registry_graphs.py --root .
python scripts/build_provider_route_index.py --root .
python scripts/build_semantic_capability_index.py --root .
python scripts/build_registry_envelope_inventory.py --root .
```

Then reconcile the graph authority manifest and rewrite world state (see the campaign notes for
the exact two calls). Confirm `validate_registry` reports `valid: True` with a large
`active_count` before continuing.

---

## Phase 3 — Build the canonical runtime (NEEDS APPROVAL)

Only for the librarian/deep lanes. This compiles llama.cpp with CUDA and is long.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\px_build_llama_cuda.ps1
```

Requirements you must verify first and report if absent: CMake, an MSVC toolset, the **Windows
SDK** (it supplies `rc.exe`, `mt.exe` and the import libraries — a missing SDK is the most
common failure), and the CUDA toolkit. The script discovers VS via `vswhere` and CUDA via
`CUDA_PATH`; you may override with `-VisualStudioRoot` and `-CudaRootParam`.

Done when `~/.px/runtime-lock.json` exists and its `server_path` runs `--version` and
`--list-devices` shows the GPU. `scripts/px_install.py` will then report
`local_runtime_built: true`.

---

## Phase 4 — Acquire and admit the models (NEEDS APPROVAL)

For each agreed model:

1. download to staging, verifying size and resuming if interrupted;
2. verify the GGUF header and architecture;
3. compute the SHA-256;
4. move it atomically into the canonical custody root `.pacify-x/models/<model-id>/`;
5. record `artifact_sha256` in `models/model-portfolio.json` and confirm the runtime profile.

Then prove it loads through the governed runtime, not by hand:

```powershell
python -m runtime.cli model-runtime status
```

---

## Phase 5 — Calibrate placement (READ-ONLY measurement)

Do not hardcode GPU layers. Measure a bounded candidate set and let the resource planner choose:

```powershell
python scripts/benchmark_local_models.py --help
```

Record the measurements as evidence. Expect the result to be machine-specific; on a small-VRAM
GPU a naive partial offload can be **slower** than CPU-only, and full offload of a MoE model
with few active parameters can be the fastest option. Report what you measured.

---

## Phase 6 — Package and install the extension (NEEDS APPROVAL)

```powershell
cd extension
npm ci --ignore-scripts
npm run check
npm run test:unit
npm run package
```

Then install the produced VSIX. Done when the **PX Agent Console** appears in the VS Code
right-hand sidebar and answers one real local turn through PX's provider gateway (the response
must carry an exact provider receipt — a bare text answer is not proof).

---

## Phase 7 — Prove one operational turn (READ-ONLY)

```powershell
python -m runtime.vscode_model_bridge chat --engine-root . --project-root .
```

Feed it a bounded request on stdin. Success is a streamed answer **plus** a receipt envelope.
If the engine is unavailable, the correct behaviour is a typed failure — never a substituted
answer. Record the evidence.

---

## Reporting back

Give the user a short closing status covering: the chosen profile, each model's hash and
runtime build, the measured placement, what is operational, and **anything that is declared but
not yet proven**. Do not describe a capability as working when only its files exist.

## If something blocks you

State exactly: the step, the command, the full error, the root cause if known, the evidence,
and the single next action. Do not work around a governance gate by editing state, and do not
retry a failing certification in a loop.