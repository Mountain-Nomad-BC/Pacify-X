from runtime.evidence_cache import EvidenceCache


H = "a" * 64


def test_cache_binds_all_revisions_and_rejects_cross_revision_hit(tmp_path):
    cache = EvidenceCache(tmp_path)
    key = cache.key(
        "ledger-projection",
        source_revision=H,
        authority_revision="b" * 64,
        toolchain_revision="c" * 64,
        dependency_revisions={"ledger": "d" * 64},
    )
    receipt = cache.put(key, {"event_count": 10})
    assert receipt["canonical"] is False
    assert cache.get(key) == {"event_count": 10}
    changed = cache.key(
        "ledger-projection",
        source_revision=H,
        authority_revision="b" * 64,
        toolchain_revision="c" * 64,
        dependency_revisions={"ledger": "e" * 64},
    )
    assert cache.get(changed) is None


def test_cache_corruption_fails_closed(tmp_path):
    cache = EvidenceCache(tmp_path)
    key = cache.key(
        "x",
        source_revision=H,
        authority_revision=H,
        toolchain_revision=H,
        dependency_revisions={"x": H},
    )
    receipt = cache.put(key, {"value": 1})
    blob = cache.directory / "blobs" / f"{receipt['content_sha256']}.json"
    blob.write_text("{}", encoding="utf-8")
    assert cache.get(key) is None
