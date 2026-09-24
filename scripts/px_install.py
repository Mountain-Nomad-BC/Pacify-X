"""Interactive Pacify-X first-run installer and commissioning planner.

This is the human-facing entry point. It is deliberately *decision-oriented*: it asks the few
questions a person must answer, discovers everything it can on its own, and emits a machine
readable commissioning plan that the installing AI assistant then executes.

It is non-destructive and idempotent:

* ``--dry-run`` (default)  inspects and prints the plan; writes nothing.
* ``--apply``              writes the local commissioning record under
                           ``.engineering-bootstrap/commissioning/`` (gitignored custody).

It never downloads models, never installs a runtime, and never enables a provider. It produces
the decisions and the ordered plan; the user or the installing assistant performs the effects
through the governed owners (``scripts/px_build_llama_cuda.ps1``,
``scripts/reconcile_capability_map.py``, the model portfolio, and the extension package).

Usage:
    python scripts/px_install.py                  # interactive
    python scripts/px_install.py --non-interactive --role workstation
    python scripts/px_install.py --apply
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

COMMISSIONING_DIR = ROOT / ".engineering-bootstrap" / "commissioning"
PLAN_SCHEMA = "px.commissioning-plan/1.0"

# --- Profile catalogue ------------------------------------------------------
# Each profile names the roles it fills and which checkpoints it needs. The user chooses a
# profile; PX resolves the concrete models and placement. Never hardcode a model here.

PROFILES: dict[str, dict[str, object]] = {
    "minimal": {
        "title": "Minimal (no local models)",
        "summary": "Deterministic PX only. No local model runtime, no GGUF downloads.",
        "roles": ["deterministic"],
        "requires_gpu": False,
        "approx_disk_gb": 2,
    },
    "librarian-only": {
        "title": "Librarian only (recommended first step)",
        "summary": "One resident CPU-first librarian for retrieval, classification and PX upkeep.",
        "roles": ["deterministic", "resident_librarian"],
        "requires_gpu": False,
        "approx_disk_gb": 8,
    },
    "workstation": {
        "title": "Workstation (librarian + on-demand deep worker)",
        "summary": "Resident librarian plus an on-demand local deep worker held under an exclusive lease.",
        "roles": ["deterministic", "resident_librarian", "on_demand_usage"],
        "requires_gpu": True,
        "approx_disk_gb": 30,
    },
    "hybrid-escalation": {
        "title": "Hybrid with external escalation",
        "summary": "Local lanes plus a policy-gated remote escalation slot for frontier work.",
        "roles": ["deterministic", "resident_librarian", "on_demand_usage", "remote_escalation"],
        "requires_gpu": True,
        "approx_disk_gb": 30,
    },
}


@dataclass
class EnvironmentFacts:
    """Discovered facts. Nothing here is invented; absent values stay absent."""

    os_name: str = ""
    python_version: str = ""
    git_available: bool = False
    node_available: bool = False
    code_available: bool = False
    ssh_keygen_available: bool = False
    nvidia_gpu: str | None = None
    vram_mb: int | None = None
    ram_gb: float | None = None
    disk_free_gb: float | None = None
    runtime_built: bool = False
    runtime_lock: dict[str, object] | None = None
    models_present: list[str] = field(default_factory=list)
    extension_present: bool = False

    def as_mapping(self) -> dict[str, object]:
        return {
            "os": self.os_name,
            "python_version": self.python_version,
            "git_available": self.git_available,
            "node_available": self.node_available,
            "code_available": self.code_available,
            "ssh_keygen_available": self.ssh_keygen_available,
            "nvidia_gpu": self.nvidia_gpu,
            "vram_mb": self.vram_mb,
            "ram_gb": self.ram_gb,
            "disk_free_gb": self.disk_free_gb,
            "local_runtime_built": self.runtime_built,
            "models_present": self.models_present,
            "extension_present": self.extension_present,
        }


def _which(name: str) -> bool:
    if shutil.which(name):
        return True
    # Windows tooling is frequently installed but not on the inherited PATH, and some
    # (VS Code) ship as .cmd shims rather than .exe.
    program_files = Path(os.environ.get("ProgramFiles", "C:/Program Files"))
    local_appdata = Path(os.environ.get("LOCALAPPDATA", ""))
    candidates: list[Path] = []
    for root in (program_files, local_appdata / "Programs"):
        for suffix in (".exe", ".cmd", ".bat", ""):
            candidates.append(root / "Git" / "cmd" / f"{name}{suffix}")
            candidates.append(root / "nodejs" / f"{name}{suffix}")
            candidates.append(root / "Microsoft VS Code" / "bin" / f"{name}{suffix}")
    candidates.append(
        Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32" / "OpenSSH" / f"{name}.exe"
    )
    return any(candidate.is_file() for candidate in candidates)


def _runtime_status() -> tuple[bool, dict[str, object] | None]:
    """Read the runtime lock and prove the recorded server binary is present."""

    install_root = Path(os.environ.get("PX_INSTALL_ROOT") or (Path.home() / ".px"))
    lock = install_root / "runtime-lock.json"
    if not lock.is_file():
        return False, None
    try:
        # PowerShell's `Set-Content -Encoding UTF8` writes a BOM; accept both forms.
        payload = json.loads(lock.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return False, None
    server = Path(str(payload.get("server_path", "")))
    if not server.is_file():
        # Fall back to the conventional build output before declaring failure.
        fallback = install_root / "runtime" / "llama.cpp" / "build" / "bin" / "llama-server.exe"
        if fallback.is_file():
            payload["server_path"] = str(fallback)
            server = fallback
    return server.is_file(), payload


def _gpu_facts() -> tuple[str | None, int | None]:
    import subprocess

    smi = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32" / "nvidia-smi.exe"
    if not smi.is_file():
        return None, None
    try:
        result = subprocess.run(
            [str(smi), "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=20, shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None, None
    line = (result.stdout or "").strip().splitlines()
    if not line:
        return None, None
    parts = [part.strip() for part in line[0].split(",")]
    return parts[0] if parts else None, int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None


def discover() -> EnvironmentFacts:
    """Inspect the machine. Never guesses: unavailable facts remain None/False."""

    facts = EnvironmentFacts(
        os_name=platform.platform(),
        python_version=platform.python_version(),
        git_available=_which("git"),
        node_available=_which("node"),
        code_available=_which("code"),
        ssh_keygen_available=_which("ssh-keygen"),
    )
    gpu, vram = _gpu_facts()
    facts.nvidia_gpu, facts.vram_mb = gpu, vram

    try:
        import ctypes

        class _MemoryStatusEx(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = _MemoryStatusEx()
        status.dwLength = ctypes.sizeof(_MemoryStatusEx)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            facts.ram_gb = round(status.ullTotalPhys / (1024**3), 1)
    except (OSError, AttributeError, ValueError):
        facts.ram_gb = None

    try:
        facts.disk_free_gb = round(shutil.disk_usage(ROOT).free / (1024**3), 1)
    except OSError:
        facts.disk_free_gb = None

    facts.runtime_built, facts.runtime_lock = _runtime_status()

    models_root = ROOT / ".pacify-x" / "models"
    if models_root.is_dir():
        facts.models_present = sorted(
            f"{directory.name}/{file.name}"
            for directory in models_root.iterdir()
            if directory.is_dir()
            for file in directory.glob("*.gguf")
        )
    facts.extension_present = (ROOT / "extension" / "package.json").is_file()
    return facts


def recommend_profile(facts: EnvironmentFacts) -> tuple[str, str]:
    """Recommend a profile from measured facts, with the reason stated."""

    has_gpu = bool(facts.nvidia_gpu and (facts.vram_mb or 0) >= 6000)
    enough_ram = bool(facts.ram_gb and facts.ram_gb >= 24)
    enough_disk = bool(facts.disk_free_gb and facts.disk_free_gb >= 40)
    if has_gpu and enough_ram and enough_disk and facts.runtime_built:
        return "workstation", "GPU, RAM, disk and a built runtime are all present"
    if has_gpu and enough_ram and enough_disk:
        return "workstation", "hardware is sufficient; the local runtime still needs building"
    if enough_ram and enough_disk:
        return "librarian-only", "no usable GPU found; the CPU-first librarian still fits"
    return "minimal", "insufficient measured resources for local model lanes"


def build_plan(profile: str, facts: EnvironmentFacts, *, source_revision: str | None = None) -> dict:
    """Emit the ordered commissioning plan for the chosen profile."""

    if profile not in PROFILES:
        raise SystemExit(f"unknown profile {profile!r}; choose from {sorted(PROFILES)}")
    spec = PROFILES[profile]
    roles = [str(role) for role in spec["roles"]]  # type: ignore[union-attr]

    steps: list[dict[str, object]] = [
        {
            "id": "verify-prerequisites",
            "title": "Verify prerequisites",
            "owner": "scripts/px_install.py",
            "requires_approval": False,
            "command": None,
            "done_when": "Python, Git and ssh-keygen are all available",
            "blocked_by": [] if (facts.git_available and facts.ssh_keygen_available) else ["missing-prerequisite"],
        },
        {
            "id": "validate-engine",
            "title": "Validate the Pacify-X engine checkout",
            "owner": "runtime.cli",
            "requires_approval": False,
            "command": "python -m runtime.cli validate",
            "done_when": "validate exits 0",
            "blocked_by": [],
        },
        {
            "id": "reconcile-registry",
            "title": "Reconcile the capability registry to the admitted surface",
            "owner": "scripts/reconcile_capability_map.py",
            "requires_approval": False,
            "command": "python scripts/reconcile_capability_map.py --root . --apply",
            "done_when": "validate_registry reports valid with active_count > 100",
            "blocked_by": ["validate-engine"],
        },
    ]

    if "resident_librarian" in roles or "on_demand_usage" in roles:
        steps.append({
            "id": "build-runtime",
            "title": "Build the canonical CUDA llama.cpp runtime",
            "owner": "scripts/px_build_llama_cuda.ps1",
            "requires_approval": True,
            "command": 'powershell -ExecutionPolicy Bypass -File scripts\\px_build_llama_cuda.ps1',
            "done_when": "runtime-lock.json exists and server_path is executable",
            "blocked_by": [],
            "approval_reason": "requires the Windows SDK and a long local compile",
        })
        steps.append({
            "id": "acquire-models",
            "title": "Acquire and admit the local GGUF models",
            "owner": "models/model-portfolio.json",
            "requires_approval": True,
            "command": None,
            "done_when": "each lane model has an artifact_sha256 and a loadable profile",
            "blocked_by": ["build-runtime"],
            "approval_reason": "multi-GB downloads and local model custody",
        })
        steps.append({
            "id": "calibrate-placement",
            "title": "Calibrate CPU/GPU/MoE placement from measurement",
            "owner": "scripts/benchmark_local_models.py",
            "requires_approval": False,
            "command": "python scripts/benchmark_local_models.py --help",
            "done_when": "each profile carries a validated placement and a benchmark receipt",
            "blocked_by": ["acquire-models"],
        })
        steps.append({
            "id": "start-router",
            "title": "Start the governed router pool",
            "owner": "runtime.local_model_runtime",
            "requires_approval": False,
            "command": "python -m runtime.cli model-runtime status",
            "done_when": "/health is ok and both lanes are preset-bound",
            "blocked_by": ["calibrate-placement"],
        })

    if "remote_escalation" in roles:
        steps.append({
            "id": "configure-escalation",
            "title": "Configure the policy-gated escalation provider",
            "owner": "registry/provider_adapters.json",
            "requires_approval": True,
            "command": None,
            "done_when": "the adapter is admitted and the credential is in host secret storage",
            "blocked_by": ["build-runtime"],
            "approval_reason": "external provider credentials and spend policy",
        })

    steps.append({
        "id": "install-extension",
        "title": "Package and install the VS Code extension",
        "owner": "extension/scripts/package-vsix.js",
        "requires_approval": True,
        "command": "cd extension; npm ci --ignore-scripts; npm run package; .\\Install-PacifyX.ps1",
        "done_when": "the PX Agent Console appears in the right sidebar and answers a local turn",
        "blocked_by": ["reconcile-registry"],
        "approval_reason": "installs software into the editor host",
    })
    steps.append({
        "id": "smoke-turn",
        "title": "Prove one operational chat turn",
        "owner": "runtime.vscode_model_bridge",
        "requires_approval": False,
        "command": "python -m runtime.vscode_model_bridge chat --engine-root . --project-root .",
        "done_when": "a real answer returns with an exact provider receipt",
        "blocked_by": ["install-extension"],
    })

    return {
        "schema_version": PLAN_SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "profile": profile,
        "profile_title": spec["title"],
        "roles": roles,
        "estimated_disk_gb": spec["approx_disk_gb"],
        "environment": facts.as_mapping(),
        "source_revision": source_revision,
        "steps": steps,
        "authority_note": (
            "Nothing here is performed automatically. Each step names its governing owner; "
            "steps marked requires_approval must be approved by the user. PX never downloads a "
            "model, installs a runtime, or enables a provider on its own."
        ),
    }


def _ask(prompt: str, options: dict[str, str], default: str) -> str:
    print()
    print(prompt)
    for choice, label in options.items():
        marker = " (default)" if choice == default else ""
        print(f"  [{choice}] {label}{marker}")
    while True:
        answer = input("> ").strip().lower() or default
        if answer in options:
            return answer
        print(f"  please choose one of: {', '.join(options)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Pacify-X installer and commissioning planner")
    parser.add_argument("--role", "--profile", dest="profile", choices=sorted(PROFILES))
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    facts = discover()
    recommended, reason = recommend_profile(facts)

    if args.profile:
        profile = args.profile
    elif args.non_interactive:
        profile = recommended
    else:
        profile = _ask(
            "Which Pacify-X profile fits this machine?",
            {key: f"{spec['title']} - {spec['summary']}" for key, spec in PROFILES.items()},
            recommended,
        )

    plan = build_plan(profile, facts)
    plan["recommended_profile"] = recommended
    plan["recommendation_reason"] = reason

    if args.apply and not args.dry_run:
        COMMISSIONING_DIR.mkdir(parents=True, exist_ok=True)
        target = COMMISSIONING_DIR / "commissioning-plan.json"
        target.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"\nwrote {target.relative_to(ROOT).as_posix()}")

    if args.json:
        print(json.dumps(plan, indent=2))
        return 0

    print()
    print("=" * 74)
    print(f"Pacify-X commissioning plan - profile: {profile} ({PROFILES[profile]['title']})")
    print("=" * 74)
    print(f"recommended: {recommended}  ({reason})")
    print(f"estimated additional disk: ~{PROFILES[profile]['approx_disk_gb']} GB")
    print()
    print("Environment discovered:")
    for key, value in facts.as_mapping().items():
        print(f"  {key:<22} {value}")
    print()
    print("Ordered steps (nothing is performed automatically):")
    for index, step in enumerate(plan["steps"], start=1):
        flag = " [APPROVAL REQUIRED]" if step["requires_approval"] else ""
        print(f"  {index}. {step['title']}{flag}")
        if step.get("command"):
            print(f"       $ {step['command']}")
        if step.get("blocked_by"):
            print(f"       after: {', '.join(step['blocked_by'])}")
        if step.get("approval_reason"):
            print(f"       because: {step['approval_reason']}")
    print()
    print("Re-run with --apply to record this plan under .engineering-bootstrap/commissioning/.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())