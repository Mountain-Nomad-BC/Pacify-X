import pytest

from runtime.architecture_invariants import INVARIANT_IDS, architecture_invariant_report


@pytest.mark.parametrize("invariant_id", INVARIANT_IDS)
def test_each_architecture_invariant_has_passing_and_failing_vector(invariant_id):
    passing = {item: True for item in INVARIANT_IDS}
    assert architecture_invariant_report(passing)["valid"] is True
    passing[invariant_id] = False
    failed = architecture_invariant_report(passing)
    assert failed["valid"] is False
    assert failed["failed_invariant_ids"] == [invariant_id]
