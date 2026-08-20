from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

from runtime.operation_coverage import reconcile_operation_coverage
from runtime.operational_visibility import ROUTE_REGISTRY_SCHEMA


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 8, 11, 20, 0, tzinfo=timezone.utc)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _route(route_id: str, tier: str, *, unsupported: bool = False) -> dict[str, object]:
    mechanisms = {"A": "mediator", "B": "observer", "C": "attestation", "D": "none"}
    health = "unsupported" if unsupported else ("unconfigured" if tier == "D" else "healthy")
    return {
        "route_id": route_id,
        "surface": "runtime",
        "owner": f"owners/{route_id}.py",
        "advertised": True,
        "status": "unsupported" if unsupported else ("planned" if tier == "D" else "active"),
        "effect_classes": ["read"],
        "instrumentation": {
            "kind": mechanisms[tier],
            "component": None if tier == "D" else f"owners/{route_id}.py",
            "health": health,
        },
        "coverage_tier": tier,
        "blind_spot_state": "unsupported" if unsupported else ("unobserved" if tier == "D" else "none"),
        "retention_class": "none" if unsupported else "evidence",
        "consent": "not_granted" if unsupported else "not_required",
        "acceptance_evidence": [f"O01 {route_id} acceptance"],
    }


def _fixture(tmp_path: Path, routes: list[dict[str, object]]) -> tuple[Path, dict[str, object]]:
    (tmp_path / "registry").mkdir()
    (tmp_path / "contracts/operations").mkdir(parents=True)
    (tmp_path / "evidence/punch-cards").mkdir(parents=True)
    (tmp_path / "owners").mkdir()
    (tmp_path / "receipts").mkdir()
    (tmp_path / ROUTE_REGISTRY_SCHEMA).write_bytes((ROOT / ROUTE_REGISTRY_SCHEMA).read_bytes())
    for route in routes:
        (tmp_path / str(route["owner"])).write_text("# owner\n", encoding="utf-8")
    registry = {"schema_version": "1.0", "policy": "strict test registry", "routes": routes}
    (tmp_path / "registry/operation_route_registry.json").write_text(json.dumps(registry), encoding="utf-8")
    artifact = tmp_path / "owners" / str(routes[0]["route_id"] + ".py")
    evidence = {
        "schema_version": "px.punch-card-evidence/1.0",
        "card_id": "O01",
        "status": "accepted",
        "artifacts": [{"path": artifact.relative_to(tmp_path).as_posix(), "sha256": _sha(artifact)}],
    }
    (tmp_path / "evidence/punch-cards/O01.json").write_text(json.dumps(evidence), encoding="utf-8")
    states = []
    for route in routes:
        tier = route["coverage_tier"]
        if tier not in {"A", "B"}:
            continue
        receipt = tmp_path / "receipts" / f"{route['route_id']}.json"
        receipt.write_text(json.dumps({"route_id": route["route_id"]}), encoding="utf-8")
        states.append(
            {
                "route_id": route["route_id"],
                "kind": "mediator" if tier == "A" else "observer",
                "health": "healthy",
                "observed_at": NOW.isoformat(),
                "receipt_path": receipt.relative_to(tmp_path).as_posix(),
                "receipt_sha256": _sha(receipt),
            }
        )
    return tmp_path, {"schema_version": "px.operation-coverage-health/1.0", "route_states": states}


def _codes(report: dict[str, object]) -> set[str]:
    return {str(item["code"]) for item in report["blockers"]}  # type: ignore[index]


def _externalize_owner(
    root: Path,
    route: dict[str, object],
    *,
    include_owner: bool = True,
) -> Path:
    owner = str(route["owner"])
    (root / owner).unlink()
    receipt = root / "receipts/external-owner.json"
    payload = {
        "schema_version": "px.external-extension-verification/1.0",
        "card_id": "O01",
        "extension_root": "C:/external/extension",
        "verified_at": NOW.isoformat(),
        "artifacts": {owner: "a" * 64} if include_owner else {"src/other.js": "b" * 64},
    }
    receipt.write_text(json.dumps(payload), encoding="utf-8")
    evidence = {
        "schema_version": "px.punch-card-evidence/1.0",
        "card_id": "O01",
        "status": "accepted",
        "artifacts": [
            {
                "path": receipt.relative_to(root).as_posix(),
                "sha256": _sha(receipt),
            }
        ],
    }
    (root / "evidence/punch-cards/O01.json").write_text(
        json.dumps(evidence), encoding="utf-8"
    )
    return receipt


def test_healthy_mediator_observer_and_attestation_fixture_certifies(tmp_path: Path) -> None:
    root, health = _fixture(tmp_path, [_route("model.invoke", "A"), _route("os.observe", "B"), _route("cli.attest", "C")])
    report = reconcile_operation_coverage(root, health_snapshot=health, now=NOW)
    assert report["valid"] is True
    assert report["certifiable"] is True
    assert report["classified_route_count"] == 3
    assert report["tiers"] == {"A": 1, "B": 1, "C": 1, "D": 0}
    assert report["blockers"] == []


def test_unknown_route_state_is_invalid_and_blocks_certification(tmp_path: Path) -> None:
    root, health = _fixture(tmp_path, [_route("model.invoke", "A")])
    health["route_states"].append(deepcopy(health["route_states"][0]))  # type: ignore[index,union-attr]
    health["route_states"][-1]["route_id"] = "undeclared.route"  # type: ignore[index]
    report = reconcile_operation_coverage(root, health_snapshot=health, now=NOW)
    assert report["valid"] is False
    assert report["certifiable"] is False
    assert "unknown_route_state" in _codes(report)


def test_stale_and_unhealthy_observer_blocks_certification(tmp_path: Path) -> None:
    root, health = _fixture(tmp_path, [_route("os.observe", "B")])
    state = health["route_states"][0]  # type: ignore[index]
    state["health"] = "degraded"
    state["observed_at"] = (NOW - timedelta(minutes=6)).isoformat()
    report = reconcile_operation_coverage(root, health_snapshot=health, now=NOW, max_age_seconds=300)
    assert report["valid"] is True
    assert report["certifiable"] is False
    assert {"route_health_unhealthy", "route_health_stale"} <= _codes(report)


def test_false_tier_a_is_rejected_even_with_a_healthy_state(tmp_path: Path) -> None:
    route = _route("model.invoke", "A")
    route["instrumentation"]["kind"] = "attestation"  # type: ignore[index]
    root, health = _fixture(tmp_path, [route])
    report = reconcile_operation_coverage(root, health_snapshot=health, now=NOW)
    assert report["valid"] is False
    assert report["certifiable"] is False
    assert "registry_invalid" in _codes(report)
    assert "dishonest_tier" in _codes(report)


def test_explicit_unsupported_tier_d_is_valid_but_visible_as_blind_spot(tmp_path: Path) -> None:
    root, health = _fixture(tmp_path, [_route("os.unsupported", "D", unsupported=True)])
    report = reconcile_operation_coverage(root, health_snapshot=health, now=NOW)
    assert report["valid"] is True
    assert report["certifiable"] is False
    assert report["blind_spots"] == [{"route_id": "os.unsupported", "state": "unsupported"}]
    assert "declared_blind_spot" in _codes(report)


def test_health_receipt_mismatch_blocks_certification(tmp_path: Path) -> None:
    root, health = _fixture(tmp_path, [_route("model.invoke", "A")])
    health["route_states"][0]["receipt_sha256"] = "0" * 64  # type: ignore[index]
    report = reconcile_operation_coverage(root, health_snapshot=health, now=NOW)
    assert report["valid"] is True
    assert report["certifiable"] is False
    assert "health_receipt_mismatch" in _codes(report)


def test_missing_required_observer_state_blocks_certification(tmp_path: Path) -> None:
    root, health = _fixture(tmp_path, [_route("os.observe", "B")])
    health["route_states"] = []
    report = reconcile_operation_coverage(root, health_snapshot=health, now=NOW)
    assert report["valid"] is True
    assert report["certifiable"] is False
    assert "required_health_state_missing" in _codes(report)


def test_disabled_optional_observer_does_not_require_live_health(tmp_path: Path) -> None:
    route = _route("os.observe", "B")
    route["advertised"] = False
    route["status"] = "planned"
    route["instrumentation"]["health"] = "unconfigured"  # type: ignore[index]
    root, health = _fixture(tmp_path, [route])
    health["route_states"] = []

    report = reconcile_operation_coverage(root, health_snapshot=health, now=NOW)

    assert report["valid"] is True
    assert report["certifiable"] is True
    assert report["routes"][0]["advertised"] is False  # type: ignore[index]
    assert "required_health_state_missing" not in _codes(report)
    assert "declared_instrumentation_unhealthy" not in _codes(report)


def test_unadvertised_planned_route_does_not_claim_acceptance(tmp_path: Path) -> None:
    route = _route("maintenance.planned", "D")
    route["advertised"] = False
    route["status"] = "planned"
    root, health = _fixture(tmp_path, [route])
    (root / "evidence/punch-cards/O01.json").unlink()

    report = reconcile_operation_coverage(root, health_snapshot=health, now=NOW)

    assert report["valid"] is True
    assert report["certifiable"] is True
    assert report["routes"][0]["required_acceptance_cards"] == ["O01"]  # type: ignore[index]
    assert "acceptance_evidence_missing" not in _codes(report)


def test_stale_acceptance_artifact_hash_blocks_certification(tmp_path: Path) -> None:
    root, health = _fixture(tmp_path, [_route("model.invoke", "A")])
    (root / "owners/model.invoke.py").write_text("# changed\n", encoding="utf-8")
    report = reconcile_operation_coverage(root, health_snapshot=health, now=NOW)
    assert report["valid"] is True
    assert report["certifiable"] is False
    assert "acceptance_receipt_mismatch" in _codes(report)


def test_external_owner_requires_accepted_hash_bound_local_receipt(tmp_path: Path) -> None:
    route = _route("extension.observe", "C")
    route["surface"] = "extension"
    root, health = _fixture(tmp_path, [route])
    _externalize_owner(root, route)

    report = reconcile_operation_coverage(root, health_snapshot=health, now=NOW)

    assert report["certifiable"] is True
    owner_evidence = report["routes"][0]["owner_evidence"]  # type: ignore[index]
    assert owner_evidence == {
        "mode": "external_hash_bound_receipt",
        "card_id": "O01",
        "receipt_path": "receipts/external-owner.json",
        "owner": route["owner"],
        "owner_sha256": "a" * 64,
    }


def test_tampered_external_owner_receipt_blocks_route(tmp_path: Path) -> None:
    route = _route("extension.observe", "C")
    route["surface"] = "extension"
    root, health = _fixture(tmp_path, [route])
    receipt = _externalize_owner(root, route)
    receipt.write_text("{}", encoding="utf-8")

    report = reconcile_operation_coverage(root, health_snapshot=health, now=NOW)

    assert report["certifiable"] is False
    assert {"acceptance_receipt_mismatch", "route_owner_missing"} <= _codes(report)


def test_external_receipt_must_name_exact_owner(tmp_path: Path) -> None:
    route = _route("extension.observe", "C")
    route["surface"] = "extension"
    root, health = _fixture(tmp_path, [route])
    _externalize_owner(root, route, include_owner=False)

    report = reconcile_operation_coverage(root, health_snapshot=health, now=NOW)

    assert report["certifiable"] is False
    assert "route_owner_missing" in _codes(report)


def test_external_receipt_cannot_substitute_for_runtime_owner(tmp_path: Path) -> None:
    route = _route("runtime.missing", "C")
    root, health = _fixture(tmp_path, [route])
    _externalize_owner(root, route)

    report = reconcile_operation_coverage(root, health_snapshot=health, now=NOW)

    assert report["certifiable"] is False
    assert "route_owner_missing" in _codes(report)
