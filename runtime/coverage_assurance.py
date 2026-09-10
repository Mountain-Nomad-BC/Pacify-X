"""Validate executed branch coverage against safety-class thresholds."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


def validate_coverage_evidence(root: Path, coverage_json: Path) -> dict[str, Any]:
    from .input_files import independent_file, cooperative_deadline, read_file_image
    from .json_io import decode_json_object

    try:
        if type(root) is not type(Path()):
            raise ValueError("coverage root must be an actual filesystem path")
        deadline = cooperative_deadline()
        # Preflight both declared inputs before either body acquisition.
        policy_path, policy_info = independent_file(
            root / "policies/coverage-assurance.json"
        )
        coverage_path, coverage_info = independent_file(coverage_json)
        if (
            policy_info.st_size > 1024 * 1024
            or coverage_info.st_size > 64 * 1024 * 1024
        ):
            raise ValueError("coverage input byte budget exhausted before acquisition")
        policy_image = read_file_image(
            policy_path, policy_info, limit=1024 * 1024, deadline=deadline
        )
        policy_sha256 = hashlib.sha256(policy_image).hexdigest()
        policy = decode_json_object(
            policy_image, max_bytes=1024 * 1024, max_depth=64, max_nodes=100000
        )
        del policy_image
        coverage_image = read_file_image(
            coverage_path, coverage_info, limit=64 * 1024 * 1024, deadline=deadline
        )
        coverage_sha256 = hashlib.sha256(coverage_image).hexdigest()
        coverage = decode_json_object(
            coverage_image, max_bytes=64 * 1024 * 1024, max_depth=64, max_nodes=1000000
        )
        del coverage_image
        return _evaluate_coverage_images(
            policy, coverage, policy_sha256, coverage_sha256
        )
    except (
        OSError,
        ValueError,
        TypeError,
        AttributeError,
        OverflowError,
        RecursionError,
    ):
        return {
            "schema_version": "1.0",
            "valid": False,
            "coverage_sha256": None,
            "policy_sha256": None,
            "classes": {},
            "exemption_count": None,
            "errors": ["coverage inputs are invalid or unavailable"],
        }


def _evaluate_coverage_images(policy, coverage, policy_sha256, coverage_sha256):
    errors: list[str] = []
    meta = coverage.get("meta", {})
    if (
        policy.get("branch_required") is True
        and meta.get("branch_coverage") is not True
    ):
        errors.append("coverage evidence does not include branch coverage")
    if policy.get("dynamic_context_required") is True and not meta.get("show_contexts"):
        errors.append("coverage evidence does not include dynamic test contexts")
    exemptions = policy.get("exemptions", [])
    if not isinstance(exemptions, list):
        errors.append("coverage exemptions must be a list")
        exemptions = []
    for exemption in exemptions:
        if (
            not isinstance(exemption, dict)
            or not all(
                str(exemption.get(field, "")).strip()
                for field in ("module", "owner", "reason")
            )
            or not exemption.get("branches")
        ):
            errors.append(
                "coverage exemption requires module, owner, reason, and branches"
            )
    files = {
        str(path).replace("\\", "/"): value
        for path, value in coverage.get("files", {}).items()
    }
    classes: dict[str, object] = {}
    for class_name, rule in policy.get("classes", {}).items():
        modules = rule.get("modules", [])
        minimum = float(rule.get("minimum_branch_percent", 0))
        results = []
        class_total = 0
        class_missing = 0
        for module in modules:
            candidates = [
                value
                for path, value in files.items()
                if path == module or path.endswith("/" + module)
            ]
            if len(candidates) != 1:
                errors.append(f"{class_name}: executed coverage missing for {module}")
                continue
            summary = candidates[0].get("summary", {})
            contexts = candidates[0].get("contexts", {})
            if policy.get("dynamic_context_required") is True and not isinstance(
                contexts, dict
            ):
                errors.append(
                    f"{class_name}: dynamic test contexts missing for {module}"
                )
            elif policy.get("dynamic_context_required") is True and not any(
                isinstance(names, list) and any(str(name).strip() for name in names)
                for names in contexts.values()
            ):
                errors.append(
                    f"{class_name}: dynamic test contexts are empty for {module}"
                )
            total = int(summary.get("num_branches", 0))
            missing = int(summary.get("missing_branches", 0))
            percent = (
                100.0 if total == 0 else round((total - missing) * 100.0 / total, 2)
            )
            results.append(
                {
                    "module": module,
                    "branches": total,
                    "missing": missing,
                    "branch_percent": percent,
                }
            )
            class_total += total
            class_missing += missing
        class_percent = (
            100.0
            if class_total == 0
            else round((class_total - class_missing) * 100.0 / class_total, 2)
        )
        class_valid = len(results) == len(modules) and class_percent >= minimum
        if len(results) == len(modules) and class_percent < minimum:
            errors.append(
                f"{class_name}: aggregate branch coverage {class_percent}% is below {minimum}%"
            )
        classes[class_name] = {
            "minimum_branch_percent": minimum,
            "branch_percent": class_percent,
            "branches": class_total,
            "missing": class_missing,
            "modules": results,
            "valid": class_valid,
        }
    return {
        "schema_version": "1.0",
        "valid": not errors,
        "coverage_sha256": coverage_sha256,
        "policy_sha256": policy_sha256,
        "classes": classes,
        "exemption_count": len(exemptions),
        "errors": errors,
    }
