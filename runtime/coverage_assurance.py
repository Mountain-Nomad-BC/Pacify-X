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
    import math
    from .archive_io import portable_member_name

    errors = []
    classes = {}
    exemptions = []

    def result():
        return {'schema_version': '1.0', 'valid': not errors,
                'coverage_sha256': coverage_sha256, 'policy_sha256': policy_sha256,
                'classes': classes, 'exemption_count': len(exemptions),
                'exemption_semantics': 'declarations-only; no branch or threshold discount',
                'errors': errors}

    if type(policy) is not dict or type(coverage) is not dict:
        errors.append('coverage policy and evidence must be objects')
        return result()
    rules = policy.get('classes')
    if type(rules) is not dict or not 1 <= len(rules) <= 256:
        errors.append('coverage classes must be a nonempty bounded object')
        return result()
    for flag in ('branch_required', 'dynamic_context_required'):
        if type(policy.get(flag)) is not bool:
            errors.append('coverage policy requires explicit boolean ' + flag)
    meta = coverage.get('meta')
    if type(meta) is not dict:
        errors.append('coverage metadata is invalid')
        meta = {}
    if policy.get('branch_required') is True and meta.get('branch_coverage') is not True:
        errors.append('coverage evidence does not include branch coverage')
    if policy.get('dynamic_context_required') is True and meta.get('show_contexts') is not True:
        errors.append('coverage evidence does not include dynamic test contexts')
    raw_files = coverage.get('files')
    files = {}
    if type(raw_files) is not dict or not 1 <= len(raw_files) <= 100000:
        errors.append('coverage files must be a nonempty bounded object')
    else:
        for path, value in raw_files.items():
            if type(path) is not str or not path or len(path.encode('utf-8')) > 4096 or type(value) is not dict:
                errors.append('coverage file record is invalid')
                continue
            normalized = path.replace('\\', '/')
            if normalized in files:
                errors.append('coverage file identity is duplicated: ' + normalized)
            files[normalized] = value
    exemptions = policy.get('exemptions', [])
    if type(exemptions) is not list or len(exemptions) > 10000:
        errors.append('coverage exemptions must be a bounded list')
        exemptions = []
    for exemption in exemptions:
        if (type(exemption) is not dict or
                any(type(exemption.get(key)) is not str or not exemption[key].strip()
                    for key in ('module', 'owner', 'reason')) or
                type(exemption.get('branches')) is not list or not exemption['branches'] or
                any(type(branch) is not int or branch < 1 for branch in exemption['branches'])):
            errors.append('coverage exemption requires module, owner, reason, and branches')
    global_errors = bool(errors)
    for class_name, rule in rules.items():
        local = []
        minimum = None
        modules = []
        if type(class_name) is not str or not class_name.strip() or type(rule) is not dict:
            errors.append('coverage class declaration is invalid')
            continue
        threshold = rule.get('minimum_branch_percent')
        if type(threshold) not in (int, float) or not 0 <= threshold <= 100 or not math.isfinite(threshold):
            local.append('coverage threshold must be finite and between zero and 100')
        else:
            minimum = float(threshold)
        supplied = rule.get('modules')
        if type(supplied) is not list or not 1 <= len(supplied) <= 10000:
            local.append('coverage modules must be a nonempty bounded list')
        else:
            seen = set()
            for module in supplied:
                try:
                    if type(module) is not str or not module or len(module.encode('utf-8')) > 4096:
                        raise ValueError('invalid module')
                    if portable_member_name(module, allow_directory=False) != module or module in seen:
                        raise ValueError('invalid or duplicate module')
                    seen.add(module)
                    modules.append(module)
                except (TypeError, ValueError):
                    local.append('coverage module identity is invalid or duplicated')
        results = []
        class_total = class_missing = 0
        for module in modules:
            candidates = [value for path, value in files.items()
                          if path == module or path.endswith('/' + module)]
            if len(candidates) != 1:
                local.append('executed coverage missing or ambiguous for ' + module)
                continue
            summary = candidates[0].get('summary')
            if type(summary) is not dict:
                local.append('coverage summary missing for ' + module)
                continue
            total, missing = summary.get('num_branches'), summary.get('missing_branches')
            if (type(total) is not int or type(missing) is not int or
                    not 0 <= missing <= total <= 1000000000):
                local.append('coverage branch counts are invalid for ' + module)
                continue
            if 'covered_branches' in summary and (type(summary['covered_branches']) is not int or summary['covered_branches'] != total - missing):
                local.append('covered branch count disagrees for ' + module)
            contexts = candidates[0].get('contexts')
            if policy.get('dynamic_context_required') is True:
                if type(contexts) is not dict or not contexts or not any(
                    type(names) is list and any(type(name) is str and name.strip() for name in names)
                    for names in contexts.values()
                ):
                    local.append('dynamic test contexts are empty or missing for ' + module)
            percent = 100.0 if total == 0 else round((total - missing) * 100.0 / total, 2)
            results.append({'module': module, 'branches': total, 'missing': missing,
                            'branch_percent': percent})
            class_total += total
            class_missing += missing
        percent = 100.0 if class_total == 0 else round((class_total - class_missing) * 100.0 / class_total, 2)
        exact_percent = 100.0 if class_total == 0 else (class_total - class_missing) * 100.0 / class_total
        if minimum is not None and exact_percent < minimum:
            local.append(f'aggregate branch coverage {percent}% is below {minimum}%')
        valid = not global_errors and not local and bool(modules) and len(results) == len(modules)
        classes[class_name] = {'minimum_branch_percent': minimum, 'branch_percent': percent,
            'branches': class_total, 'missing': class_missing, 'modules': results,
            'expected_module_count': len(supplied) if type(supplied) is list else None,
            'valid': valid, 'errors': local}
        errors.extend(class_name + ': ' + error for error in local)
    return result()
