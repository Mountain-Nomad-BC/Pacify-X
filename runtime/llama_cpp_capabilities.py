"""Bounded llama.cpp executable capability fingerprinting and typed launch policy.

The exact llama-server binary is the authority for which command-line options are
available.  This module performs bounded, read-only probes and turns only
advertised options into launch arguments.  It grants no model, routing, tool,
memory, execution, certification, or release authority.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Callable, Iterable, Mapping, Sequence


FINGERPRINT_SCHEMA = "px.llama-cpp-capability-fingerprint/1.0"
MAX_PROBE_BYTES = 1_048_576
MAX_PROBE_SECONDS = 10.0
MAX_OPTIONS = 4096
OPTION_RE = re.compile(r"(?<![A-Za-z0-9_])(--[A-Za-z0-9][A-Za-z0-9-]*)")
KV_TYPE_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,31}$")


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _inside(path: Path, roots: Sequence[Path]) -> bool:
    candidate = os.path.normcase(str(path))
    for root in roots:
        try:
            normalized_root = os.path.normcase(str(root))
            if os.path.commonpath((candidate, normalized_root)) == normalized_root:
                return True
        except ValueError:
            continue
    return False


def _validate_executable(path: Path, allowed_roots: Iterable[Path] | None) -> Path:
    executable = path.resolve(strict=True)
    if not executable.is_file():
        raise ValueError("llama.cpp executable must be a regular file")
    if allowed_roots is not None:
        roots = tuple(root.resolve(strict=True) for root in allowed_roots)
        if not roots or not _inside(executable, roots):
            raise ValueError("llama.cpp executable is outside admitted runtime roots")
    return executable


def _normalize_probe(raw: bytes) -> str:
    if len(raw) > MAX_PROBE_BYTES:
        raise ValueError("llama.cpp probe output exceeds the bounded contract")
    return raw.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n").strip()


def _default_runner(command: Sequence[str], timeout: float) -> tuple[int, bytes, bytes]:
    completed = subprocess.run(
        list(command),
        shell=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    return int(completed.returncode), bytes(completed.stdout), bytes(completed.stderr)


ProbeRunner = Callable[[Sequence[str], float], tuple[int, bytes, bytes]]


def _probe(executable: Path, args: Sequence[str], *, runner: ProbeRunner, timeout: float) -> tuple[int, str]:
    code, stdout, stderr = runner((str(executable), *args), timeout)
    combined = stdout + (b"\n" if stdout and stderr else b"") + stderr
    return code, _normalize_probe(combined)


def _supported_options(help_text: str) -> tuple[str, ...]:
    options = sorted(set(OPTION_RE.findall(help_text)))
    if len(options) > MAX_OPTIONS:
        raise ValueError("llama.cpp help advertises too many options")
    return tuple(options)


@dataclass(frozen=True, slots=True)
class LlamaCppCapabilityFingerprint:
    schema_version: str
    executable_path: str
    executable_sha256: str
    executable_size_bytes: int
    version_text: str
    version_sha256: str
    help_sha256: str
    devices_sha256: str | None
    supported_options: tuple[str, ...]
    device_probe_supported: bool
    fingerprint_sha256: str

    def identity_payload(self) -> dict[str, object]:
        payload = asdict(self)
        payload.pop("fingerprint_sha256")
        payload["supported_options"] = list(self.supported_options)
        return payload

    def validate(self) -> None:
        if self.schema_version != FINGERPRINT_SCHEMA:
            raise ValueError("unsupported llama.cpp capability fingerprint schema")
        if not Path(self.executable_path).is_absolute():
            raise ValueError("capability fingerprint executable path must be absolute")
        if not re.fullmatch(r"[0-9a-f]{64}", self.executable_sha256):
            raise ValueError("invalid executable SHA-256")
        if type(self.executable_size_bytes) is not int or self.executable_size_bytes <= 0:
            raise ValueError("invalid executable size")
        for name, value in (("version_sha256", self.version_sha256), ("help_sha256", self.help_sha256)):
            if not re.fullmatch(r"[0-9a-f]{64}", value):
                raise ValueError(f"invalid {name}")
        if self.devices_sha256 is not None and not re.fullmatch(r"[0-9a-f]{64}", self.devices_sha256):
            raise ValueError("invalid devices_sha256")
        if tuple(sorted(set(self.supported_options))) != self.supported_options:
            raise ValueError("supported_options must be sorted and unique")
        if any(not OPTION_RE.fullmatch(option) for option in self.supported_options):
            raise ValueError("invalid llama.cpp option token")
        if self.fingerprint_sha256 != _sha(self.identity_payload()):
            raise ValueError("llama.cpp capability fingerprint digest is invalid")

    def supports(self, *options: str) -> bool:
        available = set(self.supported_options)
        return all(option in available for option in options)


def probe_llama_cpp_capabilities(
    executable_path: Path,
    *,
    allowed_roots: Iterable[Path] | None = None,
    runner: ProbeRunner | None = None,
    timeout_seconds: float = 3.0,
) -> LlamaCppCapabilityFingerprint:
    """Fingerprint an exact llama.cpp executable using bounded read-only probes."""
    if type(timeout_seconds) not in (int, float) or type(timeout_seconds) is bool or not 0 < float(timeout_seconds) <= MAX_PROBE_SECONDS:
        raise ValueError(f"probe timeout must be in (0, {MAX_PROBE_SECONDS}]")
    executable = _validate_executable(executable_path, allowed_roots)
    probe_runner = runner or _default_runner

    version_code, version_text = _probe(executable, ("--version",), runner=probe_runner, timeout=float(timeout_seconds))
    if version_code != 0 or not version_text:
        raise ValueError("llama.cpp --version probe failed")
    help_code, help_text = _probe(executable, ("--help",), runner=probe_runner, timeout=float(timeout_seconds))
    if help_code != 0 or not help_text:
        raise ValueError("llama.cpp --help probe failed")

    device_code, device_text = _probe(executable, ("--list-devices",), runner=probe_runner, timeout=float(timeout_seconds))
    device_supported = device_code == 0 and bool(device_text)
    options = _supported_options(help_text)
    size = executable.stat().st_size
    body = {
        "schema_version": FINGERPRINT_SCHEMA,
        "executable_path": str(executable),
        "executable_sha256": _digest_file(executable),
        "executable_size_bytes": size,
        "version_text": version_text[:4096],
        "version_sha256": hashlib.sha256(version_text.encode("utf-8")).hexdigest(),
        "help_sha256": hashlib.sha256(help_text.encode("utf-8")).hexdigest(),
        "devices_sha256": hashlib.sha256(device_text.encode("utf-8")).hexdigest() if device_supported else None,
        "supported_options": list(options),
        "device_probe_supported": device_supported,
    }
    fingerprint = LlamaCppCapabilityFingerprint(
        schema_version=FINGERPRINT_SCHEMA,
        executable_path=str(executable),
        executable_sha256=body["executable_sha256"],
        executable_size_bytes=size,
        version_text=body["version_text"],
        version_sha256=body["version_sha256"],
        help_sha256=body["help_sha256"],
        devices_sha256=body["devices_sha256"],
        supported_options=options,
        device_probe_supported=device_supported,
        fingerprint_sha256=_sha(body),
    )
    fingerprint.validate()
    return fingerprint


def assert_fingerprint_current(fingerprint: LlamaCppCapabilityFingerprint, executable_path: Path) -> Path:
    fingerprint.validate()
    executable = executable_path.resolve(strict=True)
    if str(executable) != fingerprint.executable_path:
        raise ValueError("capability fingerprint belongs to a different executable path")
    stat = executable.stat()
    if stat.st_size != fingerprint.executable_size_bytes or _digest_file(executable) != fingerprint.executable_sha256:
        raise ValueError("llama.cpp capability fingerprint is stale")
    return executable


def _bounded_int(value: object, name: str, minimum: int, maximum: int, *, optional: bool = True) -> int | None:
    if value is None and optional:
        return None
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer in [{minimum}, {maximum}]")
    return value


def _optional_bool(value: object, name: str) -> bool | None:
    if value is None:
        return None
    if type(value) is not bool:
        raise ValueError(f"{name} must be boolean or null")
    return value


def _kv_type(value: object, name: str) -> str | None:
    if value is None:
        return None
    if type(value) is not str or not KV_TYPE_RE.fullmatch(value.strip().lower()):
        raise ValueError(f"{name} is not a bounded llama.cpp cache type")
    return value.strip().lower()


@dataclass(frozen=True, slots=True)
class LlamaCppLaunchPolicy:
    """Typed optional llama.cpp placement/performance policy.

    Values are rendered only when the exact pinned executable advertises the
    corresponding option.  ``None`` means PX makes no request for that setting.
    """

    gpu_layers: int | str | None = None  # integer | "auto" | "all"
    cpu_moe: bool | None = None
    cpu_moe_layers: int | None = None
    cpu_ffn: bool | None = None
    threads: int | None = None
    threads_batch: int | None = None
    batch_size: int | None = None
    ubatch_size: int | None = None
    flash_attention: bool | None = None
    fit: bool | None = None
    fit_target: int | None = None
    fit_context_min: int | None = None
    cache_type_k: str | None = None
    cache_type_v: str | None = None
    mmap: bool | None = None
    mlock: bool | None = None

    def validate(self) -> None:
        if self.gpu_layers is not None:
            if type(self.gpu_layers) is int:
                _bounded_int(self.gpu_layers, "gpu_layers", 0, 100_000, optional=False)
            elif self.gpu_layers not in {"auto", "all"}:
                raise ValueError("gpu_layers must be integer, 'auto', 'all', or null")
        _optional_bool(self.cpu_moe, "cpu_moe")
        _bounded_int(self.cpu_moe_layers, "cpu_moe_layers", 0, 100_000)
        _optional_bool(self.cpu_ffn, "cpu_ffn")
        _bounded_int(self.threads, "threads", 1, 4096)
        _bounded_int(self.threads_batch, "threads_batch", 1, 4096)
        _bounded_int(self.batch_size, "batch_size", 1, 1_048_576)
        _bounded_int(self.ubatch_size, "ubatch_size", 1, 1_048_576)
        if self.batch_size is not None and self.ubatch_size is not None and self.ubatch_size > self.batch_size:
            raise ValueError("ubatch_size cannot exceed batch_size")
        _optional_bool(self.flash_attention, "flash_attention")
        _optional_bool(self.fit, "fit")
        _bounded_int(self.fit_target, "fit_target", 1, 1024**4)
        _bounded_int(self.fit_context_min, "fit_context_min", 128, 1_048_576)
        _kv_type(self.cache_type_k, "cache_type_k")
        _kv_type(self.cache_type_v, "cache_type_v")
        _optional_bool(self.mmap, "mmap")
        _optional_bool(self.mlock, "mlock")
        if self.cpu_moe is False and self.cpu_moe_layers not in (None, 0):
            raise ValueError("cpu_moe_layers conflicts with cpu_moe=false")

    def as_mapping(self) -> dict[str, object]:
        self.validate()
        return asdict(self)


def _pick(fingerprint: LlamaCppCapabilityFingerprint, logical: str, candidates: Sequence[str]) -> str:
    available = set(fingerprint.supported_options)
    for candidate in candidates:
        if candidate in available:
            return candidate
    raise ValueError(f"pinned llama.cpp executable does not advertise required option: {logical}")


def _boolean_args(
    fingerprint: LlamaCppCapabilityFingerprint,
    logical: str,
    value: bool | None,
    positive: Sequence[str],
    negative: Sequence[str],
) -> list[str]:
    if value is None:
        return []
    if value:
        return [_pick(fingerprint, logical, positive)]
    if negative:
        return [_pick(fingerprint, logical, negative)]
    raise ValueError(f"explicit false for {logical} cannot be represented by the pinned executable")


def _valued_boolean_args(
    fingerprint: LlamaCppCapabilityFingerprint,
    logical: str,
    value: bool | None,
    option_forms: Sequence[str],
) -> list[str]:
    """Render a boolean as ``<option> on|off`` for builds whose flag takes a value.

    Recent llama.cpp releases replaced the paired ``--x`` / ``--no-x`` booleans with a single
    valued option (for example ``-fa, --flash-attn [on|off|auto]``). Emitting the bare flag or
    a non-existent ``--no-x`` fails at launch, so the exact binary form is selected and the
    value is always supplied. Presence of a distinct ``--no-<option>`` in the same help text is
    what distinguishes the paired form, handled by ``_boolean_args`` instead.
    """

    if value is None:
        return []
    option = _pick(fingerprint, logical, option_forms)
    return [option, "on" if value else "off"]


def launch_policy_from_profile(profile: object) -> LlamaCppLaunchPolicy:
    """Bridge a validated runtime profile to a typed llama.cpp launch policy.

    The typed placement layer (``gpu_layers`` / ``cpu_moe_layers`` / ``flash_attention`` and
    friends) only takes effect when a caller builds it from the profile. Without this bridge,
    ``plan_server`` always falls back to the legacy integer ``--n-gpu-layers`` path and every
    other placement control the binary supports is silently unused.

    Only fields the profile actually declares are carried. ``None`` continues to mean "PX makes
    no request for this setting", so nothing is invented.
    """

    def _get(name: str) -> object:
        return getattr(profile, name, None)

    gpu_layers = _get("gpu_layers")
    if isinstance(gpu_layers, str) and gpu_layers not in {"auto", "all"}:
        gpu_layers = None
    cpu_moe_layers = _get("cpu_moe_layers")
    threads = _get("threads")
    threads_batch = _get("threads_batch")
    batch_size = _get("batch_size")
    ubatch_size = _get("ubatch_size")
    flash_attention = _get("flash_attention")
    policy = LlamaCppLaunchPolicy(
        gpu_layers=gpu_layers if isinstance(gpu_layers, (int, str)) else None,
        cpu_moe=bool(cpu_moe_layers) if isinstance(cpu_moe_layers, int) and cpu_moe_layers > 0 else None,
        cpu_moe_layers=cpu_moe_layers if isinstance(cpu_moe_layers, int) else None,
        threads=threads if isinstance(threads, int) else None,
        threads_batch=threads_batch if isinstance(threads_batch, int) else None,
        batch_size=batch_size if isinstance(batch_size, int) else None,
        ubatch_size=ubatch_size if isinstance(ubatch_size, int) else None,
        flash_attention=flash_attention if isinstance(flash_attention, bool) else None,
    )
    policy.validate()
    return policy


def render_launch_policy(
    policy: LlamaCppLaunchPolicy,
    fingerprint: LlamaCppCapabilityFingerprint,
) -> tuple[str, ...]:
    """Render a typed policy against the exact advertised option set; fail closed."""
    policy.validate()
    fingerprint.validate()
    args: list[str] = []

    def value_arg(logical: str, value: object, candidates: Sequence[str]) -> None:
        if value is None:
            return
        args.extend((_pick(fingerprint, logical, candidates), str(value)))

    value_arg("gpu_layers", policy.gpu_layers, ("--n-gpu-layers",))
    args.extend(_boolean_args(fingerprint, "cpu_moe", policy.cpu_moe, ("--cpu-moe",), ("--no-cpu-moe",)))
    value_arg("cpu_moe_layers", policy.cpu_moe_layers, ("--n-cpu-moe", "--cpu-moe-layers"))
    args.extend(_boolean_args(fingerprint, "cpu_ffn", policy.cpu_ffn, ("--cpu-ffn",), ("--no-cpu-ffn",)))
    value_arg("threads", policy.threads, ("--threads",))
    value_arg("threads_batch", policy.threads_batch, ("--threads-batch",))
    value_arg("batch_size", policy.batch_size, ("--batch-size",))
    value_arg("ubatch_size", policy.ubatch_size, ("--ubatch-size",))
    # Flash attention and fit are valued booleans in current llama.cpp builds
    # (``-fa, --flash-attn [on|off|auto]``); the paired --x/--no-x form no longer exists.
    args.extend(_valued_boolean_args(fingerprint, "flash_attention", policy.flash_attention, ("--flash-attn", "--flash_attention")))
    args.extend(_valued_boolean_args(fingerprint, "fit", policy.fit, ("--fit",)))
    value_arg("fit_target", policy.fit_target, ("--fit-target",))
    value_arg("fit_context_min", policy.fit_context_min, ("--fit-ctx", "--fit-context-min"))
    value_arg("cache_type_k", _kv_type(policy.cache_type_k, "cache_type_k"), ("--cache-type-k",))
    value_arg("cache_type_v", _kv_type(policy.cache_type_v, "cache_type_v"), ("--cache-type-v",))
    args.extend(_boolean_args(fingerprint, "mmap", policy.mmap, ("--mmap",), ("--no-mmap",)))
    args.extend(_boolean_args(fingerprint, "mlock", policy.mlock, ("--mlock",), ("--no-mlock",)))
    return tuple(args)


def capability_receipt(fingerprint: LlamaCppCapabilityFingerprint) -> Mapping[str, object]:
    """Return a JSON-safe non-authoritative receipt for evidence and profile binding."""
    fingerprint.validate()
    return {
        "schema_version": FINGERPRINT_SCHEMA,
        "executable_path": fingerprint.executable_path,
        "executable_sha256": fingerprint.executable_sha256,
        "executable_size_bytes": fingerprint.executable_size_bytes,
        "version_text": fingerprint.version_text,
        "version_sha256": fingerprint.version_sha256,
        "help_sha256": fingerprint.help_sha256,
        "devices_sha256": fingerprint.devices_sha256,
        "supported_options": list(fingerprint.supported_options),
        "device_probe_supported": fingerprint.device_probe_supported,
        "fingerprint_sha256": fingerprint.fingerprint_sha256,
        "authority": "evidence_only_no_runtime_or_certification_grant",
    }
