from __future__ import annotations

import ast
from hashlib import sha256
import importlib.util
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "runtime" / "llama_cpp_capabilities.py"
SPEC = importlib.util.spec_from_file_location("px_unified_llama_cpp_capabilities", MODULE_PATH)
assert SPEC and SPEC.loader
CAP = importlib.util.module_from_spec(SPEC)
import sys
sys.modules[SPEC.name] = CAP
SPEC.loader.exec_module(CAP)

LlamaCppLaunchPolicy = CAP.LlamaCppLaunchPolicy
assert_fingerprint_current = CAP.assert_fingerprint_current
probe_llama_cpp_capabilities = CAP.probe_llama_cpp_capabilities
render_launch_policy = CAP.render_launch_policy

HELP = b"""llama-server\n  --n-gpu-layers N\n  --cpu-moe\n  --no-cpu-moe\n  --n-cpu-moe N\n  --cpu-ffn\n  --no-cpu-ffn\n  --threads N\n  --threads-batch N\n  --batch-size N\n  --ubatch-size N\n  --flash-attn\n  --no-flash-attn\n  --fit\n  --no-fit\n  --fit-target N\n  --fit-ctx N\n  --cache-type-k TYPE\n  --cache-type-v TYPE\n  --mmap\n  --no-mmap\n  --mlock\n  --no-mlock\n  --list-devices\n"""


def runner(command, timeout):
    assert timeout <= 10
    if command[-1] == "--version":
        return 0, b"llama-server test-build", b""
    if command[-1] == "--help":
        return 0, HELP, b""
    if command[-1] == "--list-devices":
        return 0, b"CPU\nGPU0", b""
    raise AssertionError(command)


def test_capability_fingerprint_is_binary_bound_and_policy_is_closed_world(tmp_path: Path) -> None:
    binary = tmp_path / "llama-server"
    binary.write_bytes(b"fake llama binary")
    fp = probe_llama_cpp_capabilities(binary, allowed_roots=[tmp_path], runner=runner)
    assert fp.executable_sha256 == sha256(binary.read_bytes()).hexdigest()
    assert fp.supports("--n-gpu-layers", "--cpu-moe", "--cache-type-k")

    policy = LlamaCppLaunchPolicy(
        gpu_layers="all", cpu_moe=True, cpu_moe_layers=12, cpu_ffn=True,
        threads=8, threads_batch=12, batch_size=512, ubatch_size=128,
        flash_attention=True, fit=True, fit_target=4096, fit_context_min=4096,
        cache_type_k="q8_0", cache_type_v="q8_0", mmap=False, mlock=True,
    )
    args = render_launch_policy(policy, fp)
    assert args[:2] == ("--n-gpu-layers", "all")
    assert "--cpu-moe" in args and "--n-cpu-moe" in args
    assert "--cache-type-k" in args and "--no-mmap" in args

    binary.write_bytes(b"changed binary")
    with pytest.raises(ValueError, match="stale"):
        assert_fingerprint_current(fp, binary)


def test_unsupported_requested_option_fails_closed(tmp_path: Path) -> None:
    binary = tmp_path / "llama-server"
    binary.write_bytes(b"fake")

    def limited(command, timeout):
        if command[-1] == "--version": return 0, b"v", b""
        if command[-1] == "--help": return 0, b"--n-gpu-layers N", b""
        return 1, b"", b"unknown"

    fp = probe_llama_cpp_capabilities(binary, runner=limited)
    with pytest.raises(ValueError, match="threads"):
        render_launch_policy(LlamaCppLaunchPolicy(threads=4), fp)


def test_typed_policy_rejects_conflicts() -> None:
    with pytest.raises(ValueError, match="conflicts"):
        LlamaCppLaunchPolicy(cpu_moe=False, cpu_moe_layers=4).validate()
    with pytest.raises(ValueError, match="ubatch_size"):
        LlamaCppLaunchPolicy(batch_size=64, ubatch_size=128).validate()


def test_local_runtime_source_contains_modern_qwen_and_capability_binding() -> None:
    source_path = Path(__file__).resolve().parents[1] / "runtime" / "local_model_runtime.py"
    source = source_path.read_text(encoding="utf-8")
    ast.parse(source)
    for architecture in ("qwen35", "qwen35moe", "qwen3moe", "qwen3next"):
        assert f'"{architecture}"' in source
    assert "LlamaCppCapabilityFingerprint" in source
    assert "assert_fingerprint_current" in source
    assert "render_launch_policy" in source
    assert "typed launch policy and exact capability fingerprint are required together" in source
