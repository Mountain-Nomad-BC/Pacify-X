from pathlib import Path
import hashlib

from runtime.hash_utils import file_sha256
from runtime.structural_integrity import _logic_duplicates


def test_shared_file_digest_streams_beyond_one_chunk(tmp_path):
    image = bytes(range(256)) * 8193
    path = tmp_path / "large.bin"
    path.write_bytes(image)
    assert file_sha256(path) == hashlib.sha256(image).hexdigest()
    assert file_sha256(path) != hashlib.sha256(image[:1024*1024]).hexdigest()


def test_digest_review_requires_exact_owner_set(tmp_path):
    paths = (
        "runtime/airllm_runtime.py", "runtime/hash_utils.py", "runtime/project_control_plane.py",
        "runtime/project_intelligence.py", "runtime/workspace_manager.py",
        "scripts/archive_project_map_history.py", "scripts/build_release_successor_configs.py",
        "scripts/migration/extract_behavior_contracts.py", "scripts/pre_candidate_hygiene.py",
        "scripts/run_installed_operational_owner.py", "scripts/run_release_candidate.py",
        "scripts/run_release_stage_owner.py", "scripts/validate_certification_pipeline.py",
        "scripts/verify_release_publication.py",
    )
    function = "def file_sha256(path):\n    digest = hashlib.sha256()\n    with path.open('rb') as stream:\n        for chunk in iter(lambda: stream.read(1024 * 1024), b''):\n            digest.update(chunk)\n    return digest.hexdigest()\n"
    files = []
    for name in paths:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(function, encoding="utf-8")
        files.append(path)
    records, unreviewed = _logic_duplicates(tmp_path, tuple(files))
    assert not unreviewed
    assert records[0]["classification"] == "expanded-release-digest-adapters"
    extra = tmp_path / "runtime/unknown_owner.py"
    extra.write_text(function, encoding="utf-8")
    records, unreviewed = _logic_duplicates(tmp_path, tuple(files+[extra]))
    assert len(unreviewed) == 1
    assert records[0]["classification"] == "unreviewed"
