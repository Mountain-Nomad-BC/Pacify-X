"""Exercise length controls through PX native schema admission and runtime validation."""
import json
import pytest
from runtime.contracts import (SUPPORTED_DIALECT, ContractValidationError,
    build_minimal_instance, contract_digest, validate_instance)


def schema(root, rule):
    p = root / 'bounded.schema.json'
    p.write_text(json.dumps({'$schema': SUPPORTED_DIALECT, '$id': 'urn:test:bounded', **rule}), encoding='utf-8')
    return p


@pytest.mark.parametrize('maximum,accepted,rejected', [(0, '', 'x'), (1, '\U0001f9ea', '\U0001f9eax'), (3, 'abc', 'abcd')])
def test_native_length_boundary_and_generated_example(tmp_path, maximum, accepted, rejected):
    p = schema(tmp_path, {'type': 'string', 'maxLength': maximum})
    assert len(contract_digest(p)) == 64
    validate_instance(accepted, p)
    with pytest.raises(ContractValidationError, match='too long'):
        validate_instance(rejected, p)
    validate_instance(build_minimal_instance(p), p)


@pytest.mark.parametrize('value', [-1, True, 1.5, '3'])
def test_malformed_length_bound_fails_native_admission(tmp_path, value):
    p = schema(tmp_path, {'type': 'string', 'maxLength': value})
    with pytest.raises(ValueError, match='maxLength'):
        contract_digest(p)


def test_contradictory_length_bounds_fail_admission(tmp_path):
    p = schema(tmp_path, {'type': 'string', 'minLength': 4, 'maxLength': 3})
    with pytest.raises(ValueError, match='minLength'):
        contract_digest(p)


def test_string_length_keyword_does_not_constrain_nonstring_instances(tmp_path):
    p = schema(tmp_path, {'maxLength': 0})
    validate_instance(123, p)
    validate_instance([], p)


def test_native_uuid_accepts_generated_example_and_rejects_malformed_value(tmp_path):
    p = schema(tmp_path, {'type': 'string', 'format': 'uuid'})
    validate_instance(build_minimal_instance(p), p)
    with pytest.raises(ContractValidationError, match='uuid'):
        validate_instance('forged-identity', p)


@pytest.mark.parametrize('name', ['dependency-identity', 'gremlin-recovery-authority', 'projection-status'])
def test_ported_runtime_contract_examples_pass_native_validation(name):
    from pathlib import Path
    p = Path(__file__).resolve().parents[1] / 'contracts' / (name + '.schema.json')
    validate_instance(build_minimal_instance(p), p)
