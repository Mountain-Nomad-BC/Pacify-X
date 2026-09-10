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
from .release_repository_context import validate_release_gate_repository_context


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
    source_product_valid = source_product.get(
        "product_valid", source_product.get("valid")
    )
    if not source_product_valid:
        failures.append(
            PreflightFailure("RP-BND-002", "live product inputs are invalid")
        )
    if not clean_product.get("valid"):
        failures.append(
            PreflightFailure(
                "RP-BND-002", "clean export contains invalid or unclassified content"
            )
        )
    if source_product.get("product_digest") != clean_product.get("product_digest"):
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
        "source_classifier_errors": list(source_product.get("errors", ())),
        "clean_classifier_errors": list(clean_product.get("errors", ())),
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


def _preflight_product_records(root: Path, *, deadline: float) -> tuple[dict, ...]:
    """Validate consumed classifier fields; classification remains its own owner."""
    from .archive_io import member_identity
    from .input_files import check_deadline, relative_source_path

    check_deadline(deadline)
    result = classify_tree(root)
    check_deadline(deadline)
    if (type(result) is not dict or len(result) > 64
            or result.get("valid") is not True or result.get("product_valid") is not True
            or type(result.get("errors")) is not list or result["errors"]):
        raise ValueError("release product classification is invalid or incomplete")
    rows = result.get("product_records")
    if type(rows) is not list or len(rows) > 250000:
        raise ValueError("release product record denominator is invalid or oversized")
    prepared = []
    aliases = set()
    path_bytes = total_bytes = 0
    for row in rows:
        check_deadline(deadline)
        if type(row) is not dict or len(row) > 8:
            raise ValueError("release product record must be a bounded actual object")
        relative = relative_source_path(row.get("path"))
        identity = member_identity(relative, allow_directory=False)
        if identity in aliases:
            raise ValueError("release product path identity is ambiguous")
        aliases.add(identity)
        size = row.get("size")
        digest = row.get("sha256")
        if type(size) is not int or not 0 <= size <= 64 * 1024**3:
            raise ValueError("release product bytes must be a bounded actual integer")
        if type(digest) is not str or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("release product digest is invalid")
        path_bytes += len(relative.encode("utf-8"))
        total_bytes += size
        if path_bytes > 64 * 1024**2 or total_bytes > 64 * 1024**3:
            raise ValueError("release product metadata exceeds its aggregate budget")
        prepared.append({"path": relative, "size": size, "sha256": digest})
    return tuple(prepared)


def _preflight_feedback_targets(root: Path, targets: object, *, deadline: float) -> tuple[tuple[str, str, str], ...]:
    """Admit original contained future paths without creating or authorizing them."""
    import stat
    from .archive_io import member_identity, reject_path_links
    from .input_files import check_deadline, relative_source_path
    from .numeric_inputs import bounded_text

    if type(targets) not in (list, tuple) or len(targets) > 1024:
        raise ValueError("feedback targets must be an actual bounded list or tuple")
    targets = tuple(targets)
    prepared = []
    aliases = set()
    placeholders = {"<release>": "release", "<run-id>": "run"}
    for target in targets:
        check_deadline(deadline)
        normalized = bounded_text(target, "feedback target", maximum=4096, strip=False).replace("\\", "/")
        concrete = "/".join(placeholders.get(part, part) for part in normalized.split("/"))
        concrete = relative_source_path(concrete)
        if len(concrete.split("/")) > 128:
            raise ValueError("feedback target exceeds release path depth")
        identity = member_identity(concrete, allow_directory=False)
        if identity in aliases:
            raise ValueError("feedback target identity is duplicated or ambiguous")
        aliases.add(identity)
        original = root / concrete
        reject_path_links(original)
        if not original.resolve(strict=False).is_relative_to(root):
            raise ValueError("feedback target escapes the admitted project root")
        cursor = original
        while cursor != root:
            check_deadline(deadline)
            try:
                info = cursor.lstat()
            except FileNotFoundError:
                cursor = cursor.parent
                continue
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
                raise ValueError("linked feedback path is not admitted")
            if cursor == original:
                if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
                    raise ValueError("feedback target has unsupported filesystem type")
                if stat.S_ISREG(info.st_mode) and info.st_nlink > 1:
                    raise ValueError("feedback target aliases another file identity")
            elif not stat.S_ISDIR(info.st_mode):
                raise ValueError("feedback target parent is not a directory")
            cursor = cursor.parent
        prepared.append((normalized, concrete, identity))
    return tuple(prepared)


def _release_input_limits(policy):
    from .numeric_inputs import bounded_integer, bounded_mapping, finite_number

    policy = bounded_mapping(policy, "release input policy", maximum=64)
    return {
        "total": bounded_integer(policy.get("max_total_release_evidence_bytes"), "total evidence bytes", maximum=1024**3),
        "single": bounded_integer(policy.get("max_single_evidence_file_bytes"), "single evidence bytes", maximum=256 * 1024**2),
        "amplification": finite_number(policy.get("max_context_amplification_ratio", 20.0), "context amplification", minimum=0, maximum=1000000),
    }


def _bounded_release_evidence_inventory(root, *, deadline):
    """One selected metadata inventory; version/config reads are separate inputs."""
    import stat
    import time
    from .archive_io import member_identity, reject_path_links
    from .bounded_walk import WalkLimits, bounded_walk
    from .input_files import check_deadline, contained_file, directory_root
    from .release_identity import authoritative_version

    root = directory_root(root)
    check_deadline(deadline)
    original_project = root / "pyproject.toml"
    reject_path_links(original_project)
    try:
        project_info = original_project.lstat()
    except FileNotFoundError:
        groups = [(root / "evidence", False)]
    else:
        if not stat.S_ISREG(project_info.st_mode):
            raise ValueError("release version source must be a regular file")
        groups = [(root / "evidence/releases" / authoritative_version(root), True)]
    groups.append((root / "extension/evidence", False))
    selected = []
    aliases = set()
    physical = set()
    file_count = directory_count = entry_count = total_bytes = 0
    custody = {"quarantine", ".quarantine", "_quarantine", "repo_quarantine"}
    for original, recursive in groups:
        check_deadline(deadline)
        reject_path_links(original)
        try:
            group_info = original.lstat()
        except FileNotFoundError:
            continue
        if not stat.S_ISDIR(group_info.st_mode):
            raise ValueError("release evidence root must be a directory")
        group = directory_root(original)
        if not group.is_relative_to(root):
            raise ValueError("release evidence root escapes the admitted project")

        def excluded(relative):
            if any(part.casefold() in custody for part in relative.split("/")):
                return True
            if recursive:
                return False
            # Shallow evidence does not descend into unrelated directories.
            # Links/reparse points remain visible to the walker's refusal gate.
            info = (group / relative).lstat()
            return stat.S_ISDIR(info.st_mode) and not (
                getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            )

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError("release evidence metadata deadline expired")
        walk = bounded_walk(group, limits=WalkLimits(
            max_files=max(1, 10000 - file_count),
            max_directories=max(1, 10000 - directory_count),
            max_entries=max(1, 20000 - entry_count), max_depth=128,
            max_bytes=max(1, 1024**3 - total_bytes), max_duration_seconds=remaining,
        ), exclude=excluded)
        file_count += walk.file_count
        directory_count += walk.directory_count
        entry_count += walk.scanned_entries
        total_bytes += walk.total_bytes
        if file_count > 10000 or directory_count > 10000 or entry_count > 20000 or total_bytes > 1024**3:
            raise ValueError("release evidence metadata exceeds aggregate limits")
        for entry in walk.files:
            check_deadline(deadline)
            relative = entry.path.relative_to(root).as_posix()
            identity = member_identity(relative, allow_directory=False)
            if identity in aliases:
                raise ValueError("release evidence portable identity is ambiguous")
            aliases.add(identity)
            path, info = contained_file(root, relative)
            if info.st_size != entry.size:
                raise ValueError("release evidence changed during metadata admission")
            file_id = (info.st_dev, info.st_ino)
            if info.st_ino and file_id in physical:
                raise ValueError("release evidence paths alias one file identity")
            physical.add(file_id)
            selected.append((relative, path, info))
    check_deadline(deadline)
    return {
        "root": root,
        "entries": tuple(sorted(selected, key=lambda row: (row[0].casefold(), row[0]))),
        "total_bytes": total_bytes,
        "file_count": file_count,
        "directory_count": directory_count,
        "scanned_entries": entry_count,
        "deadline": deadline,
    }


def load_preflight_input_policy(root: Path, *, required: bool = True) -> dict:
    from .input_files import cooperative_deadline, directory_root, contained_file, read_file_image
    from .json_io import decode_json_object

    if type(required) is not bool:
        raise ValueError("policy required flag must be an actual boolean")
    deadline = cooperative_deadline()
    root = directory_root(root)
    try:
        path, info = contained_file(root, "policies/release-preflight.json")
    except FileNotFoundError:
        if required:
            raise ValueError("release preflight policy is missing") from None
        return {"schema_version": "px.release-preflight-policy/1.0",
                "max_total_release_evidence_bytes": 250 * 1024**2,
                "max_single_evidence_file_bytes": 100 * 1024**2,
                "max_context_amplification_ratio": 20.0}
    result = decode_json_object(read_file_image(path, info, limit=1024 * 1024, deadline=deadline), max_bytes=1024 * 1024, max_depth=32, max_nodes=100000)
    if result.get("schema_version") != "px.release-preflight-policy/1.0":
        raise ValueError("release preflight policy schema version is unsupported")
    return result


def _release_input_failure(kind: str) -> dict:
    schemas = {"portability": "px.release-evidence-portability-preflight/1.0", "budget": "px.release-evidence-budget/1.0"}
    result = {"schema_version": schemas[kind], "valid": False,
              "failures": [PreflightFailure("RP-EVD-001" if kind == "portability" else "RP-EVD-002",
                  "release evidence input is invalid, changed, oversized or incompletely evaluated").as_dict()]}
    if kind == "portability":
        result.update(finding_count=None, findings=[], scan_complete=False)
    else:
        result.update(total_bytes=None, file_count=None, source_bytes=None,
                      context_amplification_ratio=None, amplification_evaluated=False,
                      top_contributors=[], oversized_files=[])
    return result


class _ReleasePreflightInputs:
    """One private request's consumed declarations and selected evidence metadata.

    This creates no authority, persistent cache or cross-file snapshot. Construction
    is pure; actual classification and evidence acquisition remain lazy.
    """

    def __init__(self, root: Path, policy=None):
        self.original_root = root
        self.policy_input = dict(policy) if type(policy) is dict and len(policy) <= 64 else policy
        self.root = None
        self.deadline = None
        self.limits = None
        self.inventory = None
        self.product_records = None
        self.product_failed = False

    def start(self):
        from .input_files import check_deadline, cooperative_deadline, directory_root

        if self.deadline is None:
            deadline = cooperative_deadline()
            root = directory_root(self.original_root)
            self.root, self.deadline = root, deadline
        check_deadline(self.deadline)

    def products(self):
        self.start()
        if self.product_failed:
            raise ValueError("release product classification previously failed")
        if self.product_records is None:
            try:
                self.product_records = _preflight_product_records(self.root, deadline=self.deadline)
            except (OSError, ValueError, TypeError):
                self.product_failed = True
                raise
        return self.product_records

    def selected(self):
        # Supplied byte policy is admitted before evidence metadata acquisition.
        if self.limits is None:
            policy = self.policy_input
            if policy is None:
                self.start()
                policy = load_preflight_input_policy(self.root, required=False)
            self.limits = _release_input_limits(policy)
        self.start()
        if self.inventory is None:
            self.inventory = _bounded_release_evidence_inventory(self.root, deadline=self.deadline)
        return self.inventory

    def verify_selected_metadata(self):
        from .input_files import check_deadline, contained_file

        for relative, _, expected in self.selected()["entries"]:
            check_deadline(self.deadline)
            _, current = contained_file(self.root, relative)
            if (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns) != (
                expected.st_dev, expected.st_ino, expected.st_size, expected.st_mtime_ns
            ):
                raise ValueError("selected release evidence metadata changed")
        check_deadline(self.deadline)

    def sizing(self):
        inventory = self.selected()
        files = [{"path": relative, "bytes": info.st_size} for relative, _, info in inventory["entries"]]
        files.sort(key=lambda row: (-row["bytes"], row["path"]))
        oversized = [row for row in files if row["bytes"] > self.limits["single"]]
        return {"total_bytes": inventory["total_bytes"], "file_count": len(files),
                "maximum_total_bytes": self.limits["total"], "maximum_single_file_bytes": self.limits["single"],
                "top_contributors": files[:20], "oversized_files": oversized[:256],
                "oversized_file_count": len(oversized), "oversized_files_truncated": len(oversized) > 256}

    def feedback(self, write_targets):
        from .archive_io import member_identity
        from .input_files import check_deadline

        try:
            self.start()
            targets = _preflight_feedback_targets(self.root, write_targets, deadline=self.deadline)
            products = {member_identity(row["path"], allow_directory=False) for row in self.products()}
            check_deadline(self.deadline)
        except (OSError, ValueError, TypeError):
            return {"schema_version": "px.release-feedback-audit/1.0", "valid": False,
                    "writes": [], "illegal_feedback_targets": [],
                    "failures": [PreflightFailure("RP-FBK-002", "feedback input, physical path or product classification is invalid or incomplete").as_dict()]}
        writes = []
        illegal = []
        for normalized, concrete, identity in targets:
            if identity in products:
                kind = "generated_product"
            elif concrete.startswith("evidence/"):
                kind = "release_transaction_evidence"
            elif concrete.startswith(".engineering-bootstrap/runtime-core/"):
                kind = "post_cert_runtime_state"
            elif concrete.startswith(".engineering-bootstrap/"):
                kind = "temporary_workspace"
            else:
                kind = "unknown"
            if kind in {"generated_product", "unknown"}:
                illegal.append(normalized)
            writes.append({"path": normalized, "classification": kind})
        return {"schema_version": "px.release-feedback-audit/1.0", "valid": not illegal,
                "writes": writes, "illegal_feedback_targets": illegal,
                "failures": [] if not illegal else [PreflightFailure("RP-FBK-001",
                    "post-certification write feeds an immutable or unknown product input: " + ", ".join(illegal)).as_dict()]}

    def portability(self):
        from contextlib import closing
        from .evidence_portability import stream_portability_findings
        from .input_files import check_deadline, iter_file_image

        try:
            inventory = self.selected()
            sizing = self.sizing()
            if sizing["total_bytes"] > self.limits["total"] or sizing["oversized_file_count"]:
                result = _release_input_failure("portability")
                result["byte_budget"] = sizing
                return result
            findings = []
            text_suffixes = {".json", ".jsonl", ".ndjson", ".xml", ".log", ".txt", ".md", ".svg", ".sig"}
            for relative, path, info in inventory["entries"]:
                check_deadline(self.deadline)
                if path.suffix.casefold() not in text_suffixes and path.name != "SHA256SUMS":
                    continue
                with closing(iter_file_image(path, info, limit=self.limits["single"], deadline=self.deadline)) as chunks:
                    values = stream_portability_findings(chunks, deadline=self.deadline)
                if len(findings) + len(values) > 4096:
                    raise ValueError("release portability findings exceed aggregate count")
                findings.extend({"path": relative, "locator": value} for value in values)
            self.verify_selected_metadata()
            return {"schema_version": "px.release-evidence-portability-preflight/1.0", "valid": not findings,
                    "finding_count": len(findings), "findings": findings, "scan_complete": True,
                    "failures": [] if not findings else [PreflightFailure("RP-EVD-001", f"{len(findings)} machine-local evidence locator(s) found").as_dict()]}
        except (OSError, ValueError, TypeError):
            return _release_input_failure("portability")

    def budget(self):
        try:
            sizing = self.sizing()
            products = self.products()
            source_bytes = sum(row["size"] for row in products)
            self.verify_selected_metadata()
            amplification = sizing["total_bytes"] / source_bytes if source_bytes > 0 else None
            valid = (sizing["total_bytes"] <= self.limits["total"] and not sizing["oversized_file_count"]
                     and amplification is not None and amplification <= self.limits["amplification"])
            return {"schema_version": "px.release-evidence-budget/1.0", "valid": valid, **sizing,
                    "source_bytes": source_bytes, "context_amplification_ratio": round(amplification, 6) if amplification is not None else None,
                    "maximum_context_amplification_ratio": self.limits["amplification"], "amplification_evaluated": amplification is not None,
                    "failures": [] if valid else [PreflightFailure("RP-EVD-002", "release evidence budget is exceeded or cannot be evaluated completely").as_dict()]}
        except (OSError, ValueError, TypeError):
            return _release_input_failure("budget")


def _release_input_callbacks(root: Path, policy: dict):
    """Construct callbacks without IO; one invocation owns their lazy input view."""
    inputs = _ReleasePreflightInputs(root, policy)
    targets = policy.get("post_certification_writes") if type(policy) is dict else None
    if type(targets) in (list, tuple) and len(targets) <= 1024:
        targets = tuple(targets)
    return [("feedback_audit", lambda: inputs.feedback(targets)),
            ("evidence_portability", inputs.portability), ("evidence_budget", inputs.budget)]


def feedback_audit(root: Path, write_targets: Iterable[str]) -> dict[str, Any]:
    return _ReleasePreflightInputs(root).feedback(write_targets)


def _release_evidence_files(root: Path) -> list[Path]:
    """Return bounded metadata-selected current transaction evidence paths."""
    return [path for _, path, _ in _ReleasePreflightInputs(root).selected()["entries"]]


def evidence_portability(root: Path) -> dict[str, Any]:
    return _ReleasePreflightInputs(root).portability()


def evidence_budget(root: Path, policy: Mapping[str, Any]) -> dict[str, Any]:
    return _ReleasePreflightInputs(root, policy).budget()


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


def certification_group_readiness(root: Path) -> dict[str, Any]:
    """Mirror the whole-certification test-group receipt admission exactly."""
    from .test_profiles import group_status

    status = group_status(root)
    rows = list(status.get("groups", ()))
    stale = [str(row.get("group")) for row in rows if row.get("current") is not True]
    current = [str(row.get("group")) for row in rows if row.get("current") is True]
    valid = status.get("valid") is True and not stale
    return {
        "schema_version": "px.test-group-readiness-preflight/1.0",
        "valid": valid,
        "required_groups": list(status.get("required_groups", ())),
        "current_groups": current,
        "stale_groups": stale,
        "member_count": status.get("member_count", 0),
        "failures": []
        if valid
        else [
            PreflightFailure(
                "RP-TST-001",
                "whole certification requires current test-group receipts: "
                + ", ".join(stale),
            ).as_dict()
        ],
    }


def prepare_release_test_completion_projection(root: Path) -> dict[str, Any]:
    """Publish and verify the exact control projection consumed by release tests."""

    root = root.resolve(strict=True)
    target = root / "registry/completion_status.json"
    try:
        from scripts.build_completion_status import build, write

        published = write(root)
        current = build(root)
        stored = _json(target)
        valid = published == current == stored
        error = None
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as caught:
        published = {}
        current = {}
        stored = {}
        valid = False
        error = f"{type(caught).__name__}: {caught}"
    return {
        "schema_version": "px.release-test-completion-projection/1.0",
        "valid": valid,
        "path": "registry/completion_status.json",
        "projection_sha256": _sha_bytes(_canonical(stored)) if stored else None,
        "complete": bool(current.get("complete")),
        "certified": bool(current.get("certified")),
        "failures": []
        if valid
        else [
            PreflightFailure(
                "RP-TST-002",
                "release-test completion projection could not be published at its execution boundary"
                + (f": {error}" if error else ""),
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
    root = root.resolve(strict=True)
    resolved_artifact: Path | None = None
    artifact_path: str | None = None
    if artifact is not None:
        resolved_artifact = artifact.resolve(strict=True)
        try:
            artifact_path = resolved_artifact.relative_to(root).as_posix()
        except ValueError:
            # An external artifact can be explored, but cannot be rebound by
            # finalization from portable repository state and therefore will
            # fail the exact receipt comparison below.
            artifact_path = None
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
        "product_valid": product.get("product_valid", product.get("valid")) is True,
        "engine_identity": engine.get("tree_sha256"),
        "engine_manifest_sha256": engine.get("manifest_sha256"),
        "engine_valid": engine.get("valid") is True,
        "policy_digest": _sha_bytes(policy_path.read_bytes()),
        "implementation_digest": _implementation_digest(root),
        "artifact_path": artifact_path,
        "artifact_sha256": _sha_bytes(resolved_artifact.read_bytes())
        if resolved_artifact
        else None,
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
        expected = stored.get("binding", {})
        artifact_relative = expected.get("artifact_path")
        artifact: Path | None = None
        if artifact_relative is not None:
            if not isinstance(artifact_relative, str) or not artifact_relative:
                raise ValueError("preflight artifact path is malformed")
            candidate = Path(artifact_relative)
            if candidate.is_absolute() or ".." in candidate.parts:
                raise ValueError("preflight artifact path escapes the repository")
            artifact = (root / candidate).resolve(strict=True)
            artifact.relative_to(root.resolve(strict=True))
        current = _binding(root, release, artifact)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return {
            "valid": False,
            "ready_for_certification": False,
            "code": "RELEASE_PREFLIGHT_REQUIRED",
            "errors": [
                f"preflight receipt is unreadable: {type(error).__name__}: {error}"
            ],
        }
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
        "artifact_path",
        "artifact_sha256",
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
    enforce_release_binding: bool = True,
) -> dict[str, Any]:
    """Run cheap checks first, then clean-stage state transitions and fixed point."""
    from .test_profiles import require_processing_stage
    from .input_files import directory_root

    started = time.monotonic()
    root = directory_root(root)
    # A binding preflight includes exact installed-host equivalence.  It can
    # therefore run only after package, install, and installed operational
    # testing.  Discovery deliberately omits the release binding so repair can
    # still collect a denominator without entering the certification campaign.
    if enforce_release_binding:
        require_processing_stage(root, "certify")
    release = release or authoritative_version(root)
    artifact = artifact.resolve(strict=True) if artifact else None
    policy = load_preflight_input_policy(root)
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
        *_release_input_callbacks(root, policy),
        ("skip_policy", lambda: skip_policy_preflight()),
        (
            "release_gate_repository_context",
            lambda: validate_release_gate_repository_context(root),
        ),
        ("test_group_readiness", lambda: certification_group_readiness(root)),
        (
            "release_test_completion_projection",
            lambda: prepare_release_test_completion_projection(root),
        ),
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

    check_failures = [
        failure for result in checks.values() for failure in result.get("failures", ())
    ]
    checks_valid = bool(
        not check_failures
        and checks
        and all(result.get("valid") for result in checks.values())
        and checks.get("fixed_point", {}).get("fixed_point") is True
    )
    binding_failures = []
    if not binding["source_identity_valid"]:
        binding_failures.append(
            {
                "code": "RP-BND-002",
                "message": "source revision is not clean, tagged, and release-bound",
            }
        )
    if not binding["product_valid"]:
        binding_failures.append(
            {
                "code": "RP-BND-002",
                "message": "live product identity inputs are invalid",
            }
        )
    if not binding["engine_valid"]:
        binding_failures.append(
            {"code": "RP-GEN-001", "message": "engine identity projection is stale"}
        )
    ready_for_certification = checks_valid and not binding_failures
    valid = ready_for_certification if enforce_release_binding else checks_valid
    failures = [
        *check_failures,
        *(binding_failures if enforce_release_binding else ()),
    ]
    warnings = [] if enforce_release_binding else binding_failures
    result = {
        "schema_version": "px.release-preflight/1.0",
        "valid": valid,
        "ready_for_certification": ready_for_certification,
        "binding": binding,
        "checks": checks,
        "blocking_reasons": failures,
        "warnings": warnings,
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
    verdict = "READY_FOR_CERTIFICATION = " + (
        "TRUE" if ready_for_certification else "FALSE"
    )
    result["summary"] = {
        "verdict": verdict,
        "passed": sorted(
            name for name, check in checks.items() if check.get("valid") is True
        ),
        "failed": sorted(
            name for name, check in checks.items() if check.get("valid") is not True
        ),
        "blocked_finalizer": not ready_for_certification,
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
        root,
        release=release,
        artifact=artifact,
        deep=True,
        write_receipt=False,
        enforce_release_binding=False,
    )
    return {
        **result,
        "schema_version": "px.release-discovery/1.0",
        "signed": False,
        "published": False,
        "mode": "deep",
    }
