"""Reviewed release-test skip policy without finalizer coupling."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET


ALLOWED_RELEASE_TEST_SKIPS = {
    (
        "tests.test_build_installed_host_control_evidence",
        "test_retained_host_receipt_is_current_or_explicitly_stale",
    ): "retained installed VSIX is external host custody",
    (
        "tests.test_clean_source_export",
        "test_posix_unzip_restores_and_directly_executes_script",
    ): "ordinary POSIX unzip execution is verified on a host with unzip",
    (
        "tests.test_native_skills.NativeSkillTests",
        "test_live_workspace_original_backup_restores_exactly",
    ): "native migration has not run",
    (
        "tests.test_skill_studio",
        "test_skill_source_rejects_duplicate_canonical_directory_aliases",
    ): "host filesystem does not permit distinct case aliases",
    (
        "tests.test_operation_health_snapshot",
        "test_current_platform_listener_receipt_is_retained",
    ): "current installed-host evidence is intentionally outside source control",
    (
        "tests.test_studio_api",
        "test_worker_authority_environment_freezes_parent_home_key_root",
    ): "POSIX HOME fallback semantics",
}


class _BoundedJUnitTree(ET.TreeBuilder):
    def __init__(self):
        super().__init__()
        self.depth = 0
        self.nodes = 0

    def start(self, tag, attrs):
        self.depth += 1
        self.nodes += 1
        if self.depth > 64 or self.nodes > 1_000_000:
            raise ValueError("JUnit structural budget exhausted")
        return super().start(tag, attrs)

    def end(self, tag):
        value = super().end(tag)
        self.depth -= 1
        return value

    def doctype(self, name, pubid, system):
        raise ValueError("JUnit document types are not supported")


def junit_case_inventory(path: Path):
    """Acquire one bounded image and derive counts from actual unique cases."""
    from .input_files import independent_file, read_file_image, cooperative_deadline

    source, info = independent_file(path)
    raw = read_file_image(source, info, limit=64 * 1024 * 1024,
                          deadline=cooperative_deadline())
    return _junit_image_inventory(raw)


def _validated_junit_image(raw):
    """Parse an already acquired image so its digest and case inventory agree."""
    if type(raw) not in (bytes, bytearray) or len(raw) > 64 * 1024 * 1024:
        raise ValueError("JUnit image exceeds its byte contract")
    root = ET.fromstring(raw, parser=ET.XMLParser(target=_BoundedJUnitTree()))
    namespace = root.tag[:-len(root.tag.rsplit('}', 1)[-1])]
    def tag(element):
        name = element.tag
        if not isinstance(name, str):
            raise ValueError("JUnit element name is invalid")
        local = name.rsplit('}', 1)[-1]
        if name != namespace + local:
            raise ValueError("JUnit structural namespaces disagree")
        return local

    count_names = ('tests', 'failures', 'errors', 'skipped')
    cases = []
    identities = set()
    visited_cases = set()
    visited_outcomes = set()

    def declared_counts(element, actual):
        for key in count_names:
            value = element.get(key)
            if value is not None:
                if not value.isascii() or not value.isdecimal() or len(value) > 7:
                    raise ValueError("JUnit declared count is invalid")
                if int(value) != actual[key]:
                    raise ValueError("JUnit declared counts disagree with cases")

    def visit(element):
        kind = tag(element)
        if kind not in {'testsuites', 'testsuite'}:
            raise ValueError("JUnit root or suite is invalid")
        totals = dict.fromkeys(count_names, 0)
        for child in element:
            child_kind = tag(child)
            if child_kind in {'testsuites', 'testsuite'}:
                nested = visit(child)
                for key in count_names:
                    totals[key] += nested[key]
            elif child_kind == 'testcase':
                if kind != 'testsuite':
                    raise ValueError("JUnit case must belong to a suite")
                identity = (child.get('classname', ''), child.get('name', ''))
                if any(not text.strip() or len(text.encode('utf-8')) > 16384 for text in identity):
                    raise ValueError("JUnit case identity is missing or oversized")
                if identity in identities:
                    raise ValueError("JUnit case identities are not unique")
                identities.add(identity)
                visited_cases.add(id(child))
                if any(tag(value) not in {'failure', 'error', 'skipped', 'properties', 'system-out', 'system-err'} for value in child):
                    raise ValueError("JUnit testcase contains unsupported structure")
                outcomes = [value for value in child if tag(value) in {'failure', 'error', 'skipped'}]
                visited_outcomes.update(id(value) for value in outcomes)
                if len(outcomes) > 1:
                    raise ValueError("JUnit case has conflicting or repeated outcomes")
                outcome = tag(outcomes[0]) if outcomes else 'passed'
                reason = '' if not outcomes else ' '.join(filter(None, (outcomes[0].get('message', ''), outcomes[0].text or '')))
                totals['tests'] += 1
                if outcome != 'passed':
                    totals[{'failure': 'failures', 'error': 'errors', 'skipped': 'skipped'}[outcome]] += 1
                cases.append({'classname': identity[0], 'name': identity[1], 'outcome': outcome, 'reason': reason})
            elif child_kind not in {'properties', 'system-out', 'system-err'}:
                raise ValueError("JUnit suite contains unsupported structure")
        declared_counts(element, totals)
        return totals

    totals = visit(root)
    if not totals['tests']:
        raise ValueError("JUnit case denominator is empty")
    if any(id(element) not in visited_cases for element in root.iter() if tag(element) == 'testcase'):
        raise ValueError("JUnit case is outside the suite hierarchy")
    if any(id(element) not in visited_outcomes for element in root.iter() if tag(element) in {'failure', 'error', 'skipped'}):
        raise ValueError("JUnit outcome is outside its testcase")
    return root, {'totals': totals, 'cases': tuple(cases)}


def _junit_image_inventory(raw):
    return _validated_junit_image(raw)[1]


def _junit_skip_inventory_gate(parsed):
    allowed, unexpected = [], []
    for case in parsed['cases']:
        if case['outcome'] != 'skipped':
            continue
        identity = (case['classname'], case['name'])
        reason = ALLOWED_RELEASE_TEST_SKIPS.get(identity)
        label = f'{identity[0]}::{identity[1]}'
        (allowed if reason and reason in case['reason'] else unexpected).append(label)
    return {'valid': not unexpected, 'allowed_count': len(allowed),
            'allowed': sorted(allowed), 'unexpected_count': len(unexpected),
            'unexpected': sorted(unexpected), 'errors': []}



def junit_skip_policy_gate(path: Path) -> dict[str, Any]:
    """Require a complete case inventory and reviewed host-conditional skips."""
    try:
        return _junit_skip_inventory_gate(junit_case_inventory(path))
    except (OSError, ValueError, TypeError, KeyError, ET.ParseError) as error:
        return {'valid': False, 'allowed_count': 0, 'allowed': [],
                'unexpected_count': 0, 'unexpected': [],
                'errors': ['JUnit case inventory is invalid: ' + str(error)]}
