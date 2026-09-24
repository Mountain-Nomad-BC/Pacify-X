# Third-Party Notices

PACIFY-X redistributes third-party software under the licences below. This file lists
**redistributed** components. Components that the runtime can *use* or *download independently*
are listed separately in §3, because they are not redistributed by PACIFY-X.

This inventory is generated from the actual dependency manifests in the repository:
`pyproject.toml`, `extension/package.json`, and the vendored/embedded assets under
`runtime/`, `scripts/`, and `extension/`.

---

## 1. Python runtime dependencies (redistributed as installed packages, not vendored)

| Component | Version (pinned) | Licence | Source |
|---|---|
| PyYAML | 6.0.3 | MIT | https://github.com/yaml/pyyaml |

PACIFY-X requires **no other Python runtime dependency** for core operation.

## 2. Build and test dependencies (not shipped to users)

| Component | Version (pinned) | Licence | Used for | Source |
|---|---|---|
| setuptools | 84.0.0 | MIT | build backend | https://github.com/pypa/setuptools |

## 3. VS Code extension dependencies

### 3.1 Bundled into the extension (redistributed)

| Component | Version (pinned) | Licence | Source |
|---|---|
| `@modelcontextprotocol/server` | 2.0.0 | MIT | https://github.com/modelcontextprotocol/servers |
| zod | 4.4.3 | MIT | https://github.com/colinhacks/zod |

### 3.2 Development-only (not shipped in the VSIX)

| Component | Version (pinned) | Licence | Source |
|---|---|
| `@vscode/test-electron` | 3.1.0 | MIT | https://github.com/microsoft/vscode-test |
| esbuild | 0.28.2 | MIT | https://github.com/evanw/esbuild |
| playwright-core | 1.62.1 | Apache-2.0 | https://github.com/microsoft/playwright |

## 4. Embeddable Python runtime shipped inside the VSIX

The extension ships a self-contained Python runtime so it can run without a system Python
install. That runtime is redistributed under its own licence:

| Component | Licence | Notes |
|---|---|---|
| Python | PSF License Agreement | The embeddable distribution's own licence text is preserved unchanged. |

The `PSF` licence and any bundled Python component licences are preserved with the shipped
runtime bytes.

## 5. Host platform components (provided by the host, not redistributed)

| Component | Relationship |
|---|---|
| Visual Studio Code | a host platform the extension runs inside; not redistributed |
| Windows / Linux | operating-system components; not redistributed |

## 6. Not redistributed by PACIFY-X — independently obtained

These are **not** shipped with PACIFY-X. The runtime can *use* them when the operator obtains
them, and their own licences govern them.

| Component | Relationship | Licensing note |
|---|---|---|
| llama.cpp / ggml | **built locally** from upstream source by `scripts/px_build_llama_cuda.ps1` (explicit, approval-gated clone). The resulting binaries live in local runtime custody, not in the repository. | MIT — see upstream `LICENSE` in the built tree |
| CUDA runtime | installed by the operator from NVIDIA | NVIDIA EULA governs the operator's installation |
| GGUF model weights | supplied by the operator; **never auto-downloaded** | each model has its own licence — see [MODEL_AND_DATA_LICENSES.md](MODEL_AND_DATA_LICENSES.md) |
| Ollama | optional, if installed by the operator | upstream licence governs |
| Any external model provider SDK/API | configured by the operator | that vendor's terms govern |

**Important:** the Apache-2.0 licence of PACIFY-X does **not** extend to any item in this section.

## 7. Assets in this repository

Icons, logos, and documentation images under `docs/assets/` and `extension/media/` are part of
this project and covered by the project licence, except where a file states otherwise.

## 8. Attribution preservation

Where an upstream licence requires its notice to survive redistribution, that notice is preserved
unchanged in this repository and in the packaged extension. Removing or altering those notices is
not permitted by the applicable upstream licences.

## 9. Verifying this inventory

```powershell
# Python dependencies
Select-String -Path pyproject.toml -Pattern "dependencies"

# Extension dependencies
Get-Content extension/package.json | Select-String -Pattern "dependencies"

# Bundled Python runtime
Get-ChildItem extension -Recurse -Filter "PYTHON_LICENSE*" | Select-Object FullName
```

This section is intentionally verifiable rather than asserted: if the manifests change and this
file does not, that is a defect. The release compliance gate checks that this inventory is
present and consistent with the manifests (see `docs/compliance/RELEASE_COMPLIANCE_CHECKLIST.md`).

## 10. Reporting a licensing concern

If you believe a component is licensed incorrectly or requires attribution not present here,
contact `bjc274@gmail.com`.