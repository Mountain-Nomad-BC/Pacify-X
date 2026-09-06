from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import verify_release_publication as publication


RELEASE = "0.7.0"
CANDIDATE = "pacify-x-certification-20260906-final100-single"
COMMIT = "a" * 40


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    repository = tmp_path / "repository"
    (repository / "policies").mkdir(parents=True)
    (repository / "policies/release-trust.json").write_text("{}", encoding="utf-8")
    output = tmp_path / "restored"
    release_tree = output / "release-evidence"
    artifacts = output / "artifacts"
    artifacts.mkdir(parents=True)
    wheel = artifacts / "engineering_loop_bootstrap-0.7.0-py3-none-any.whl"
    sdist = artifacts / "engineering_loop_bootstrap-0.7.0.tar.gz"
    wheel.write_bytes(b"wheel")
    sdist.write_bytes(b"sdist")
    product_digest = "b" * 64
    harness_digest = "c" * 64
    certificate = {
        "release": RELEASE,
        "status": "self_certified",
        "product_digest": product_digest,
        "harness_digest": harness_digest,
        "source_control": {"commit_sha": COMMIT},
        "signature": {"path": "certificate.json.sig"},
        "artifacts": [
            {
                "type": "wheel",
                "filename": wheel.name,
                "sha256": _sha(wheel),
                "size_bytes": wheel.stat().st_size,
            },
            {
                "type": "sdist",
                "filename": sdist.name,
                "sha256": _sha(sdist),
                "size_bytes": sdist.stat().st_size,
            },
        ],
    }
    certificate_path = release_tree / "certificate.json"
    _write(certificate_path, certificate)
    (release_tree / "certificate.json.sig").write_bytes(b"certificate-signature")
    vsix_name = "pacify-x-vscode-0.6.85.vsix"
    bundled_vsix = output / vsix_name
    bundled_vsix.write_bytes(b"immutable-vsix")
    summary = {
        "schema_version": "px.installed-operational-run-summary/1.1",
        "campaign_id": CANDIDATE,
        "claim_id": f"release-stage:{CANDIDATE}:installed_operational:fixture",
        "release_identity_sha256": "d" * 64,
        "source_product_digest": product_digest,
        "source_harness_digest": harness_digest,
        "all_passed": True,
        "retries": 0,
        "cross_platform_smokes_parallel": True,
        "windows_hosts_serialized": True,
        "artifact": {
            "path": f"extension/dist/{vsix_name}",
            "sha256": _sha(bundled_vsix),
            "size": bundled_vsix.stat().st_size,
        },
        "members": [
            {
                "member": "windows-exact-vsix-smoke",
                "exit_code": 0,
                "artifact_unchanged": True,
                "process_tree_closed_verified": True,
            },
            {
                "member": "ubuntu-exact-vsix-smoke",
                "exit_code": 0,
                "artifact_unchanged": True,
                "process_tree_closed_verified": True,
            },
            {
                "member": "exhaustive-installed-exact-vsix-host-walk",
                "exit_code": 0,
                "artifact_unchanged": True,
                "process_tree_closed_verified": True,
                "terminal_state": "completed",
                "operationally_complete": True,
                "scope_complete": True,
                "issue_count": 0,
                "blocking_issue_count": 0,
                "host_error_count": 0,
                "profile_failure_count": 0,
                "workspace_reclaimed": True,
            },
        ],
    }
    summary_path = output / "final100-installed-operational-summary.json"
    _write(summary_path, summary)
    subject = {
        "archive_path": summary_path.name,
        "sha256": _sha(summary_path),
        "size": summary_path.stat().st_size,
        **{
            key: summary[key]
            for key in (
                "schema_version",
                "campaign_id",
                "release_identity_sha256",
                "source_product_digest",
                "source_harness_digest",
                "artifact",
            )
        },
    }
    receipt = {
        "schema_version": "1.1",
        "receipt_type": "complete_release_evidence_custody",
        "release": RELEASE,
        "source_commit": COMMIT,
        "chunks": [
            {
                "index": 1,
                "filename": f"pacify-x-v{RELEASE}-complete-evidence.zip.part-0001",
                "size": 5,
                "sha256": hashlib.sha256(b"chunk").hexdigest(),
            }
        ],
        "subjects": {
            "vsix": {
                "archive_path": bundled_vsix.name,
                "sha256": _sha(bundled_vsix),
                "size": bundled_vsix.stat().st_size,
            },
            "installed_operational_summary": subject,
        },
        "certificate_binding": {
            "archive_path": "release-evidence/certificate.json",
            "certificate_sha256": _sha(certificate_path),
            "release": RELEASE,
            "product_digest": product_digest,
            "harness_digest": harness_digest,
            "release_commit": COMMIT,
        },
    }
    assets = tmp_path / "assets"
    assets.mkdir()
    receipt_path = assets / f"pacify-x-v{RELEASE}-complete-evidence-custody.json"
    _write(receipt_path, receipt)
    receipt_path.with_suffix(".json.sig").write_bytes(b"custody-signature")
    (assets / receipt["chunks"][0]["filename"]).write_bytes(b"chunk")
    (assets / vsix_name).write_bytes(bundled_vsix.read_bytes())
    monkeypatch.setattr(
        publication,
        "verify_certificate_signature",
        lambda *_args, **_kwargs: {"valid": True, "identity": "fixture"},
    )
    monkeypatch.setattr(
        publication,
        "reconstruct_evidence_custody",
        lambda *_args, **_kwargs: {"valid": True, "extracted": True},
    )
    return {
        "assets": assets,
        "output": output,
        "repository": repository,
        "receipt": receipt,
        "receipt_path": receipt_path,
        "summary": summary,
        "summary_path": summary_path,
        "vsix_name": vsix_name,
        "vsix_sha256": _sha(bundled_vsix),
        "vsix_size": bundled_vsix.stat().st_size,
    }


def _verify(
    values: dict[str, object], *, candidate_id: str | None = None
) -> dict[str, object]:
    return publication.verify_publication(
        assets=values["assets"],
        output=values["output"],
        repository=values["repository"],
        release=RELEASE,
        source_commit=COMMIT,
        candidate_id=candidate_id,
        vsix_name=values["vsix_name"],
        vsix_sha256=values["vsix_sha256"],
        vsix_size=values["vsix_size"],
    )


def test_exact_signed_publication_bundle_is_admitted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    values = _fixture(tmp_path, monkeypatch)
    result = _verify(values)
    assert result["valid"]
    assert result["candidate_id"] == CANDIDATE
    assert result["vsix"] == str(values["assets"] / values["vsix_name"])
    assert (values["repository"] / "evidence/releases/0.7.0/certificate.json").is_file()


def test_supplied_candidate_must_match_signed_custody(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    values = _fixture(tmp_path, monkeypatch)
    with pytest.raises(
        publication.PublicationBlocked,
        match="supplied candidate differs from signed custody",
    ):
        _verify(
            values,
            candidate_id="pacify-x-certification-20260906-final101-single",
        )


def test_standalone_vsix_substitution_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    values = _fixture(tmp_path, monkeypatch)
    (values["assets"] / values["vsix_name"]).write_bytes(b"substitution")
    with pytest.raises(publication.PublicationBlocked, match="standalone draft VSIX"):
        _verify(values)


def test_extra_draft_asset_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    values = _fixture(tmp_path, monkeypatch)
    (values["assets"] / "unbound.bin").write_bytes(b"not signed")
    with pytest.raises(publication.PublicationBlocked, match="asset denominator"):
        _verify(values)


def test_summary_to_certificate_digest_split_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    values = _fixture(tmp_path, monkeypatch)
    summary = values["summary"]
    summary["source_product_digest"] = "e" * 64
    _write(values["summary_path"], summary)
    receipt = values["receipt"]
    receipt["subjects"]["installed_operational_summary"].update(
        {
            "sha256": _sha(values["summary_path"]),
            "size": values["summary_path"].stat().st_size,
            "source_product_digest": summary["source_product_digest"],
        }
    )
    _write(values["receipt_path"], receipt)
    with pytest.raises(publication.PublicationBlocked, match="certificate binding"):
        _verify(values)
