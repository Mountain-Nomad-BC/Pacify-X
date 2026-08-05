"""Feature-level health checks for executables used by authority paths."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable


Runner = Callable[..., subprocess.CompletedProcess[str]]


def openssh_authority_status(*, runner: Runner = subprocess.run) -> dict[str, object]:
    """Probe the OpenSSH features required for signed evidence without signing canon."""
    executable = shutil.which("ssh-keygen")
    result: dict[str, object] = {
        "executable": executable,
        "present": executable is not None,
        "ed25519_generation": False,
        "ssh_signature_sign": False,
        "ssh_signature_verify": False,
        "authoritative_signing_available": False,
        "finding_codes": [],
    }
    findings: list[str] = result["finding_codes"]  # type: ignore[assignment]
    if executable is None:
        findings.append("SSH_KEYGEN_NOT_FOUND")
        return result
    try:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            key = root / "probe_key"
            generated = runner(
                [executable, "-q", "-t", "ed25519", "-N", "", "-f", str(key)],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            result["ed25519_generation"] = (
                generated.returncode == 0
                and key.is_file()
                and Path(str(key) + ".pub").is_file()
            )
            if not result["ed25519_generation"]:
                findings.append("ED25519_GENERATION_UNAVAILABLE")
                return result
            payload = root / "probe.txt"
            payload.write_text("toolchain capability probe\n", encoding="utf-8")
            signed = runner(
                [
                    executable,
                    "-Y",
                    "sign",
                    "-f",
                    str(key),
                    "-n",
                    "pacify-x-toolchain-probe",
                    str(payload),
                ],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            signature = Path(str(payload) + ".sig")
            result["ssh_signature_sign"] = (
                signed.returncode == 0 and signature.is_file()
            )
            if not result["ssh_signature_sign"]:
                findings.append("SSH_SIGNATURE_SIGN_UNAVAILABLE")
                return result
            allowed = root / "allowed_signers"
            allowed.write_text(
                "probe " + Path(str(key) + ".pub").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            with payload.open("r", encoding="utf-8") as stream:
                verified = runner(
                    [
                        executable,
                        "-Y",
                        "verify",
                        "-f",
                        str(allowed),
                        "-I",
                        "probe",
                        "-n",
                        "pacify-x-toolchain-probe",
                        "-s",
                        str(signature),
                    ],
                    stdin=stream,
                    capture_output=True,
                    text=True,
                    timeout=20,
                    check=False,
                )
            result["ssh_signature_verify"] = verified.returncode == 0
            if not result["ssh_signature_verify"]:
                findings.append("SSH_SIGNATURE_VERIFY_UNAVAILABLE")
    except (OSError, subprocess.SubprocessError) as error:
        findings.append(f"SSH_TOOLCHAIN_PROBE_FAILED:{type(error).__name__}")
    result["authoritative_signing_available"] = bool(
        result["ed25519_generation"]
        and result["ssh_signature_sign"]
        and result["ssh_signature_verify"]
    )
    return result


def require_openssh_authority(*, runner: Runner = subprocess.run) -> dict[str, object]:
    """Fail with one stable actionable error when signed authority is unavailable."""
    status = openssh_authority_status(runner=runner)
    if not status["authoritative_signing_available"]:
        codes = ",".join(map(str, status["finding_codes"])) or "UNKNOWN"
        raise RuntimeError(
            "AUTHORITATIVE_SIGNING_UNAVAILABLE: install OpenSSH with Ed25519 and "
            f"ssh-keygen -Y sign/-Y verify support ({codes})"
        )
    return status
