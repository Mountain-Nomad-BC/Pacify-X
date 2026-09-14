from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys

import pytest

from runtime import secret_scanning as secret
from runtime import sanitation_assurance as sanitation
from runtime.test_runner import run_test_command

ROOT = Path(__file__).resolve().parents[1]


def project(tmp_path):
    root = tmp_path / "project"
    (root / "policies").mkdir(parents=True)
    (root / "policies/public-data-allowlist.json").write_text(
        json.dumps(
            {
                "approved_public_identifiers": [],
                "inert_test_domains": ["example.invalid"],
                "technical_uri_tokens": [],
                "binary_types": {".png": "89504e470d0a1a0a"},
            }
        ),
        encoding="utf-8",
    )
    (root / "README.md").write_text("ordinary source\n", encoding="utf-8")
    return root


def summary(root, **kwargs):
    gates = {
        name: {"status": "passed", "findings": []}
        for name in [
            "brand_identifier_sanitation",
            "legacy_placeholder_detection",
            "archive_detection",
        ]
    }
    return sanitation.build_sanitation_summary(
        root,
        kwargs.get("identifier", {"gates": gates}),
        kwargs.get("licensing", {"valid": True, "errors": []}),
    )


def assignment(value="boundedfixture123456"):
    return "api_" + "key = " + value + "\n"


def review(root):
    target = root / "fixture.txt"
    target.write_text(assignment(), encoding="utf-8")
    finding = secret.scan_secret_shapes(root)["findings"][0]
    record = {k: v for k, v in finding.items() if k != "value"}
    record.update(classification="test_fixture", owner="tests")
    path = root / "registry/secret_finding_reviews.json"
    path.parent.mkdir()
    path.write_text(
        json.dumps({"schema_version": "1.0", "records": [record]}), encoding="utf-8"
    )
    return target, path, record


def test_one_open_per_corpus_image_including_policy_and_reviews(tmp_path, monkeypatch):
    root = project(tmp_path)
    review(root)
    expected = {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in root.rglob("*")
        if p.is_file()
    }
    opens = []
    original = Path.open

    def opened(path, *args, **kwargs):
        if path.is_relative_to(root):
            opens.append(path.relative_to(root).as_posix())
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", opened)
    result = summary(root)
    assert result["valid"], result
    assert sorted(opens) == sorted(expected)
    records = [
        (p, len(raw), hashlib.sha256(raw).hexdigest())
        for p, raw in sorted(
            expected.items(), key=lambda row: (row[0].casefold(), row[0])
        )
    ]
    expected_sha = hashlib.sha256(
        json.dumps(records, separators=(",", ":")).encode()
    ).hexdigest()
    assert result["corpus_sha256"] == expected_sha
    assert {
        result["gates"][name]["corpus_sha256"]
        for name in [
            "secret_scanning",
            "credential_scanning",
            "pii_review",
            "binary_review",
        ]
    } == {expected_sha}


def test_local_controls_use_same_immutable_image_when_file_changes(
    tmp_path, monkeypatch
):
    root = project(tmp_path)
    path = root / "generation.txt"
    old = ("original@real.example\n" + assignment()).encode()
    new = ("replacement@real.example\n" + assignment("changedfixture654321")).encode()
    path.write_bytes(old)
    pattern = sanitation.EMAIL_PATTERN

    class ReplacingPattern:
        def finditer(self, raw, *args):
            if b"original@real.example" in raw:
                path.write_bytes(new)
            return pattern.finditer(raw, *args)

    monkeypatch.setattr(sanitation, "EMAIL_PATTERN", ReplacingPattern())
    result = summary(root)
    observed = result["gates"]["credential_scanning"]["findings"][0]
    expected = hashlib.sha256(assignment().strip().encode()).hexdigest()
    assert observed["line_sha256"] == expected
    assert (
        result["gates"]["pii_review"]["findings"][0]["value_sha256"]
        == hashlib.sha256(b"original@real.example").hexdigest()
    )
    assert secret.scan_secret_shapes(root)["findings"][0]["line_sha256"] != expected


@pytest.mark.parametrize(
    "setting,value",
    [
        ("MAX_SOURCE_BYTES", 128),
        ("MAX_FILES", 1),
        ("MAX_ENTRIES", 1),
        ("MAX_DIRECTORIES", 1),
        ("MAX_DEPTH", 1),
    ],
)
def test_complete_preflight_refuses_before_any_body(
    tmp_path, monkeypatch, setting, value
):
    root = project(tmp_path)
    (root / "a/b").mkdir(parents=True)
    (root / "a/b/large.txt").write_bytes(b"x" * 1024)
    monkeypatch.setattr(secret, setting, value, raising=False)
    original = Path.open
    opened = []

    def tracked(path, *args, **kwargs):
        if path.is_relative_to(root):
            opened.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", tracked)
    result = summary(root)
    assert result["valid"] is False and result.get("complete") is False
    assert result["corpus_sha256"] is None
    assert opened == []
    assert all(
        result["gates"][name]["status"] == "failed"
        for name in [
            "secret_scanning",
            "credential_scanning",
            "pii_review",
            "binary_review",
        ]
    )


@pytest.mark.parametrize(
    "relative",
    [
        "quarantine/hidden.txt",
        "_quarantine/hidden.txt",
        ".quarantine/hidden.txt",
        "REPO_QUARANTINE/hidden.txt",
        "registry/operational_gap_ledger.jsonl",
        "registry/operational_gap_ledger.deltas/retained.jsonl",
        ".px/mcp-runtime-probe.json",
    ],
)
def test_exclusions_apply_before_body_acquisition(tmp_path, monkeypatch, relative):
    root = project(tmp_path)
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(assignment(), encoding="utf-8")
    original = Path.open

    def checked(path, *args, **kwargs):
        assert path != target, "excluded body acquired"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", checked)
    assert secret.scan_secret_shapes(root)["valid"]
    assert summary(root)["valid"]


def test_relative_root_within_quarantine_refuses_before_read(tmp_path, monkeypatch):
    root = tmp_path / "_quarantine"
    root.mkdir()
    (root / "sentinel.txt").write_text(assignment(), encoding="utf-8")
    monkeypatch.chdir(root)
    original = Path.open

    def checked(path, *args, **kwargs):
        assert path.name != "sentinel.txt"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", checked)
    result = secret.scan_secret_shapes(Path("."))
    assert result["valid"] is False and result.get("complete") is False


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate",
        "unknown_class",
        "coerced_line",
        "bad_identity",
        "padded_owner",
        "unknown_field",
    ],
)
def test_review_schema_cannot_suppress_by_coercion_or_duplicate(tmp_path, mutation):
    root = project(tmp_path)
    _, path, record = review(root)
    records = [record]
    if mutation == "duplicate":
        records.append(dict(record))
    elif mutation == "unknown_class":
        record["classification"] = "arbitrary_permission"
    elif mutation == "coerced_line":
        record["line"] = "1"
    elif mutation == "bad_identity":
        record["id"] = "0" * 20
    elif mutation == "padded_owner":
        record["owner"] = "x" * 257
    else:
        record["extra"] = True
    path.write_text(
        json.dumps({"schema_version": "1.0", "records": records}), encoding="utf-8"
    )
    result = secret.scan_secret_shapes(root)
    assert result["valid"] is False
    assert result.get("complete") is False


def test_duplicate_json_review_key_is_incomplete(tmp_path):
    root = project(tmp_path)
    _, path, _ = review(root)
    path.write_text(
        '{"schema_version":"1.0","records":[],"records":[]}', encoding="utf-8"
    )
    result = secret.scan_secret_shapes(root)
    assert result["valid"] is False and result.get("complete") is False


def test_explicit_external_review_is_checked_separate_metadata(tmp_path):
    root = project(tmp_path)
    _, _, record = review(root)
    external = tmp_path / "external-review.json"
    raw = json.dumps({"schema_version": "1.0", "records": [record]}).encode()
    external.write_bytes(raw)
    result = secret.scan_secret_shapes(root, review_registry=external)
    assert result["valid"]
    assert result.get("review_registry_sha256") == hashlib.sha256(raw).hexdigest()


@pytest.mark.skipif(os.name != "nt", reason="Windows original junction boundary")
def test_original_junction_root_and_external_review_refuse(tmp_path):
    import _winapi

    root = project(tmp_path)
    _, registry, _ = review(root)
    link = tmp_path / "linked-project"
    _winapi.CreateJunction(str(root), str(link))
    result = secret.scan_secret_shapes(link)
    assert result["valid"] is False and result.get("complete") is False
    result = secret.scan_secret_shapes(
        root, review_registry=link / registry.relative_to(root)
    )
    assert result["valid"] is False and result.get("complete") is False


@pytest.mark.parametrize(
    "setting", ["MAX_LINES", "MAX_MATCHES", "MAX_FINDINGS", "MAX_OUTPUT_BYTES"]
)
def test_pattern_and_output_limits_refuse_partial_clean_claim(
    tmp_path, monkeypatch, setting
):
    root = project(tmp_path)
    (root / "many.txt").write_text(assignment() * 5, encoding="utf-8")
    monkeypatch.setattr(secret, setting, 1, raising=False)
    result = secret.scan_secret_shapes(root)
    assert result["valid"] is False and result.get("complete") is False
    assert result["findings"] == [] and result.get("corpus_sha256") is None


@pytest.mark.parametrize(
    "body,ending,expected",
    [
        ("A" * 64, "PRIVATE KEY", True),
        ("A" * 32 + "=\n" + "B" * 32 + "==", "PRIVATE KEY", True),
        ("A" * 63, "PRIVATE KEY", False),
        ("A" * 64, "RSA PRIVATE KEY", False),
        ("A" * 32 + "===\n" + "B" * 32, "PRIVATE KEY", False),
        ("A" * 64 + "!", "PRIVATE KEY", False),
    ],
    ids=[
        "continuous",
        "padded-lines",
        "short",
        "wrong-kind",
        "bad-padding",
        "bad-alphabet",
    ],
)
def test_private_block_semantics(tmp_path, body, ending, expected):
    root = project(tmp_path)
    text = (
        "-----BEGIN " + "PRIVATE KEY-----\n" + body + "\n-----END " + ending + "-----\n"
    )
    (root / "synthetic.pem").write_text(text, encoding="utf-8")
    result = secret.scan_secret_shapes(root)
    assert any(x["kind"] == "private_key" for x in result["findings"]) is expected


def test_malformed_private_body_closes_owned_child(tmp_path):
    root = project(tmp_path)
    (root / "malformed.pem").write_text(
        "-----BEGIN "
        + "PRIVATE KEY-----\n"
        + "A" * 65536
        + "!\n-----END "
        + "PRIVATE KEY-----\n",
        encoding="utf-8",
    )
    code = 'from pathlib import Path; import sys; from runtime.secret_scanning import scan_secret_shapes; r=scan_secret_shapes(Path(sys.argv[1])); print(r["valid"]); raise SystemExit(0 if r["valid"] else 1)'
    result = run_test_command(
        [sys.executable, "-B", "-c", code, str(root)],
        cwd=ROOT,
        environment={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        timeout_seconds=10,
        run_id="sanitation-malformed-private-body",
        lane_id="causal-owned-child",
        manage_process_temp=True,
    )
    assert result["process_tree_terminated"]
    assert (
        result["test_workspace"]["reclaimed"] and not result["test_workspace"]["errors"]
    )
    assert not result["timed_out"], result
    assert result["exit_code"] == 0, result


@pytest.mark.parametrize(
    "case",
    ["duplicate-policy-key", "coerced-domain", "ambiguous-magic", "huge-email-token"],
)
def test_policy_and_email_work_refuse_incomplete(tmp_path, case):
    root = project(tmp_path)
    path = root / "policies/public-data-allowlist.json"
    data = json.loads(path.read_text())
    if case == "duplicate-policy-key":
        path.write_text(path.read_text()[:-1] + ',"binary_types":{}}', encoding="utf-8")
    elif case == "coerced-domain":
        data["inert_test_domains"] = [123]
        path.write_text(json.dumps(data), encoding="utf-8")
    elif case == "ambiguous-magic":
        data["binary_types"][".PNG"] = "8950"
        path.write_text(json.dumps(data), encoding="utf-8")
    else:
        (root / "long.txt").write_text(
            "a" * 4097 + "@example.invalid", encoding="utf-8"
        )
    result = summary(root)
    assert result["valid"] is False and result.get("complete") is False


def test_unicode_newlines_preserve_original_finding_identity(tmp_path):
    root = project(tmp_path)
    path = root / "mixed.txt"
    raw = "heading\r\nvertical\u2028separator\n" + assignment()
    path.write_bytes(raw.encode("utf-8"))
    expected = secret._finding(
        path, root, "generic_secret", raw.count("\n", 0, raw.index("api_")) + 1, raw
    )
    result = secret.scan_secret_shapes(root)
    actual = next(x for x in result["findings"] if x["file"] == "mixed.txt")
    assert all(actual[k] == v for k, v in expected.items())
    assert "boundedfixture123456" not in json.dumps(result)


def test_current_review_metadata_is_preserved_in_owned_copy(tmp_path):
    root = project(tmp_path)
    raw = (ROOT / "registry/secret_finding_reviews.json").read_bytes()
    target = root / "registry/secret_finding_reviews.json"
    target.parent.mkdir()
    target.write_bytes(raw)
    corpus = secret._SourceCorpus(root)
    reviews, digest = secret._reviews(corpus, None)
    expected = json.loads(raw)["records"]
    assert list(reviews.values()) == expected
    assert digest == hashlib.sha256(raw).hexdigest()


def test_email_token_partition_preserves_original_offsets_and_escapes(tmp_path):
    root = project(tmp_path)
    raw = b"hello@real.example \\escaped@real.example \\escaped.part@real.example -punct@real.example first@real.example@second.example x@real.example/y@real.example\n"
    (root / "emails.txt").write_bytes(raw)
    expected = [
        (m.start(), hashlib.sha256(m.group(0).lower()).hexdigest())
        for m in sanitation.EMAIL_PATTERN.finditer(raw)
    ]
    result = summary(root)
    assert [
        (x["offset"], x["value_sha256"])
        for x in result["gates"]["pii_review"]["findings"]
    ] == expected


def test_read_failure_is_incomplete_without_partial_identity(tmp_path, monkeypatch):
    root = project(tmp_path)
    original = Path.open

    def opened(path, *args, **kwargs):
        if path == root / "README.md":
            raise PermissionError("owned refusal")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", opened)
    result = summary(root)
    assert not result["valid"] and not result["complete"]
    assert result["file_count"] is None and result["corpus_sha256"] is None
    assert result["scan_errors"][0]["error"] == "PermissionError"


def test_portable_source_aliases_refuse_before_body(tmp_path, monkeypatch):
    root = project(tmp_path)
    (root / "\u00e9.txt").write_text("one", encoding="utf-8")
    (root / "e\u0301.txt").write_text("two", encoding="utf-8")
    original = Path.open
    opened = []

    def tracked(path, *args, **kwargs):
        if path.is_relative_to(root):
            opened.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", tracked)
    result = secret.scan_secret_shapes(root)
    assert not result["valid"] and not result["complete"]
    assert opened == []


def test_explicit_missing_review_does_not_become_no_reviews(tmp_path):
    root = project(tmp_path)
    result = secret.scan_secret_shapes(root, review_registry=tmp_path / "missing.json")
    assert not result["valid"] and not result["complete"]
