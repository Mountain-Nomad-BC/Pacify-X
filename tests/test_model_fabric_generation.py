from __future__ import annotations

from pathlib import Path

import pytest

from runtime.model_fabric_generation import build_model_fabric_generation, policy_document_digests
from runtime.model_profile import load_runtime_profiles


ROOT = Path(__file__).parents[1]


def test_generation_identity_is_order_independent_and_policy_bound() -> None:
    profiles = load_runtime_profiles(ROOT)[:2]
    policies = policy_document_digests(ROOT)
    artifacts = {profiles[0].model_id: "a" * 64, profiles[1].model_id: "b" * 64}
    one = build_model_fabric_generation(model_artifacts=artifacts, profiles=profiles, policy_documents=policies, adapter_revisions={"llama-cpp-stream": "c" * 64})
    two = build_model_fabric_generation(model_artifacts=list(reversed(tuple(artifacts.items()))), profiles=reversed(profiles), policy_documents=list(reversed(tuple(policies.items()))), adapter_revisions={"llama-cpp-stream": "c" * 64})
    assert one == two
    assert len(one.generation_id) == 64

    changed = dict(policies)
    key = sorted(changed)[0]
    changed[key] = "d" * 64
    other = build_model_fabric_generation(model_artifacts=artifacts, profiles=profiles, policy_documents=changed, adapter_revisions={"llama-cpp-stream": "c" * 64})
    assert other.generation_id != one.generation_id


def test_generation_rejects_duplicate_identity_and_non_digest_evidence() -> None:
    profile = load_runtime_profiles(ROOT)[0]
    with pytest.raises(ValueError, match="duplicate model_artifacts key"):
        build_model_fabric_generation(model_artifacts=((profile.model_id, "a" * 64), (profile.model_id, "b" * 64)), profiles=(profile,), policy_documents={})
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        build_model_fabric_generation(model_artifacts={profile.model_id: "NOT-A-DIGEST"}, profiles=(profile,), policy_documents={})


def test_policy_digest_set_covers_every_wave6_execution_authority_document() -> None:
    digests = policy_document_digests(ROOT)
    assert set(digests) == {
        "models/routing-policy.json",
        "models/benchmark-policy.json",
        "models/model-portfolio.json",
        "models/runtime-profiles.json",
        "models/resource-policy.json",
        "models/provider-protocols.json",
    }
    assert all(len(value) == 64 for value in digests.values())
