from __future__ import annotations

import json
from pathlib import Path
import tempfile

from runtime.sanitation_assurance import build_sanitation_summary
from runtime.secret_scanning import scan_secret_shapes


def _fixture(root: Path) -> None:
    (root / "policies").mkdir()
    (root / "policies/public-data-allowlist.json").write_text(
        json.dumps(
            {
                "approved_public_identifiers": [
                    {
                        "type": "email",
                        "value": "public@example.com",
                        "owner": "owner",
                        "reason": "contact",
                    }
                ],
                "inert_test_domains": ["example.invalid"],
                "technical_uri_tokens": ["git@github.com"],
                "binary_types": {".png": "89504e470d0a1a0a"},
            }
        ),
        encoding="utf-8",
    )
    (root / "README.md").write_text(
        "public@example.com release@example.invalid git@github.com\n", encoding="utf-8"
    )
    (root / "logo.png").write_bytes(bytes.fromhex("89504e470d0a1a0a") + b"fixture")


def _identifier_audit() -> dict:
    def gate(name: str) -> dict:
        return {
            "name": name,
            "status": "passed",
            "tool": "identifier",
            "corpus": ".",
            "exclusions": [".git"],
            "limitations": "bounded",
            "findings": [],
            "disposition": "pass",
        }

    return {
        "gates": {
            name: gate(name)
            for name in (
                "brand_identifier_sanitation",
                "legacy_placeholder_detection",
                "archive_detection",
            )
        }
    }


def test_release_sanitation_controls_are_separate_and_all_executed() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        _fixture(root)
        result = build_sanitation_summary(
            root, _identifier_audit(), {"valid": True, "errors": []}
        )
        assert result["valid"], result["errors"]
        assert set(result["gates"]) == {
            "brand_identifier_sanitation",
            "legacy_placeholder_detection",
            "archive_detection",
            "secret_scanning",
            "credential_scanning",
            "pii_review",
            "binary_review",
            "license_provenance_review",
        }
        assert all(gate["status"] == "passed" for gate in result["gates"].values())


def test_secret_and_credential_findings_fail_only_their_controls() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        _fixture(root)
        github = "ghp_" + "a8F4c2D7e9G1h3J5k7M9n2P4"
        assignment = "api_" + "key=boundedfixture123456"
        (root / "unsafe.txt").write_text(f"{github}\n{assignment}\n", encoding="utf-8")
        result = build_sanitation_summary(
            root, _identifier_audit(), {"valid": True, "errors": []}
        )
        assert not result["valid"]
        assert result["gates"]["secret_scanning"]["status"] == "failed"
        assert result["gates"]["credential_scanning"]["status"] == "failed"
        assert result["gates"]["pii_review"]["status"] == "passed"


def test_undeclared_binary_and_unreviewed_email_fail_closed() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        _fixture(root)
        (root / "payload.bin").write_bytes(b"\x00unsafe")
        (root / "contact.txt").write_text("private@real.example\n", encoding="utf-8")
        result = build_sanitation_summary(
            root, _identifier_audit(), {"valid": True, "errors": []}
        )
        assert result["gates"]["binary_review"]["status"] == "failed"
        assert result["gates"]["pii_review"]["status"] == "failed"


def test_secret_review_survives_formatting_only_line_movement() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        target = root / "fixture.py"
        target.write_text("api_" + "key = boundedfixture123456\n", encoding="utf-8")
        finding = scan_secret_shapes(root)["findings"][0]
        review = {key: value for key, value in finding.items() if key != "value"}
        review.update(
            classification="test_fixture",
            owner="tests",
            rationale="synthetic scanner fixture",
        )
        registry = root / "registry/secret_finding_reviews.json"
        registry.parent.mkdir()
        registry.write_text(
            json.dumps({"schema_version": "1.0", "records": [review]}),
            encoding="utf-8",
        )
        assert scan_secret_shapes(root)["valid"]

        target.write_text("\n\napi_" + "key = boundedfixture123456\n", encoding="utf-8")
        moved = scan_secret_shapes(root)
        assert moved["valid"], moved["errors"]
        assert moved["findings"][0]["line"] == 3
