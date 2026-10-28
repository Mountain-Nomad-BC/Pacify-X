"""Native lifecycle pointers are state; neighboring declarations stay authored."""
import pytest
from runtime.source_boundary import AUTHORED, RUNTIME_STATE, classify_path


@pytest.mark.parametrize('control', ['.agentic_engineering_os_px', '.engineering-bootstrap'])
@pytest.mark.parametrize('path,owner', [
    ('repair-campaign.json', 'runtime/test_profiles.py'),
    ('release-identity.json', 'runtime/release_campaign.py'),
    ('current-campaigns/' + 'a' * 64 + '/release-identity.json', 'runtime/release_campaign.py'),
])
def test_exact_native_lifecycle_state_is_not_authored(control, path, owner):
    row = classify_path(control + '/processing-order/' + path)
    assert row['classification'] == RUNTIME_STATE
    assert row['owner'] == owner


@pytest.mark.parametrize('path', [
    'repair-campaign.json/source.py', 'repair-campaign-policy.json',
    'current-campaigns/not-a-digest/release-identity.json',
    'current-campaigns/' + 'a' * 64 + '/policy.json',
    'current-campaigns/' + 'a' * 64 + '/release-identity.json/source.py',
])
def test_neighboring_campaign_requirements_are_not_excluded(path):
    assert classify_path('.agentic_engineering_os_px/processing-order/' + path)['classification'] == AUTHORED
