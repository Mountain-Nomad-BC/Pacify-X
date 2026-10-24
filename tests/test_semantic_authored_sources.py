"""Focused regressions for admitted authored-format owners and reviewed policy.

These tests assert the behavior the W1 census slice had to add: real
source-bearing formats are actually observed rather than reported as having no
owner, and non-semantic families are classified by an explicit reviewed policy
instead of being silently excluded or relabelled.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from runtime import semantic_authored_sources as authored
from runtime import semantic_surfaces as surfaces


ROOT = Path(__file__).resolve().parents[1]


def put(root, relative, text):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def row_for(report, relative):
    return next(row for row in report["files"] if row["path"] == relative)


# --- real source-bearing formats are observed -------------------------------


def test_stylesheet_layers_selectors_and_tokens_are_observed(tmp_path):
    put(tmp_path, "media/theme.css",
        "@layer px.tokens {\n  :root {\n    --bg: #000;\n  }\n  .panel {\n    color: red;\n  }\n}\n")
    snapshot = surfaces.collect_corpus_snapshot(tmp_path)
    assert row_for(snapshot.report(), "media/theme.css")["disposition"] == "observed"
    kinds = {entity.kind for entity in snapshot.entities}
    assert {"stylesheet", "layer", "design_token", "selector"} <= kinds
    assert snapshot.report()["extraction_complete"]


def test_markup_ids_and_local_references_are_observed_without_execution(tmp_path):
    canary = tmp_path / "must-not-exist.txt"
    put(tmp_path, "docs/index.html",
        "<!doctype html><html><head><title>Doc</title>"
        f"<script src=\"file:///{canary}\"></script></head>"
        "<body><h1 id=\"hero\">Hi</h1></body></html>")
    snapshot = surfaces.collect_corpus_snapshot(tmp_path)
    assert row_for(snapshot.report(), "docs/index.html")["disposition"] == "observed"
    names = {entity.name for entity in snapshot.entities}
    assert "Doc" in names and "hero" in names
    assert not canary.exists()
    assert snapshot.report()["execution_authority"] is False


def test_duplicate_element_id_fails_closed_without_partial_metadata(tmp_path):
    put(tmp_path, "docs/index.html", '<p id="a"></p>\n<p id="a"></p>')
    snapshot = surfaces.collect_corpus_snapshot(tmp_path)
    assert row_for(snapshot.report(), "docs/index.html")["disposition"] == "parse_error"
    assert snapshot.entities == ()
    assert not snapshot.report()["extraction_complete"]


def test_svg_is_parsed_as_text_and_refuses_entity_resolution(tmp_path):
    put(tmp_path, "media/icon.svg", '<svg><g id="badge"/></svg>')
    put(tmp_path, "media/hostile.svg", '<!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]><svg/>')
    report = surfaces.collect_corpus_snapshot(tmp_path).report()
    assert row_for(report, "media/icon.svg")["disposition"] == "observed"
    hostile = row_for(report, "media/hostile.svg")
    assert hostile["disposition"] == "parse_error"
    assert "document type" in hostile["reason"]


def test_typescript_is_observed_as_declarations_and_never_compiled(tmp_path):
    canary = tmp_path / "executed.txt"
    put(tmp_path, "templates/fn/index.ts",
        "export function handler(req: Request): Response {\n"
        f"  require('fs').writeFileSync({str(canary)!r}, 'x');\n"
        "  return new Response('ok');\n}\n"
        "interface Payload { id: string }\n")
    snapshot = surfaces.collect_corpus_snapshot(tmp_path)
    assert row_for(snapshot.report(), "templates/fn/index.ts")["disposition"] == "observed"
    names = {entity.name for entity in snapshot.entities}
    assert {"handler", "Payload"} <= names
    assert not canary.exists()


def test_sql_objects_are_observed_without_touching_a_database(tmp_path):
    put(tmp_path, "templates/schema.sql",
        "begin;\ncreate table if not exists public.items (id bigint primary key);\n"
        "create index items_idx on public.items (id);\ncommit;\n")
    report = surfaces.collect_corpus_snapshot(tmp_path).report()
    assert row_for(report, "templates/schema.sql")["disposition"] == "observed"
    kinds = {entity.kind for entity in snapshot_entities(tmp_path)}
    assert {"table", "index"} <= kinds


def snapshot_entities(tmp_path):
    return surfaces.collect_corpus_snapshot(tmp_path).entities


def test_release_dependency_pins_are_observed_and_unpinned_lines_fail_closed(tmp_path):
    put(tmp_path, "requirements-release.txt", "# comment\nbuild==1.5.0\ncolorama==0.4.6\n")
    snapshot = surfaces.collect_corpus_snapshot(tmp_path)
    assert row_for(snapshot.report(), "requirements-release.txt")["disposition"] == "observed"
    pinned = {entity.name for entity in snapshot.entities if entity.kind == "dependency"}
    assert pinned == {"build", "colorama"}
    put(tmp_path, "requirements-release.txt", "requests>=2.0\n")
    strict = surfaces.collect_corpus_snapshot(tmp_path).report()
    assert row_for(strict, "requirements-release.txt")["disposition"] == "parse_error"


def test_duplicate_requirement_is_refused(tmp_path):
    put(tmp_path, "requirements-release.txt", "build==1.5.0\nbuild==1.5.0\n")
    report = surfaces.collect_corpus_snapshot(tmp_path).report()
    assert row_for(report, "requirements-release.txt")["disposition"] == "parse_error"


# --- configuration, policy and template families ----------------------------


def test_path_pattern_lists_are_observed_as_declared_policy(tmp_path):
    put(tmp_path, ".gitignore", "# comment\nnode_modules/\n*.pyc\n")
    report = surfaces.collect_corpus_snapshot(tmp_path).report()
    assert row_for(report, ".gitignore")["disposition"] == "observed"
    patterns = {entity.name for entity in snapshot_entities(tmp_path)
                if entity.kind == "pattern"}
    assert patterns == {"node_modules/", "*.pyc"}


def test_packaging_manifest_includes_are_observed(tmp_path):
    put(tmp_path, "MANIFEST.in", "include LICENSE\nrecursive-include docs *.png\n")
    assert row_for(surfaces.collect_corpus_snapshot(tmp_path).report(),
                   "MANIFEST.in")["disposition"] == "observed"


def test_ownership_policy_records_declared_owners_as_attribution(tmp_path):
    put(tmp_path, ".github/CODEOWNERS", "* @pacify-x/team\n/runtime/ @pacify-x/runtime\n")
    report = surfaces.collect_corpus_snapshot(tmp_path).report()
    assert row_for(report, ".github/CODEOWNERS")["disposition"] == "observed"
    owners = {entity.doc for entity in snapshot_entities(tmp_path)}
    assert "declared review owner @pacify-x/runtime" in owners
    assert report["execution_authority"] is False


def test_ini_configuration_sections_and_settings_are_observed(tmp_path):
    put(tmp_path, ".coveragerc", "[run]\nbranch = true\n[report]\nshow_missing = true\n")
    report = surfaces.collect_corpus_snapshot(tmp_path).report()
    assert row_for(report, ".coveragerc")["disposition"] == "observed"
    assert {"section", "setting"} <= {entity.kind for entity in snapshot_entities(tmp_path)}


def test_malformed_ini_fails_closed(tmp_path):
    put(tmp_path, ".coveragerc", "[run\nbranch = true\n")
    report = surfaces.collect_corpus_snapshot(tmp_path).report()
    assert row_for(report, ".coveragerc")["disposition"] == "parse_error"


def test_editor_workspace_document_is_observed(tmp_path):
    put(tmp_path, ".vscode/px.code-workspace", '{"folders": [{"path": ".."}]}')
    assert row_for(surfaces.collect_corpus_snapshot(tmp_path).report(),
                   ".vscode/px.code-workspace")["disposition"] == "observed"


def test_environment_template_records_names_and_never_values(tmp_path):
    secret = "super-secret-placeholder-value"
    put(tmp_path, "service/.env.example", f"# example\nAPI_TOKEN={secret}\nPORT=5678\n")
    snapshot = surfaces.collect_corpus_snapshot(tmp_path)
    assert row_for(snapshot.report(), "service/.env.example")["disposition"] == "observed"
    names = {entity.name for entity in snapshot.entities}
    assert {"API_TOKEN", "PORT"} <= names
    assert all(secret not in entity.doc for entity in snapshot.entities)


def test_editor_rule_front_matter_is_observed(tmp_path):
    put(tmp_path, ".cursor/rules/boot.mdc",
        "---\ndescription: Bootstrap governance\nalwaysApply: true\n---\n# Follow AGENTS.md\n")
    report = surfaces.collect_corpus_snapshot(tmp_path).report()
    assert row_for(report, ".cursor/rules/boot.mdc")["disposition"] == "observed"
    assert "Bootstrap governance" in {entity.name for entity in snapshot_entities(tmp_path)}


# --- reviewed non-entity policy ---------------------------------------------


def test_legal_text_is_classified_by_reviewed_policy_not_excluded(tmp_path):
    put(tmp_path, "LICENSE", "MIT License\n\nPermission is hereby granted...\n")
    report = surfaces.collect_corpus_snapshot(tmp_path).report()
    row = row_for(report, "LICENSE")
    assert row["disposition"] == "intentionally_unclassified"
    assert row["unclassified_policy_id"] == "px.reviewed/legal-attribution-text"
    assert row["sha256"]
    # A reviewed non-entity classification is never extraction completeness.
    assert not report["extraction_complete"]


def test_binary_asset_is_hashed_and_classified_not_dropped(tmp_path):
    (tmp_path / "media").mkdir(parents=True, exist_ok=True)
    (tmp_path / "media" / "icon.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    report = surfaces.collect_corpus_snapshot(tmp_path).report()
    row = row_for(report, "media/icon.png")
    assert row["disposition"] == "intentionally_unclassified"
    assert row["unclassified_policy_id"] == "px.reviewed/binary-image-asset"
    assert row["sha256"] and len(report["files"]) == 1


def test_unknown_format_stays_honestly_unresolved(tmp_path):
    put(tmp_path, "knowledge/opaque.unknown", "authored unclassified material")
    report = surfaces.collect_corpus_snapshot(tmp_path).report()
    row = row_for(report, "knowledge/opaque.unknown")
    assert row["disposition"] == "unsupported_surface"
    assert row["sha256"]
    assert not report["extraction_complete"]


# --- policy binding and contract -------------------------------------------


def test_authored_source_policy_is_bound_into_the_source_binding(tmp_path):
    put(tmp_path, "runtime/a.py", "def run(): pass")
    report = surfaces.collect_corpus_snapshot(tmp_path).report()
    binding = report["source_binding"]
    assert binding["authored_source_policy_sha256"] == authored.policy_sha256()
    assert binding["canonical_identity_authority"] is False


def test_source_binding_invalidates_when_reviewed_policy_changes(tmp_path, monkeypatch):
    put(tmp_path, "runtime/a.py", "def run(): pass")
    baseline = surfaces.collect_corpus_snapshot(tmp_path).report()
    monkeypatch.setattr(authored, "REVIEWED_NON_ENTITIES", (
        *authored.REVIEWED_NON_ENTITIES,
        authored.ReviewedNonEntity(
            policy_id="px.reviewed/test-only",
            reason="injected policy change for binding invalidation",
            suffixes=(".testonly",),
        ),
    ))
    after = surfaces.collect_corpus_snapshot(tmp_path).report()
    assert after["source_revision"] == baseline["source_revision"]
    assert after["source_binding_sha256"] != baseline["source_binding_sha256"]


def test_binding_contract_accepts_the_new_disposition_and_refuses_free_text(tmp_path):
    from copy import deepcopy

    from runtime.contracts import ContractValidationError, validate_instance

    put(tmp_path, "LICENSE", "Authored legal attribution text.\n")
    binding = surfaces.collect_corpus_snapshot(tmp_path).report()["source_binding"]
    validate_instance(binding, surfaces.SOURCE_BINDING_SCHEMA)

    broken = deepcopy(binding)
    broken["authored_files"][0]["unclassified_policy_id"] = "not-a-reviewed-policy"
    with pytest.raises(ContractValidationError):
        validate_instance(broken, surfaces.SOURCE_BINDING_SCHEMA)

    unowned = deepcopy(binding)
    unowned["authored_files"][0]["unclassified_policy_id"] = "px.reviewed/anything"
    unowned["authored_files"][0].pop("reason")
    with pytest.raises(ContractValidationError):
        validate_instance(unowned, surfaces.SOURCE_BINDING_SCHEMA)


def test_reviewed_policy_and_format_owners_declare_unique_identifiers():
    policy_ids = [policy.policy_id for policy in authored.REVIEWED_NON_ENTITIES]
    format_ids = [owner.format_id for owner in authored.FORMAT_OWNERS]
    assert len(policy_ids) == len(set(policy_ids)) == len(authored.REVIEWED_NON_ENTITIES)
    assert len(format_ids) == len(set(format_ids)) == len(authored.FORMAT_OWNERS)
    assert all(policy.reason.strip() for policy in authored.REVIEWED_NON_ENTITIES)
    assert all(owner.extract for owner in authored.FORMAT_OWNERS)


def test_repository_formerly_unsupported_rows_are_now_resolved():
    """Every row the previous slice reported as unowned must now resolve."""
    previous = [
        ".coveragerc", ".cursor/rules/agentic-engineering-os-px.mdc", ".gitattributes",
        ".github/CODEOWNERS", ".gitignore",
        ".vscode/pacify-x-background.code-workspace", "LICENSE",
        "LICENSES/everything-claude-code-MIT.txt", "LICENSES/mattpocock-skills-MIT.txt",
        "MANIFEST.in", "NOTICE", "docs/architecture/index.html",
        "docs/architecture/tools/viewer_template/index.html",
        "docs/architecture/tools/viewer_template/viewer.css", "docs/architecture/viewer.css",
        "docs/assets/pacify-x.png", "extension/.vscodeignore", "extension/LICENSE",
        "extension/NOTICE", "extension/SHA256SUMS.txt", "extension/media/agent-console.css",
        "extension/media/dashboard.css", "extension/media/px-activity.svg",
        "extension/media/px-shield-128.png", "extension/media/px-shield-256.png",
        "extension/media/px-shield-32.png", "extension/media/px-shield-mark-tight.png",
        "extension/media/px-shield-v2-chroma.png", "extension/media/px-shield-v2.png",
        "extension/media/sidebar.css", "extension/media/styles/00-layer-order.css",
        "extension/media/styles/01-tokens.css", "extension/media/styles/10-primitives.css",
        "extension/media/styles/20-layout.css", "extension/media/styles/30-components.css",
        "extension/media/styles/40-surfaces.css", "extension/media/styles/50-responsive.css",
        "extension/media/styles/60-accessibility.css", "extension/tests/preview.html",
        "extension/tests/sidebar-preview.html", "providers/agency_agents/LICENSE.txt",
        "requirements-release.txt",
        "templates/service_capabilities/cross-stack/n8n_supabase_vector_schema.sql",
        "templates/service_capabilities/n8n/.env.example",
        "templates/service_capabilities/supabase/functions/example/index.ts",
        "templates/service_capabilities/supabase/migrations/0001_secure_example.sql",
    ]
    unresolved = []
    for relative in previous:
        path = ROOT / relative
        assert path.is_file(), relative
        owner = authored.format_owner(relative)
        policy = authored.reviewed_non_entity(relative)
        if owner is not None:
            try:
                authored.extract_owned(relative, path.read_bytes())
            except authored.AuthoredSourceError as exc:
                unresolved.append(f"{relative}: {exc}")
        elif policy is None:
            unresolved.append(relative)
    assert unresolved == []