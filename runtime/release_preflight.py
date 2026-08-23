"""Fast, fail-closed release-closure discovery before signed certification."""

from __future__ import annotations

from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import subprocess
import tempfile
import threading
import time
from typing import Any, Callable, Iterable, Mapping
from uuid import uuid4

from .engine_identity import build_engine_identity, validate_engine_identity
from .evidence_portability import portability_findings
from .file_lock import FileLock
from .generated_dependency import generated_dependency_graph
from .release_artifacts import classify_tree
from .release_boundary import copy_clean_product
from .release_identity import authoritative_version, capture_git_identity
from .resource_lifecycle import ResourceManager, RunState
from .release_skip_policy import ALLOWED_RELEASE_TEST_SKIPS, junit_skip_policy_gate


PREFLIGHT_POLICY = Path("policies/release-preflight.json")
RECEIPT_ROOT = Path(".engineering-bootstrap/runtime-core/release-preflight")
CACHE_ROOT = Path(".engineering-bootstrap/runtime-core/release-preflight-cache")
RESOURCE_REGISTRY = Path(
    ".engineering-bootstrap/runtime-core/release-preflight-resources.json"
)
COVERAGE_GAP_ROOT = Path(
    ".engineering-bootstrap/runtime-core/release-preflight-coverage-gaps"
)


@dataclass(frozen=True)
class PreflightFailure:
    code: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    prepared = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.prepared")
    prepared.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    # Concurrent replacement of the same destination can transiently return
    # ERROR_ACCESS_DENIED on Windows even though each prepared file is unique.
    # Keep publication atomic and bounded while allowing the competing writer
    # to finish; a persistent denial still fails closed.
    for attempt in range(100):
        try:
            os.replace(prepared, path)
            break
        except PermissionError:
            if attempt == 99:
                raise
            time.sleep(0.001)


def _files(root: Path) -> dict[str, dict[str, object]]:
    records: dict[str, dict[str, object]] = {}
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root).as_posix()
        payload = path.read_bytes()
        records[relative] = {"bytes": len(payload), "sha256": _sha_bytes(payload)}
    return records


def compare_trees(
    before: Mapping[str, object], after: Mapping[str, object]
) -> dict[str, list[str]]:
    before_paths = set(before)
    after_paths = set(after)
    return {
        "added": sorted(after_paths - before_paths),
        "removed": sorted(before_paths - after_paths),
        "changed": sorted(
            path for path in before_paths & after_paths if before[path] != after[path]
        ),
    }


def audit_clean_boundary(
    source: Path,
    clean: Path,
    *,
    identity_inputs: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Prove every identity input and classified product file survives export."""
    source = source.resolve()
    clean = clean.resolve()
    clean_files = _files(clean)
    source_files: dict[str, dict[str, object]] = {}
    source_mismatches: list[str] = []
    for relative, clean_record in clean_files.items():
        source_path = source / relative
        if not source_path.is_file() or source_path.is_symlink():
            continue
        payload = source_path.read_bytes()
        source_record = {"bytes": len(payload), "sha256": _sha_bytes(payload)}
        source_files[relative] = source_record
        if source_record != clean_record:
            source_mismatches.append(relative)
    if identity_inputs is None:
        identity_inputs = (
            str(record["path"]) for record in build_engine_identity(source)["records"]
        )
    identity = sorted(set(identity_inputs))
    missing_identity = sorted(path for path in identity if path not in clean_files)
    source_product = classify_tree(source)
    clean_product = classify_tree(clean)
    product_paths = {
        str(record["path"]) for record in source_product.get("product_records", ())
    }
    missing_product = sorted(product_paths - set(clean_files))
    unexpected = sorted(set(clean_files) - set(source_files))
    failures: list[PreflightFailure] = []
    if missing_identity:
        failures.append(
            PreflightFailure(
                "RP-BND-001",
                f"{len(missing_identity)} identity input(s) are absent from the exact clean export",
            )
        )
    if missing_product or unexpected or source_mismatches:
        failures.append(
            PreflightFailure(
                "RP-BND-002",
                "clean export differs from the classified product boundary",
            )
        )
    if (
        not source_product.get("valid")
        or not clean_product.get("valid")
        or source_product.get("product_digest") != clean_product.get("product_digest")
    ):
        failures.append(
            PreflightFailure(
                "RP-BND-002", "live and clean product digests do not match"
            )
        )
    return {
        "schema_version": "px.release-boundary-diff/1.0",
        "valid": not failures,
        "source_file_count": len(source_files),
        "clean_file_count": len(clean_files),
        "identity_input_count": len(identity),
        "identity_inputs_missing_from_clean_export": missing_identity,
        "excluded_identity_inputs": missing_identity,
        "product_inputs_missing_from_clean_export": missing_product,
        "unexpected_clean_files": unexpected,
        "clean_source_byte_mismatches": sorted(source_mismatches),
        "digest_comparison": {
            "source": source_product.get("product_digest"),
            "clean": clean_product.get("product_digest"),
            "equal": source_product.get("product_digest")
            == clean_product.get("product_digest"),
        },
        "failures": [item.as_dict() for item in failures],
    }


def require_stable_source_binding(
    boundary: dict[str, Any], expected_product_digest: str | None
) -> dict[str, Any]:
    """Reject preflight actions that mutate the source after initial binding."""
    observed = boundary.get("digest_comparison", {}).get("source")
    if observed == expected_product_digest:
        return boundary
    boundary["valid"] = False
    boundary.setdefault("failures", []).append(
        PreflightFailure(
            "RP-MUT-001",
            "preflight mutated the live product after its initial identity binding",
        ).as_dict()
    )
    boundary["initial_product_digest"] = expected_product_digest
    boundary["observed_source_product_digest"] = observed
    return boundary


def feedback_audit(
    root: Path,
    write_targets: Iterable[str],
) -> dict[str, Any]:
    product_paths = {
        str(record["path"]) for record in classify_tree(root).get("product_records", ())
    }
    illegal = []
    classified = []
    for target in write_targets:
        normalized = str(target).replace("\\", "/")
        concrete = normalized.replace("<release>", "release").replace("<run-id>", "run")
        if concrete in product_paths:
            kind = "generated_product"
            illegal.append(normalized)
        elif concrete.startswith("evidence/"):
            kind = "release_transaction_evidence"
        elif concrete.startswith(".engineering-bootstrap/runtime-core/"):
            kind = "post_cert_runtime_state"
        elif concrete.startswith(".engineering-bootstrap/"):
            kind = "temporary_workspace"
        else:
            kind = "unknown"
            illegal.append(normalized)
        classified.append({"path": normalized, "classification": kind})
    return {
        "schema_version": "px.release-feedback-audit/1.0",
        "valid": not illegal,
        "writes": classified,
        "illegal_feedback_targets": illegal,
        "failures": []
        if not illegal
        else [
            PreflightFailure(
                "RP-FBK-001",
                "post-certification write feeds an immutable or unknown product input: "
                + ", ".join(illegal),
            ).as_dict()
        ],
    }


def _release_evidence_files(root: Path) -> list[Path]:
    """Return only evidence that can enter the current release transaction."""
    candidates: set[Path] = set()
    if (root / "pyproject.toml").is_file():
        release_root = root / "evidence/releases" / authoritative_version(root)
        if release_root.is_dir():
            candidates.update(
                path for path in release_root.rglob("*") if path.is_file()
            )
    else:
        evidence = root / "evidence"
        if evidence.is_dir():
            candidates.update(path for path in evidence.iterdir() if path.is_file())
    installed = root / "extension/evidence"
    if installed.is_dir():
        candidates.update(path for path in installed.iterdir() if path.is_file())
    return sorted(candidates, key=lambda item: item.as_posix().casefold())


def evidence_portability(root: Path) -> dict[str, Any]:
    findings: list[dict[str, object]] = []
    for path in _release_evidence_files(root):
        if path.suffix.casefold() not in {
            ".json",
            ".jsonl",
            ".xml",
            ".log",
            ".txt",
            ".md",
        }:
            continue
        for value in portability_findings(
            path.read_text(encoding="utf-8", errors="replace")
        ):
            findings.append(
                {"path": path.relative_to(root).as_posix(), "locator": value}
            )
    return {
        "schema_version": "px.release-evidence-portability-preflight/1.0",
        "valid": not findings,
        "finding_count": len(findings),
        "findings": findings,
        "failures": []
        if not findings
        else [
            PreflightFailure(
                "RP-EVD-001", f"{len(findings)} machine-local evidence locator(s) found"
            ).as_dict()
        ],
    }


def evidence_budget(root: Path, policy: Mapping[str, Any]) -> dict[str, Any]:
    files = [
        {"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size}
        for path in _release_evidence_files(root)
        if not path.is_symlink()
    ]
    files.sort(key=lambda item: (-int(item["bytes"]), str(item["path"])))
    total = sum(int(item["bytes"]) for item in files)
    maximum = int(policy["max_total_release_evidence_bytes"])
    single = int(policy["max_single_evidence_file_bytes"])
    oversized = [item for item in files if int(item["bytes"]) > single]
    product = (
        classify_tree(root)
        if (root / "policies/release-artifact-policy.json").is_file()
        else {"product_records": []}
    )
    source_bytes = sum(
        int(item.get("size") or 0) for item in product.get("product_records", ())
    )
    amplification = total / source_bytes if source_bytes else 0.0
    max_amplification = float(policy.get("max_context_amplification_ratio", 20.0))
    valid = total <= maximum and not oversized and amplification <= max_amplification
    return {
        "schema_version": "px.release-evidence-budget/1.0",
        "valid": valid,
        "total_bytes": total,
        "file_count": len(files),
        "maximum_total_bytes": maximum,
        "maximum_single_file_bytes": single,
        "source_bytes": source_bytes,
        "context_amplification_ratio": round(amplification, 6),
        "maximum_context_amplification_ratio": max_amplification,
        "top_contributors": files[:20],
        "oversized_files": oversized,
        "failures": []
        if valid
        else [
            PreflightFailure(
                "RP-EVD-002", "release evidence exceeds the configured bounded budget"
            ).as_dict()
        ],
    }


def skip_policy_preflight(junit: Path | None = None) -> dict[str, Any]:
    expected = sorted(f"{owner}::{name}" for owner, name in ALLOWED_RELEASE_TEST_SKIPS)
    if junit is None:
        return {
            "schema_version": "px.release-skip-preflight/1.0",
            "valid": True,
            "allowed": expected,
            "unknown": [],
            "missing_expected": [],
            "observation": "policy_only",
        }
    result = junit_skip_policy_gate(junit)
    observed = set(result["allowed"])
    return {
        "schema_version": "px.release-skip-preflight/1.0",
        "valid": bool(result["valid"]),
        "allowed": result["allowed"],
        "unknown": result["unexpected"],
        "missing_expected": sorted(set(expected) - observed),
        "observation": "junit",
        "failures": []
        if result["valid"]
        else [PreflightFailure("RP-SKP-001", "unknown test skip observed").as_dict()],
    }


def mutation_probe(
    root: Path,
    actions: Iterable[Callable[[Path], object]],
) -> dict[str, Any]:
    before = _files(root)
    for action in actions:
        action(root)
    after = _files(root)
    diff = compare_trees(before, after)
    changed = [*diff["added"], *diff["removed"], *diff["changed"]]
    classifications = []
    for path in changed:
        if (
            path.startswith((".pytest_cache/", "__pycache__/"))
            or "/__pycache__/" in path
        ):
            kind = "cache/temp pollution"
        elif path.startswith(".engineering-bootstrap/"):
            kind = "derived runtime state incorrectly inside product"
        elif path.startswith("registry/"):
            kind = "generated projection pollution"
        else:
            kind = "illegal product mutation"
        classifications.append({"path": path, "classification": kind})
    return {
        "schema_version": "px.release-mutation-probe/1.0",
        "valid": not changed,
        "diff": diff,
        "changes": classifications,
        "failures": []
        if not changed
        else [
            PreflightFailure(
                "RP-MUT-001",
                f"safe probes mutated {len(changed)} clean-product path(s)",
            ).as_dict()
        ],
    }


def rebuild_equivalence(
    clean: Path, rebuild: Path, authorities: Iterable[str]
) -> dict[str, Any]:
    from scripts.clean_source_export import _rebuild_candidate_projections

    # The clean tree is disposable and already lifecycle-owned. Snapshot only
    # deterministic authorities, rebuild them in place, and compare exact
    # bytes; cloning the entire 100+ MB product would add minutes without
    # increasing the strength of this invariant.
    del rebuild
    before = {
        relative: (clean / relative).read_bytes()
        if (clean / relative).is_file()
        else None
        for relative in authorities
    }
    _rebuild_candidate_projections(clean)
    differences = []
    details: dict[str, list[str]] = {}

    def pointers(left: object, right: object, pointer: str = "") -> list[str]:
        if type(left) is not type(right):
            return [pointer or "/"]
        if isinstance(left, dict):
            changed: list[str] = []
            for key in sorted(set(left) | set(right)):
                child = f"{pointer}/{key}"
                if key not in left or key not in right:
                    changed.append(child)
                else:
                    changed.extend(pointers(left[key], right[key], child))
                if len(changed) >= 20:
                    break
            return changed[:20]
        if isinstance(left, list):
            if len(left) != len(right):
                return [f"{pointer}/length"]
            changed = []
            for index, (left_item, right_item) in enumerate(zip(left, right)):
                changed.extend(pointers(left_item, right_item, f"{pointer}/{index}"))
                if len(changed) >= 20:
                    break
            return changed[:20]
        return [] if left == right else [pointer or "/"]

    for relative in authorities:
        right = clean / relative
        if (
            before[relative] is None
            or not right.is_file()
            or before[relative] != right.read_bytes()
        ):
            differences.append(relative)
            if before[relative] is not None and right.is_file():
                try:
                    details[relative] = pointers(
                        json.loads(before[relative]), json.loads(right.read_bytes())
                    )
                except (json.JSONDecodeError, UnicodeDecodeError):
                    details[relative] = ["/"]
    return {
        "schema_version": "px.clean-rebuild-equivalence/1.0",
        "valid": not differences,
        "checked": list(authorities),
        "different": differences,
        "difference_pointers": details,
        "failures": []
        if not differences
        else [
            PreflightFailure(
                "RP-GEN-001",
                "clean-stage generated projections are stale: "
                + ", ".join(differences),
            ).as_dict()
        ],
    }


def concurrency_stress(
    directory: Path, *, iterations: int, seed: int
) -> dict[str, Any]:
    """Deterministically exercise atomic publication without unbounded soaking."""
    target = directory / "atomic-publication.json"
    decisions = []
    lock_failures: list[dict[str, Any]] = []
    schedule = random.Random(seed)
    monitor = threading.Lock()
    active = 0

    def locked_actor(actor: int, iteration: int, delay: float) -> None:
        nonlocal active
        time.sleep(delay)
        with FileLock(directory / "publication.lock", timeout_seconds=2):
            with monitor:
                active += 1
                if active != 1:
                    lock_failures.append(
                        {
                            "code": "RP-CON-001",
                            "iteration": iteration,
                            "operation": "file-lock-mutual-exclusion",
                            "competing_actors": [0, 1],
                            "observed": {"active_owners": active, "actor": actor},
                            "expected": {"active_owners": 1},
                        }
                    )
            time.sleep(0.0005)
            with monitor:
                active -= 1

    for iteration in range(iterations):
        values = [
            {"actor": actor, "iteration": iteration, "seed": seed} for actor in (0, 1)
        ]
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(_atomic_json, target, value) for value in values]
            for future in futures:
                future.result()
        observed = _json(target)
        if observed not in values:
            return {
                "schema_version": "px.release-concurrency-stress/1.0",
                "valid": False,
                "seed": seed,
                "iterations": iteration + 1,
                "failure": {
                    "code": "RP-CON-001",
                    "iteration": iteration,
                    "operation": "atomic-json-publication",
                    "competing_actors": [0, 1],
                    "observed": observed,
                    "expected": values,
                },
            }
        decisions.append(int(observed["actor"]))
        delays = [schedule.random() / 10_000 for _ in values]
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(locked_actor, actor, iteration, delays[actor])
                for actor in (0, 1)
            ]
            for future in futures:
                future.result()
        if lock_failures:
            return {
                "schema_version": "px.release-concurrency-stress/1.0",
                "valid": False,
                "seed": seed,
                "iterations": iteration + 1,
                "failure": lock_failures[0],
                "failures": lock_failures,
            }
    return {
        "schema_version": "px.release-concurrency-stress/1.0",
        "valid": True,
        "seed": seed,
        "iterations": iterations,
        "actor_zero": decisions.count(0),
        "actor_one": decisions.count(1),
        "operations": ["atomic-json-publication", "file-lock-mutual-exclusion"],
        "failures": [],
    }


def transaction_simulation(clean: Path, custody: Path) -> dict[str, Any]:
    """Simulate evidence/certificate/runtime publication outside product custody."""
    before = classify_tree(clean)
    evidence = custody / "release-evidence/run-simulated"
    certificate = custody / "published/certificate.json"
    runtime_projection = custody / "runtime/completion_status.json"
    representative = {
        "schema_version": "px.release-transaction-simulation/1.0",
        "product_digest": before.get("product_digest"),
        "artifact": "[content-addressed-artifact]",
        "machine_local_paths": False,
    }
    _atomic_json(evidence / "gate-summary.json", {**representative, "valid": True})
    _atomic_json(certificate, {**representative, "status": "simulated-unsigned"})
    _atomic_json(runtime_projection, {**representative, "certified": False})
    after = classify_tree(clean)
    portable = not portability_findings(
        "\n".join(
            path.read_text(encoding="utf-8")
            for path in (
                evidence / "gate-summary.json",
                certificate,
                runtime_projection,
            )
        )
    )
    valid = (
        before.get("valid") is True
        and after.get("valid") is True
        and before.get("product_digest") == after.get("product_digest")
        and portable
    )
    return {
        "schema_version": "px.release-transaction-simulation/1.0",
        "valid": valid,
        "signed": False,
        "published_authoritatively": False,
        "product_digest_before": before.get("product_digest"),
        "product_digest_after": after.get("product_digest"),
        "portable": portable,
        "simulated_outputs": [
            "release-evidence/run-simulated/gate-summary.json",
            "published/certificate.json",
            "runtime/completion_status.json",
        ],
        "failures": []
        if valid
        else [
            PreflightFailure(
                "RP-FBK-001",
                "disposable publication simulation fed back into product identity",
            ).as_dict()
        ],
    }


def _projection_snapshot(
    root: Path, authorities: Iterable[str]
) -> dict[str, str | None]:
    return {
        relative: _sha_bytes((root / relative).read_bytes())
        if (root / relative).is_file()
        else None
        for relative in authorities
    }


def fixed_point(clean: Path, authorities: Iterable[str]) -> dict[str, Any]:
    from scripts.clean_source_export import _rebuild_candidate_projections

    authorities = tuple(authorities)
    _rebuild_candidate_projections(clean)
    first = _projection_snapshot(clean, authorities)
    _rebuild_candidate_projections(clean)
    second = _projection_snapshot(clean, authorities)
    changed = sorted(path for path in authorities if first[path] != second[path])
    return {
        "schema_version": "px.release-fixed-point/1.0",
        "valid": not changed,
        "fixed_point": not changed,
        "pass_1_digest": _sha_bytes(_canonical(first)),
        "pass_2_digest": _sha_bytes(_canonical(second)),
        "changed_paths_between_passes": changed,
        "changed_authorities_between_passes": changed,
        "failures": []
        if not changed
        else [
            PreflightFailure(
                "RP-FIX-001", "release preflight did not converge on its second pass"
            ).as_dict()
        ],
    }


def installed_equivalence(root: Path, artifact: Path | None = None) -> dict[str, Any]:
    from .evidence_index import build_index

    result = build_index(root, artifacts=(() if artifact is None else (artifact,)))
    installed_prefixes = (
        "vsix version mismatch:",
        "no exact vsix artifact",
        "no indexed vsix",
        "the exact engine identity",
        "required win32 installed-vsix",
        "required linux installed-vsix",
        "windows and linux installed-host",
    )
    relevant = [
        reason
        for reason in result.get("blocking_reasons", ())
        if str(reason).casefold().startswith(installed_prefixes)
    ]
    installed_records = [
        record
        for record in result.get("records", ())
        if record.get("kind") == "installed-vsix-smoke"
    ]
    platforms = {record.get("platform") for record in installed_records}
    valid = (
        result.get("engine_identity", {}).get("valid") is True
        and platforms == {"win32", "linux"}
        and all(record.get("artifact_bound") is True for record in installed_records)
        and not relevant
    )
    return {
        "schema_version": "px.installed-equivalence-preflight/1.0",
        "valid": valid,
        "artifact": artifact.name if artifact else None,
        "blocking_reasons": relevant,
        "limitations": result.get("limitations", []),
        "failures": []
        if valid
        else [
            PreflightFailure(
                "RP-INS-001",
                "installed-host evidence is not bound to the current engine identity",
            ).as_dict()
        ],
    }


def _implementation_digest(root: Path) -> str:
    paths = [
        root / "runtime/release_preflight.py",
        root / "runtime/release_certification.py",
        root / PREFLIGHT_POLICY,
    ]
    return _sha_bytes(b"".join(path.read_bytes() for path in paths if path.is_file()))


def _node_version() -> str | None:
    try:
        completed = subprocess.run(
            ["node", "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout.strip() if completed.returncode == 0 else None


def _binding(root: Path, release: str, artifact: Path | None) -> dict[str, Any]:
    product = classify_tree(root)
    engine = validate_engine_identity(root)
    git = capture_git_identity(root, version=release)
    policy_path = root / PREFLIGHT_POLICY
    topology = root / "registry/test_group_index.json"
    return {
        "release": release,
        "source_revision": git.get("commit_sha"),
        "source_identity_valid": git.get("valid") is True,
        "product_digest": product.get("product_digest"),
        "product_valid": product.get("valid") is True,
        "engine_identity": engine.get("tree_sha256"),
        "engine_manifest_sha256": engine.get("manifest_sha256"),
        "engine_valid": engine.get("valid") is True,
        "policy_digest": _sha_bytes(policy_path.read_bytes()),
        "implementation_digest": _implementation_digest(root),
        "artifact_sha256": _sha_bytes(artifact.read_bytes()) if artifact else None,
        "platform": platform.system().casefold(),
        "python": platform.python_version(),
        "node": _node_version(),
        "test_topology_digest": _sha_bytes(topology.read_bytes())
        if topology.is_file()
        else None,
    }


def receipt_path(root: Path, release: str) -> Path:
    return root / RECEIPT_ROOT / release / "receipt.json"


def _cache_inputs(name: str, binding: Mapping[str, Any]) -> dict[str, Any]:
    common = ("release", "implementation_digest", "platform", "python")
    by_check = {
        "clean_boundary": ("product_digest", "engine_identity", "policy_digest"),
        "clean_rebuild_equivalence": (
            "product_digest",
            "engine_identity",
            "policy_digest",
            "test_topology_digest",
        ),
        "mutation_stability": ("product_digest", "engine_identity", "policy_digest"),
        "transaction_simulation": ("product_digest", "policy_digest"),
        "installed_equivalence": (
            "engine_identity",
            "engine_manifest_sha256",
            "artifact_sha256",
            "node",
        ),
        "concurrency_stress": (),
        "fixed_point": (
            "product_digest",
            "engine_identity",
            "policy_digest",
            "test_topology_digest",
        ),
    }
    return {key: binding.get(key) for key in (*common, *by_check[name])}


def _cache_path(root: Path, name: str, inputs: Mapping[str, Any]) -> Path:
    digest = _sha_bytes(_canonical({"check": name, "inputs": inputs}))
    return root / CACHE_ROOT / name / f"{digest}.json"


def validate_preflight_receipt(
    root: Path, release: str | None = None
) -> dict[str, Any]:
    root = root.resolve()
    release = release or authoritative_version(root)
    path = receipt_path(root, release)
    if not path.is_file():
        return {
            "valid": False,
            "ready_for_certification": False,
            "code": "RELEASE_PREFLIGHT_REQUIRED",
            "errors": ["FINALIZATION_DENIED: RELEASE_PREFLIGHT_REQUIRED"],
        }
    try:
        stored = _json(path)
        current = _binding(root, release, None)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return {
            "valid": False,
            "ready_for_certification": False,
            "code": "RELEASE_PREFLIGHT_REQUIRED",
            "errors": [
                f"preflight receipt is unreadable: {type(error).__name__}: {error}"
            ],
        }
    expected = stored.get("binding", {})
    sealed = dict(stored)
    recorded_sha256 = str(sealed.pop("receipt_sha256", ""))
    receipt_integrity = recorded_sha256 == _sha_bytes(_canonical(sealed))
    keys = (
        "release",
        "source_revision",
        "product_digest",
        "engine_identity",
        "engine_manifest_sha256",
        "policy_digest",
        "implementation_digest",
        "platform",
        "python",
        "node",
        "test_topology_digest",
    )
    mismatches = [key for key in keys if expected.get(key) != current.get(key)]
    valid = (
        stored.get("valid") is True
        and stored.get("ready_for_certification") is True
        and not mismatches
        and receipt_integrity
        and current["source_identity_valid"]
        and current["product_valid"]
        and current["engine_valid"]
    )
    return {
        "valid": valid,
        "ready_for_certification": valid,
        "receipt": path.relative_to(root).as_posix(),
        "mismatches": mismatches,
        "receipt_integrity": receipt_integrity,
        "errors": [] if valid else ["FINALIZATION_DENIED: RELEASE_PREFLIGHT_REQUIRED"],
    }


def record_coverage_gap(
    root: Path, *, finalizer_gate: str, failure_class: str, product_digest: str
) -> Path:
    root = root.resolve()
    release = authoritative_version(root)
    binding = _binding(root, release, None)
    record = {
        "schema_version": "px.release-preflight-coverage-gap/1.0",
        "type": "release_preflight_coverage_gap",
        "status": "open",
        "finalizer_gate": finalizer_gate,
        "failure_class": failure_class,
        "source_revision": binding["source_revision"],
        "product_digest": product_digest,
        "preflight_implementation_digest": binding["implementation_digest"],
        "detected_by_preflight": False,
        "required_action": "add upstream detector and regression before retry",
        "recorded_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    identifier = _sha_bytes(_canonical(record))[:20]
    path = root / COVERAGE_GAP_ROOT / f"{identifier}.json"
    _atomic_json(path, record)
    return path


def run_preflight(
    root: Path,
    *,
    release: str | None = None,
    artifact: Path | None = None,
    deep: bool = False,
    write_receipt: bool = True,
) -> dict[str, Any]:
    """Run cheap checks first, then clean-stage state transitions and fixed point."""
    started = time.monotonic()
    root = root.resolve(strict=True)
    release = release or authoritative_version(root)
    artifact = artifact.resolve(strict=True) if artifact else None
    policy = _json(root / PREFLIGHT_POLICY)
    binding = _binding(root, release, artifact)
    checks: dict[str, dict[str, Any]] = {}
    timings: list[dict[str, object]] = []
    transitions: list[dict[str, object]] = []

    def phase(name: str, callback: Callable[[], dict[str, Any]]) -> bool:
        phase_started = time.monotonic()
        result = callback()
        checks[name] = result
        timings.append(
            {
                "phase": name,
                "elapsed_ms": round((time.monotonic() - phase_started) * 1000, 3),
                "cache_hit": False,
            }
        )
        return bool(result.get("valid"))

    static = [
        (
            "generated_dependency_dag",
            lambda: generated_dependency_graph(policy["generated_authorities"]),
        ),
        (
            "feedback_audit",
            lambda: feedback_audit(root, policy["post_certification_writes"]),
        ),
        ("evidence_portability", lambda: evidence_portability(root)),
        ("evidence_budget", lambda: evidence_budget(root, policy)),
        ("skip_policy", lambda: skip_policy_preflight()),
    ]
    for name, callback in static:
        if not phase(name, callback):
            break
    expensive_names = (
        "clean_boundary",
        "clean_rebuild_equivalence",
        "mutation_stability",
        "transaction_simulation",
        "installed_equivalence",
        "concurrency_stress",
        "fixed_point",
    )
    if all(result.get("valid") for result in checks.values()):
        for name in expensive_names:
            inputs = _cache_inputs(name, binding)
            cached_path = _cache_path(root, name, inputs)
            if not cached_path.is_file():
                continue
            try:
                candidate = _json(cached_path)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            result = candidate.get("check")
            if (
                candidate.get("valid") is True
                and candidate.get("inputs") == inputs
                and isinstance(result, dict)
                and result.get("valid") is True
            ):
                checks[name] = result
                timings.append({"phase": name, "elapsed_ms": 0.0, "cache_hit": True})

    if all(result.get("valid") for result in checks.values()) and any(
        name not in checks for name in expensive_names
    ):
        run_id = f"release-preflight-{uuid4().hex}"
        manager = ResourceManager(root / RESOURCE_REGISTRY)
        allowed = Path(tempfile.gettempdir()) / "pacify-x-release-preflight"
        allowed.mkdir(parents=True, exist_ok=True)
        workspace = manager.create_workspace(
            allowed,
            project_id=root.name,
            run_id=run_id,
            lane_id="clean-product",
            creator="release-preflight",
            prefix="candidate-",
        )
        work = Path(str(workspace.path))
        clean = work / "product"
        rebuild = work / "rebuild"
        clean_names = {
            "clean_boundary",
            "clean_rebuild_equivalence",
            "mutation_stability",
            "transaction_simulation",
            "fixed_point",
        }
        clean_required = any(name not in checks for name in clean_names)
        try:
            if clean_required:
                copy_clean_product(root, clean)
            if "clean_boundary" not in checks:
                phase(
                    "clean_boundary",
                    lambda: require_stable_source_binding(
                        audit_clean_boundary(root, clean), binding["product_digest"]
                    ),
                )
            if (
                all(result.get("valid") for result in checks.values())
                and "clean_rebuild_equivalence" not in checks
            ):
                phase(
                    "clean_rebuild_equivalence",
                    lambda: rebuild_equivalence(
                        clean, rebuild, policy["rebuild_authorities"]
                    ),
                )
            if (
                all(result.get("valid") for result in checks.values())
                and "mutation_stability" not in checks
            ):
                phase(
                    "mutation_stability",
                    lambda: mutation_probe(
                        clean,
                        (
                            lambda candidate: classify_tree(candidate),
                            lambda candidate: build_engine_identity(candidate),
                        ),
                    ),
                )
            if (
                all(result.get("valid") for result in checks.values())
                and "transaction_simulation" not in checks
            ):
                phase(
                    "transaction_simulation",
                    lambda: transaction_simulation(
                        clean, work / "transaction-simulation"
                    ),
                )
            if (
                all(result.get("valid") for result in checks.values())
                and "installed_equivalence" not in checks
            ):
                phase(
                    "installed_equivalence",
                    lambda: installed_equivalence(root, artifact),
                )
            if (
                all(result.get("valid") for result in checks.values())
                and "concurrency_stress" not in checks
            ):
                phase(
                    "concurrency_stress",
                    lambda: concurrency_stress(
                        work / "concurrency",
                        iterations=int(policy["concurrency_iterations"])
                        * (5 if deep else 1),
                        seed=12345,
                    ),
                )
            if (
                all(result.get("valid") for result in checks.values())
                and "fixed_point" not in checks
            ):
                phase(
                    "fixed_point",
                    lambda: fixed_point(clean, policy["rebuild_authorities"]),
                )
            manager.mark_run_ended(
                run_id,
                RunState.COMPLETED
                if all(result.get("valid") for result in checks.values())
                else RunState.FAILED,
            )
        except BaseException:
            manager.mark_run_ended(run_id, RunState.FAILED)
            raise
        finally:
            manager.reclaim(
                workspace.resource_id,
                reason="release preflight clean-stage lifecycle closed",
                apply=True,
            )
        for name in expensive_names:
            if checks.get(name, {}).get("valid") is not True:
                continue
            inputs = _cache_inputs(name, binding)
            _atomic_json(
                _cache_path(root, name, inputs),
                {
                    "schema_version": "px.release-preflight-cache/1.1",
                    "valid": True,
                    "inputs": inputs,
                    "check": checks[name],
                },
            )

    if checks.get("clean_boundary"):
        boundary = checks["clean_boundary"]
        rebuild_check = checks.get("clean_rebuild_equivalence", {})
        transaction = checks.get("transaction_simulation", {})
        installed = checks.get("installed_equivalence", {})
        source_digest = boundary.get("digest_comparison", {}).get("source")
        clean_digest = boundary.get("digest_comparison", {}).get("clean")
        common_transition = {
            "files_removed": [],
            "files_changed": [],
            "authority_changed": False,
            "identity_changed": False,
        }
        transitions = [
            {
                **common_transition,
                "from": "S0_live_repository",
                "to": "S1_clean_exported_product",
                "files_added": [],
                "product_digest_before": source_digest,
                "product_digest_after": clean_digest,
                "identity_changed": source_digest != clean_digest,
            },
            {
                **common_transition,
                "from": "S1_clean_exported_product",
                "to": "S2_frozen_classified_product",
                "files_added": [],
                "generated_projection_changes": rebuild_check.get("different", []),
                "authority_changed": bool(rebuild_check.get("different")),
            },
            {
                **common_transition,
                "from": "S2_frozen_classified_product",
                "to": "S3_built_distributable_artifact",
                "files_added": [artifact.name] if artifact else [],
                "artifact_digest": binding["artifact_sha256"],
                "simulated": artifact is None,
            },
            {
                **common_transition,
                "from": "S3_built_distributable_artifact",
                "to": "S4_exact_installed_artifact",
                "files_added": [],
                "installed_identity_valid": installed.get("valid") is True,
            },
            {
                **common_transition,
                "from": "S4_exact_installed_artifact",
                "to": "S5_installed_frozen_tests",
                "files_added": [],
                "installed_test_evidence_current": installed.get("valid") is True,
            },
            {
                **common_transition,
                "from": "S5_installed_frozen_tests",
                "to": "S6_release_evidence_generated",
                "files_added": transaction.get("simulated_outputs", [])[:1],
                "evidence_changes": transaction.get("simulated_outputs", [])[:1],
                "product_digest_before": transaction.get("product_digest_before"),
                "product_digest_after": transaction.get("product_digest_after"),
            },
            {
                **common_transition,
                "from": "S6_release_evidence_generated",
                "to": "S7_certificate_evidence_published",
                "files_added": transaction.get("simulated_outputs", [])[1:2],
                "evidence_changes": transaction.get("simulated_outputs", [])[1:2],
                "published_authoritatively": False,
            },
            {
                **common_transition,
                "from": "S7_certificate_evidence_published",
                "to": "S8_post_cert_runtime_state",
                "files_added": transaction.get("simulated_outputs", [])[2:],
                "runtime_state_changes": transaction.get("simulated_outputs", [])[2:],
                "published_authoritatively": False,
            },
        ]

    failures = [
        failure for result in checks.values() for failure in result.get("failures", ())
    ]
    valid = (
        not failures
        and checks
        and all(result.get("valid") for result in checks.values())
        and binding["source_identity_valid"]
        and binding["product_valid"]
        and binding["engine_valid"]
        and checks.get("fixed_point", {}).get("fixed_point") is True
    )
    if not binding["source_identity_valid"]:
        failures.append(
            {
                "code": "RP-BND-002",
                "message": "source revision is not clean, tagged, and release-bound",
            }
        )
    if not binding["engine_valid"]:
        failures.append(
            {"code": "RP-GEN-001", "message": "engine identity projection is stale"}
        )
    result = {
        "schema_version": "px.release-preflight/1.0",
        "valid": valid,
        "ready_for_certification": valid,
        "binding": binding,
        "checks": checks,
        "blocking_reasons": failures,
        "warnings": [],
        "phase_timings": timings,
        "state_transitions": transitions,
        "skipped_phases": [
            name
            for name in (
                "clean_boundary",
                "clean_rebuild_equivalence",
                "mutation_stability",
                "transaction_simulation",
                "installed_equivalence",
                "concurrency_stress",
                "fixed_point",
            )
            if name not in checks
        ],
        "elapsed_seconds": round(time.monotonic() - started, 6),
    }
    verdict = (
        "READY_FOR_CERTIFICATION = TRUE" if valid else "READY_FOR_CERTIFICATION = FALSE"
    )
    result["summary"] = {
        "verdict": verdict,
        "passed": sorted(
            name for name, check in checks.items() if check.get("valid") is True
        ),
        "failed": sorted(
            name for name, check in checks.items() if check.get("valid") is not True
        ),
        "blocked_finalizer": not valid,
    }
    result["receipt_sha256"] = _sha_bytes(_canonical(result))
    if write_receipt:
        _atomic_json(receipt_path(root, release), result)
    return result


def run_dry_run(
    root: Path, *, release: str | None = None, artifact: Path | None = None
) -> dict[str, Any]:
    result = run_preflight(
        root, release=release, artifact=artifact, deep=False, write_receipt=False
    )
    return {
        **result,
        "schema_version": "px.release-transaction-dry-run/1.0",
        "signed": False,
        "published": False,
    }


def run_discovery(
    root: Path, *, release: str | None = None, artifact: Path | None = None
) -> dict[str, Any]:
    result = run_preflight(
        root, release=release, artifact=artifact, deep=True, write_receipt=False
    )
    return {
        **result,
        "schema_version": "px.release-discovery/1.0",
        "signed": False,
        "published": False,
        "mode": "deep",
    }
