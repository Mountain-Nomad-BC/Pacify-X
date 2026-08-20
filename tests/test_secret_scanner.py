from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SCANNER_PATH = (
    ROOT
    / ".px/skills/secure-agent-supply-chain/scripts/authoritative_secret_scanner.py"
)
SPEC = importlib.util.spec_from_file_location(
    "authoritative_secret_scanner", SCANNER_PATH
)
assert SPEC and SPEC.loader
SCANNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SCANNER)


def test_secret_scanner_detects_literal_credentials_without_echoing_values() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "credentials.txt").write_text(
            "api_key = examplevalue123456\ngithub = ghp_a8F4c2D7e9G1h3J5k7M9n2P4\n",
            encoding="utf-8",
        )
        result = SCANNER.scan(root)
        assert not result["valid"]
        assert {item["kind"] for item in result["findings"]} == {
            "generic_secret",
            "github_token",
        }
        assert {item["value"] for item in result["findings"]} == {"[REDACTED]"}


def test_secret_scanner_rejects_code_and_documentation_false_positives() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "examples.txt").write_text(
            "TOKEN = re.compile(r'[a-z]+')\n"
            "secret = os.getenv('JWT_SECRET', 'secret')\n"
            "token = accessToken\n"
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ1234\n",
            encoding="utf-8",
        )
        result = SCANNER.scan(root)
        assert result["valid"], result["findings"]


def test_secret_scanner_requires_a_complete_private_key_block() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        body = "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo=" * 4
        (root / "key.pem").write_text(
            f"-----BEGIN PRIVATE KEY-----\n{body}\n-----END PRIVATE KEY-----\n",
            encoding="utf-8",
        )
        result = SCANNER.scan(root)
        assert not result["valid"]
        assert [item["kind"] for item in result["findings"]] == ["private_key"]


def test_secret_scanner_reviews_are_identity_bound_and_fail_when_stale() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        target = root / "fixture.txt"
        target.write_text("api_" + "key = boundedfixture123456\n", encoding="utf-8")
        unreviewed = SCANNER.scan(root)
        record = {
            **unreviewed["findings"][0],
            "classification": "test_fixture",
            "owner": "tests",
        }
        record.pop("value")
        record.pop("classification", None)
        record["classification"] = "test_fixture"
        registry = root / "registry/secret_finding_reviews.json"
        registry.parent.mkdir()
        registry.write_text(
            SCANNER.json.dumps({"schema_version": "1.0", "records": [record]}),
            encoding="utf-8",
        )
        assert SCANNER.scan(root)["valid"]
        target.write_text("api_" + "key = changedfixture654321\n", encoding="utf-8")
        changed = SCANNER.scan(root)
        assert not changed["valid"]
        assert changed["unreviewed_count"] == 1
        assert any(item["error"] == "stale_reviews" for item in changed["errors"])
