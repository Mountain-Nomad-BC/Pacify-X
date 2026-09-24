# Privacy

This document describes the **actual behaviour of the released build**, verified by evidence
rather than asserted. Where a behaviour has not been proven, it is marked as such.

PACIFY-X is local-first. It is a control plane that runs on your machine. It does not operate a
service that receives your data.

**No compliance certification is claimed.** PACIFY-X is not represented as GDPR-compliant,
CCPA-compliant, HIPAA-compliant, or compliant with any other framework. This document records
what the software does so that you — or your organisation — can make your own determination for
your deployment.

---

## 1. What stays on your machine

Everything, by default.

| Data category | Where it lives | Leaves your machine? |
|---|---|---|
| Source code / workspace content | your repository | **no** |
| Prompts and model outputs | your machine | only to a provider *you* configure (see §3) |
| Persistent memory | local custody store | **no** |
| Knowledge and indexes | local custody store | **no** |
| Operational logs, traces, diagnostics | your machine | **no** |
| Certification and audit evidence | your machine | **no** |
| Credentials | OS credential storage | **no** — never written to the repository |
| Model files (GGUF) | local custody store | **no** |

**Evidence (proven):** a static scan of every authored source and configuration file finds no
PACIFY-X-operated remote endpoint. The only network hosts referenced are loopback addresses,
schema namespaces (`json-schema.org`, `www.w3.org`, `slsa.dev` — identifiers, not destinations),
the project's own repository URL, and Marketplace metadata.

**Scope of that evidence:** static analysis of the source tree. A live network trace of a running
session is part of the adversarial audit and is recorded separately.

---

## 2. What is not collected

PACIFY-X does **not** collect:

- telemetry (see [TELEMETRY.md](TELEMETRY.md));
- crash reports sent to a PACIFY-X-operated endpoint;
- analytics;
- usage or feature statistics;
- licence or activation checks;
- update checks against a PACIFY-X-operated endpoint;
- your prompts, outputs, memory, knowledge, filenames, paths, repository names, or secrets.

**Evidence (proven):** no production telemetry emitter exists in the runtime or in the
extension. This is enforced by a machine-verifiable release invariant
(`no-production-remote-telemetry` in `policies/release-invariants.json`) and by a guard that runs
on every extension check.

---

## 3. External model providers — a separate boundary

The one place your data can leave your machine is a **provider you explicitly configure**.

If you configure OpenAI, Anthropic, OpenRouter, NVIDIA, a self-hosted endpoint, or any other
external provider, then the content you send to it leaves your machine and is governed by
**that provider's** terms, retention policy, and training policy — not by PACIFY-X.

This distinction matters and is deliberate:

> Data you intentionally send to a provider you configured is **not** PACIFY-X-operated
> collection. It is your use of a third-party service.

PACIFY-X therefore:

- ships with provider adapters **denied by default**;
- never silently falls back to a remote provider when a local model fails
  (invariant `no-hidden-cloud-fallback`);
- requires explicit configuration and authorisation before a provider is used
  (invariant `explicit-provider-use-only`);
- never stores provider credentials in the repository — they live in host secret storage.

Per-provider data handling facts you must confirm yourself are catalogued in
[PROVIDER_DATA_HANDLING.md](PROVIDER_DATA_HANDLING.md). PACIFY-X does not assert a provider's
retention or training behaviour on the provider's behalf.

---

## 4. Persistent memory — the one place to be deliberate

Persistent memory is the feature most likely to accumulate information about *you* rather than
about your code. It is:

- **optional** and off unless you enable it;
- **local** by default;
- **scoped**, so one project's memory does not leak into another;
- **inspectable and exportable**.

Because memory can turn ordinary technical work into a long-lived personal data store, its
boundaries are documented separately and in more detail in
[MEMORY_PRIVACY_MODEL.md](MEMORY_PRIVACY_MODEL.md).

If you enable memory on a machine you share, or on a project containing personal data, the
retention and access questions are yours to decide. The defaults are conservative; the controls
are described in the memory document.

---

## 5. Credentials

- Provider credentials live in your operating system's credential storage.
- PACIFY-X does not write credentials into the repository, into configuration files, into
  events, or into the webview.
- The repository is scanned for shipped credential literals before release; finding one is a
  release-blocking defect (invariant `no-shipped-secrets`).

---

## 6. Retention and deletion

See [DATA_RETENTION_AND_DELETION.md](DATA_RETENTION_AND_DELETION.md). In summary: you control
your data because it is on your machine. Deleting a project's custody store removes that
project's memory, knowledge, and evidence. Some records are deliberately append-only for
auditability, and their semantics are documented there.

---

## 7. Machine-specific information in the repository

PACIFY-X ships with **no** developer- or user-specific absolute paths and no personal
identifiers. Portability is a release invariant (`no-machine-specific-paths-or-pii`) enforced by
a repo-wide scan.

---

## 8. What would change this document

This document describes the 0.9.x core. It would need revision — before release, not after — if:

- any PACIFY-X-operated endpoint were introduced;
- production telemetry were introduced;
- any hosted service (accounts, hosted memory, managed routing, teams, cloud sync) were offered.

Each of those is a formal reclassification trigger recorded in
`policies/release-invariants.json`, and each requires an updated applicability review. None of
them applies to the current release.

---

## 9. Questions and contact

Privacy questions: `bjc274@gmail.com`.

Security issues: see [SECURITY.md](SECURITY.md) — do not open a public issue for a
vulnerability.