# R10 portable audit bundle

Builds require explicit labeled inputs, output paths, and a machine-readable
prerequisite report. No developer-machine path is embedded in the manifest.

```powershell
python scripts/portable_audit_bundle.py build `
  --input engine-evidence=C:\path\to\engine-evidence `
  --input extension-evidence=C:\path\to\extension-evidence `
  --prerequisites C:\path\to\readiness.json `
  --output-zip C:\delivery\px-audit.zip `
  --checksum C:\delivery\px-audit.zip.sha256
```

An optional `--attestation` JSON document is included and hash-bound. Independent
verification needs only the ZIP and its separately delivered checksum:

```powershell
python scripts/portable_audit_bundle.py verify `
  --bundle C:\delivery\px-audit.zip `
  --checksum C:\delivery\px-audit.zip.sha256
```

Verification checks the external ZIP digest, path safety, duplicate members,
manifest membership, every payload digest and size, prerequisite identity, and
the optional attestation identity.

