# R01 certification bootstrap

R01 provides a parameterized, read-only readiness gate for the exact-artifact
certification lanes. It distinguishes an incomplete audit machine from a PX
product failure before unit, browser, or installed-VSIX tests begin.

## Command

From a Pacify-X engine checkout:

```powershell
python scripts/bootstrap_certification.py `
  --engine-root C:\path\to\Pacify-X `
  --extension-root C:\path\to\Pacify-X_Extension
```

The equivalent installed control-plane command is:

```powershell
python -m runtime.cli --root C:\path\to\Pacify-X release readiness `
  --extension-root C:\path\to\Pacify-X_Extension
```

Every root and executable is parameterized. Optional `--python`, `--node`,
`--npm`, `--browser`, and `--vscode` arguments select exact executables. There
are no developer-machine path defaults.

## Contract and exit behavior

The command prints `px.certification-readiness/1.0`, validated by
`contracts/certification-readiness.schema.json`. Exit zero means every required
row is `ready`. Any missing, incompatible, invalidly configured, or failed
probe produces:

```json
{
  "classification": "environment-unready",
  "valid": false
}
```

and a nonzero process exit. A missing browser or VS Code executable can never
be represented as a skipped success.

The report contains eight required rows:

- Python, checked against the engine `requires-python` declaration;
- the exact-pinned Python `build` package in the selected interpreter;
- Node, checked against every Node constraint in the extension lock;
- npm availability and its observed version;
- package-lock version, exact direct pins, and installed direct-dependency
  parity (including development dependencies such as `playwright-core`);
- a browser executable and observed version;
- VS Code, checked against `package.json`'s `engines.vscode` range; and
- the engine root plus a successful `runtime.cli validate` result.

The probe uses an allowlisted, scrubbed child-process environment, bounded
timeouts, explicit working directories, and no shell for native executables.
Windows `.cmd` launchers use only the system command processor with a resolved
executable path and fixed version arguments.

## Effects and sequencing

R01 is intentionally read-only: it performs no installation, network access,
browser launch, IDE launch, service start, or workspace mutation. If installed
Node dependencies are absent or drifted, run `npm ci` in the explicitly chosen
extension root under the separately authorized certification bootstrap, then
rerun R01. R02 owns the executable unit/E2E/certify lanes; R03 and later cards
own VSIX construction and installation. This separation prevents an install
failure from being mislabeled as a product-test failure.

The machine-readable `probe_policy` field records these effect boundaries in
every report.
