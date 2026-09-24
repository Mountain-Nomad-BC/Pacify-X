# Secure Update Policy

How Pacify-X artifacts are identified, distributed, verified, and revoked.

---

## 1. What is released

Distinct artifacts with distinct identities:

| Artifact | Channel | Identity |
|---|---|---|
| Source | GitHub repository + release tag | exact commit SHA + tag |
| Python package | repository / published wheel | filename + SHA-256 |
| VS Code extension | VSIX (+ Marketplace when published) | VSIX SHA-256 + extension version |
| Local model runtime | **not distributed** — built locally by the operator | executable SHA-256 in the runtime lock |
| Model weights | **not distributed** | per-model SHA-256 recorded at admission |

## 2. Signature and checksum verification

- Released assets publish **SHA-256 checksums**; verify them before use.
- A tool that installs an artifact must **verify before install**. The extension installer
  (`extension/Install-PacifyX.ps1`) already does this: it checks the VSIX against
  `SHA256SUMS.txt` and **refuses on mismatch**.
- Signature verification uses the project's signing identity where available. `ssh-keygen` is
  required for effect-grant and release-signature verification; a missing executable is
  **reported**, never silently skipped.
- A checksum mismatch is a hard stop, not a warning.

## 3. Release identity

A release is identified as a whole, not by a version string alone:

- source commit and tag;
- source manifest digest;
- package identity;
- installed (VSIX) identity;
- runtime identity;
- model artifact hashes;
- the certification receipt that binds them.

Certification binds to the **exact frozen artifact bytes**. If the bytes change, the
certification no longer applies.

## 4. Update source

- The extension updates through the VS Code Marketplace under its published publisher identity
  (`mountain-nomad-bc`).
- Source updates through the repository.
- There is **no Pacify-X-operated update-check endpoint** (invariant
  `no-px-operated-remote-endpoints`). Pacify-X does not phone home to check for updates.

## 5. Verification before relying on a release

1. Confirm the tag and the exact commit.
2. Verify the artifact checksum against the published one.
3. Confirm the artifact identity in the certification receipt matches the artifact you hold.
4. Confirm the supported platform matches yours.
5. Confirm the release is not listed as revoked.

If any step fails, do not rely on that artifact.

## 6. Rollback

- Previous releases remain available so you can return to a known state.
- Rollback is a deliberate reinstall of an earlier verified artifact; it is not silent.
- Superseding a release **marks** it; it never rewrites its history. The prior record is
  preserved so the change is auditable.

## 7. Key rotation

- Signing and release keys are rotated on a planned schedule and immediately on any suspicion of
  compromise.
- A rotation publishes the new identity and the date from which it applies.
- Artifacts signed by a retired key remain verifiable against the published historical key
  material so old releases do not become unverifiable.

## 8. If a release is compromised

See [INCIDENT_RESPONSE.md](INCIDENT_RESPONSE.md) for the full procedure. In outline:

1. **Contain** — stop recommending the affected version.
2. **Record** — add an additive revocation record (never edit history).
3. **Notify** — publish an advisory describing affected versions, impact, and the safe version.
4. **Remediate** — produce a fixed release through the normal verified path.
5. **Verify** — confirm the fix and publish the evidence.

A revocation is **additive**: existing evidence is preserved so the history remains auditable.
Pacify-X never silently rewrites a release.

## 9. Supported lifetime

Security updates are provided for the **current development line** and, for critical issues, the
previous certified release. Older lines are supported on a best-effort basis only. The current
line and its status are stated at the top of [SECURITY.md](../../SECURITY.md).

## 10. What Pacify-X does not do

- It does not auto-update itself without your action.
- It does not check for updates against a Pacify-X endpoint.
- It does not download or replace model weights on its own.
- It does not install a local runtime without an explicit, approval-gated build step.

## 11. Post-certification mutation is forbidden

A published artifact must equal the certified artifact. If generation, packaging, or documentation
after certification changes the bytes, the certification is invalid and the release must not be
published. This is the exact failure mode the processing order exists to prevent:
**anything that contributes to release identity is generated before the freeze, and
certification does not mutate the state it certifies.**