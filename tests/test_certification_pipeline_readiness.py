"""Pre-attempt coverage checks must fail before an expensive release is consumed."""
import json
from pathlib import Path

import pytest

from scripts.validate_certification_pipeline import certification_coverage, REQUIRED_LIFECYCLE_TESTS, ValidationBlocked


def fixture(root):
    (root / 'registry').mkdir()
    for relative in REQUIRED_LIFECYCLE_TESTS:
        p = root / relative
        p.parent.mkdir(exist_ok=True)
        p.write_text('# disposable test', encoding='utf-8')
    value = {'certification': {'required_sections': ['release-lifecycle']},
             'sections': {'release-lifecycle': {'command': ['python', '-m', 'pytest', *REQUIRED_LIFECYCLE_TESTS]}}}
    path = root / 'registry/test_profiles.json'
    path.write_text(json.dumps(value), encoding='utf-8')
    return path, value


def test_actual_repository_covers_every_required_lifecycle_suite():
    assert certification_coverage(Path(__file__).resolve().parents[1])['valid'] is True


@pytest.mark.parametrize('failure', ['missing-membership', 'missing-file', 'duplicate'])
def test_incomplete_or_duplicated_coverage_blocks_preflight(tmp_path, failure):
    path, value = fixture(tmp_path)
    members = value['sections']['release-lifecycle']['command']
    if failure == 'missing-membership':
        members.remove(REQUIRED_LIFECYCLE_TESTS[0])
    elif failure == 'missing-file':
        (tmp_path / REQUIRED_LIFECYCLE_TESTS[0]).rename(tmp_path / 'retained-original.py')
    else:
        members.append(REQUIRED_LIFECYCLE_TESTS[0])
    path.write_text(json.dumps(value), encoding='utf-8')
    assert certification_coverage(tmp_path)['valid'] is False


def test_listing_a_suite_while_filtering_away_its_tests_is_not_coverage(tmp_path):
    path, value = fixture(tmp_path)
    value['sections']['release-lifecycle']['command'].extend(['-k', 'nothing_can_match'])
    path.write_text(json.dumps(value), encoding='utf-8')
    with pytest.raises(ValidationBlocked, match='unfiltered'):
        certification_coverage(tmp_path)


def test_optional_only_lifecycle_section_cannot_satisfy_certification_coverage(tmp_path):
    path, value = fixture(tmp_path)
    value['sections']['unrelated'] = {'command': ['python', '-m', 'pytest', 'tests/unrelated.py']}
    value['certification']['required_sections'] = ['unrelated']
    path.write_text(json.dumps(value), encoding='utf-8')
    assert certification_coverage(tmp_path)['valid'] is False
