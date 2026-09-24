"""Optional read/advisory bridge to the external ``pacifyx_memory`` package.

Pacify-X memory remains canonical.  This bridge exposes only non-mutating
validation, listing, review-preview, and graph-preview operations in Wave 10.
The external package contains additional write/publication mechanics, but PX does
not expose them until a later explicit admission/effect-grant path is installed.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import re
from typing import Any, Mapping

from .external_capability_provider import plan_external_invocation

PROVIDER_ID = "persistent-memory"
PROVIDER_VERSION = "0.3.0"
CANDIDATE_ID = "observe-external-persistent-memory"
SAFE_CAPABILITIES = frozenset({
    "memory.repo.validate",
    "memory.record.list",
    "memory.review.preview",
    "memory.graph.preview",
})
PACKAGE_FILES = (
    "__init__.py",
    "adapter.py",
    "boundary.py",
    "contributions.py",
    "cognitive_generation.py",
    "cognitive_storage.py",
    "graph.py",
    "models.py",
    "promotion.py",
    "public_sync.py",
    "repo.py",
    "review.py",
    "store.py",
    "tiering.py",
    "utils.py",
)
_SHA = re.compile(r"^[0-9a-f]{64}$")


def _stable(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    ).hexdigest()


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


def _package_root() -> Path:
    spec = importlib.util.find_spec("pacifyx_memory")
    if spec is None or not spec.submodule_search_locations:
        raise RuntimeError("optional pacifyx_memory package is not installed")
    locations = tuple(spec.submodule_search_locations)
    if len(locations) != 1:
        raise RuntimeError("pacifyx_memory package has ambiguous import locations")
    return Path(locations[0]).resolve(strict=True)


def installed_package_sha256() -> str:
    root = _package_root()
    rows: list[dict[str, object]] = []
    for name in PACKAGE_FILES:
        path = (root / name).resolve(strict=True)
        if not _inside(path, root) or not path.is_file():
            raise RuntimeError(f"persistent-memory package file is missing or escapes package root: {name}")
        data = path.read_bytes()
        rows.append({"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    return _stable(rows)


@dataclass(frozen=True, slots=True)
class PersistentMemoryAuthorization:
    """Caller-supplied custody evidence; this object does not mint authority."""

    request_id: str
    expected_package_sha256: str
    approved_effects: tuple[str, ...] = ("read_local",)

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if type(self.request_id) is not str or not self.request_id.strip() or len(self.request_id.encode()) > 4096:
            errors.append("request_id is required and bounded")
        if type(self.expected_package_sha256) is not str or _SHA.fullmatch(self.expected_package_sha256) is None:
            errors.append("expected_package_sha256 must be lowercase SHA-256")
        if type(self.approved_effects) is not tuple or any(type(item) is not str for item in self.approved_effects):
            errors.append("approved_effects must be a tuple of strings")
        if self.approved_effects != ("read_local",):
            errors.append("Wave-10 persistent-memory bridge permits exactly one read_local effect")
        return tuple(errors)


def provider_metadata() -> dict[str, Any]:
    available = importlib.util.find_spec("pacifyx_memory") is not None
    return {
        "provider_id": PROVIDER_ID,
        "version": PROVIDER_VERSION,
        "provider_kind": "external-capability-provider",
        "available": available,
        "runtime_authority": False,
        "canonical_memory_authority": False,
        "default_enabled": False,
        "capabilities": sorted(SAFE_CAPABILITIES),
        "mutation_capabilities_exposed": [],
        "package_sha256_required": True,
        "private_repo_outside_px_root_required": True,
    }


def execute(
    capability: str,
    payload: Mapping[str, Any],
    *,
    px_root: Path,
    authorization: PersistentMemoryAuthorization,
) -> dict[str, Any]:
    """Execute one read/advisory external-memory operation under exact package custody."""
    if capability not in SAFE_CAPABILITIES:
        raise PermissionError("persistent-memory mutation/publication is not admitted by Wave 10")
    if type(payload) is not dict:
        raise ValueError("persistent-memory payload must be a plain object")
    if len(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")) > 1024 * 1024:
        raise ValueError("persistent-memory payload exceeds 1 MiB")
    errors = authorization.validate()
    if errors:
        raise PermissionError("; ".join(errors))
    px_root = px_root.resolve(strict=True)
    package_root = _package_root()
    if _inside(package_root, px_root):
        raise RuntimeError("external persistent-memory package must not live inside the Pacify-X source tree")
    package_sha = installed_package_sha256()
    if package_sha != authorization.expected_package_sha256:
        raise RuntimeError("persistent-memory package revision does not match admitted SHA-256")
    if "repo" not in payload or type(payload.get("repo")) is not str or not payload["repo"].strip():
        raise ValueError("persistent-memory operation requires a non-empty string repo path")
    if len(payload["repo"].encode("utf-8")) > 32_768:
        raise ValueError("persistent-memory repo path exceeds safety limit")
    if "public_repo" in payload and payload["public_repo"] is not None:
        if type(payload["public_repo"]) is not str or not payload["public_repo"].strip():
            raise ValueError("public_repo must be a non-empty string path when supplied")
    repo = Path(payload["repo"]).expanduser().resolve(strict=False)
    if _inside(repo, px_root):
        raise PermissionError("external persistent-memory repository must remain outside Pacify-X source root")

    # Catalog/registry custody belongs to the installed PX source tree, while
    # ``px_root`` is the caller-declared source boundary used to keep the
    # external package/repository out of PX.  Do not conflate the two.
    catalog_root = Path(__file__).resolve().parents[1]
    plan = plan_external_invocation(
        catalog_root,
        provider_id=PROVIDER_ID,
        candidate_id=CANDIDATE_ID,
        capability=capability,
        required_effects=("read_local",),
        approved_effects=authorization.approved_effects,
        payload=dict(payload),
    )
    adapter = importlib.import_module("pacifyx_memory.adapter")
    package_capabilities = frozenset(getattr(adapter, "CAPABILITIES", ()))
    if capability not in package_capabilities:
        raise RuntimeError("installed persistent-memory package does not expose requested capability")
    boundary_result = adapter.invoke(
        "memory.repo.validate",
        {"repo": str(repo), "px_root": str(px_root), "public_repo": payload.get("public_repo")},
        approved_effects=("read_local",),
    )
    if not boundary_result.get("result", {}).get("ok"):
        raise PermissionError("external persistent-memory repository boundary validation failed")
    result = adapter.invoke(capability, dict(payload), approved_effects=authorization.approved_effects)
    if result.get("px_authority_granted") is not False or type(result.get("receipt_sha256")) is not str:
        raise RuntimeError("external persistent-memory provider returned an invalid authority/receipt envelope")
    core = {
        "schema_version": "px.persistent-memory-bridge-result/1.0",
        "provider_id": PROVIDER_ID,
        "provider_version": PROVIDER_VERSION,
        "request_id": authorization.request_id,
        "package_sha256": package_sha,
        "invocation_plan_sha256": plan.plan_sha256,
        "external_receipt_sha256": result["receipt_sha256"],
        "capability": capability,
        "result": result["result"],
        "canonical_memory_authority": False,
        "authority_granted": False,
    }
    return {**core, "receipt_sha256": _stable(core)}
