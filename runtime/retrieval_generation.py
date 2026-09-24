"""Immutable retrieval-generation custody.

A retrieval generation binds the corpus, lexical/vector artifacts, embedding and
reranker revisions, calibration evidence and query policy into one immutable
identity.  Building/validating a generation never promotes it; activation and
rollback require explicit authority.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
from typing import Mapping
from uuid import uuid4

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GENERATION_SCHEMA = "px.retrieval-generation/1.0"
VALIDATION_SCHEMA = "px.retrieval-generation-validation/1.0"
ACTIVE_SCHEMA = "px.retrieval-generation-active/1.0"


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha_text(value: object, name: str) -> str:
    if type(value) is not str or SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _text(value: object, name: str, *, max_bytes: int = 512) -> str:
    if type(value) is not str or not value.strip() or len(value.encode("utf-8")) > max_bytes:
        raise ValueError(f"{name} must be bounded nonempty text")
    return value


def _positive_int(value: object, name: str, *, maximum: int = 1_000_000) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f"{name} must be an integer in [1, {maximum}]")
    return value


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    prepared = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    prepared.write_bytes(_canonical(value) + b"\n")
    os.replace(prepared, path)


def _digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class RetrievalGenerationIdentity:
    corpus_sha256: str
    lexical_index_sha256: str
    dense_index_sha256: str
    dense_manifest_sha256: str
    embedding_model_id: str
    embedding_revision: str
    embedding_dimensions: int
    embedding_normalization: str
    calibration_sha256: str
    graph_revision: str
    reranker_model_id: str | None
    reranker_revision: str | None
    query_policy_sha256: str

    def validate(self) -> None:
        for name in (
            "corpus_sha256", "lexical_index_sha256", "dense_index_sha256",
            "dense_manifest_sha256", "calibration_sha256", "query_policy_sha256",
        ):
            _sha_text(getattr(self, name), name)
        _text(self.embedding_model_id, "embedding_model_id")
        _text(self.embedding_revision, "embedding_revision")
        _positive_int(self.embedding_dimensions, "embedding_dimensions", maximum=131072)
        if self.embedding_normalization != "l2":
            raise ValueError("embedding_normalization must be l2")
        _text(self.graph_revision, "graph_revision")
        if (self.reranker_model_id is None) != (self.reranker_revision is None):
            raise ValueError("reranker model and revision must be supplied together")
        if self.reranker_model_id is not None:
            _text(self.reranker_model_id, "reranker_model_id")
            _text(self.reranker_revision, "reranker_revision")

    @property
    def generation_id(self) -> str:
        self.validate()
        return _sha({"schema_version": GENERATION_SCHEMA, "identity": asdict(self)})


@dataclass(frozen=True, slots=True)
class RetrievalGateEvidence:
    build_ok: bool
    source_manifest_ok: bool
    provenance_ok: bool
    lexical_ready: bool
    vector_ready: bool
    calibration_ready: bool
    golden_recall: float
    golden_recall_min: float
    exact_identifier_pass_rate: float
    exact_identifier_min: float
    p95_latency_ms: float
    p95_latency_max_ms: float
    graph_ready: bool = True
    high_severity_findings: int = 0
    high_severity_findings_max: int = 0

    def admission(self) -> dict[str, object]:
        for name in ("golden_recall", "golden_recall_min", "exact_identifier_pass_rate", "exact_identifier_min"):
            value = getattr(self, name)
            if type(value) not in (int, float) or type(value) is bool or not math.isfinite(float(value)) or not 0 <= float(value) <= 1:
                raise ValueError(f"{name} must be finite and in [0,1]")
        for name in ("p95_latency_ms", "p95_latency_max_ms"):
            value = getattr(self, name)
            if type(value) not in (int, float) or type(value) is bool or not math.isfinite(float(value)) or float(value) < 0:
                raise ValueError(f"{name} must be finite and nonnegative")
        if type(self.high_severity_findings) is not int or type(self.high_severity_findings_max) is not int or self.high_severity_findings < 0 or self.high_severity_findings_max < 0:
            raise ValueError("finding counts must be nonnegative integers")
        checks = {
            "build_ok": self.build_ok is True,
            "source_manifest_ok": self.source_manifest_ok is True,
            "provenance_ok": self.provenance_ok is True,
            "lexical_ready": self.lexical_ready is True,
            "vector_ready": self.vector_ready is True,
            "graph_ready": self.graph_ready is True,
            "calibration_ready": self.calibration_ready is True,
            "golden_recall": float(self.golden_recall) >= float(self.golden_recall_min),
            "exact_identifier": float(self.exact_identifier_pass_rate) >= float(self.exact_identifier_min),
            "p95_latency": float(self.p95_latency_ms) <= float(self.p95_latency_max_ms),
            "high_severity_findings": self.high_severity_findings <= self.high_severity_findings_max,
        }
        failed = sorted(name for name, ok in checks.items() if not ok)
        return {"allowed": not failed, "checks": checks, "failed": failed}


class RetrievalGenerationStore:
    """Filesystem custody for immutable retrieval generations."""

    def __init__(self, state_root: Path) -> None:
        self.root = state_root.resolve()
        self.generations = self.root / "generations"
        self.active_path = self.root / "active.json"
        self.rollback_path = self.root / "rollback.json"

    def _manifest_path(self, generation_id: str) -> Path:
        _sha_text(generation_id, "generation_id")
        return self.generations / generation_id / "manifest.json"

    def stage_candidate(self, identity: RetrievalGenerationIdentity, artifacts: Mapping[str, Mapping[str, object]]) -> dict[str, object]:
        identity.validate()
        generation_id = identity.generation_id
        normalized: dict[str, dict[str, object]] = {}
        if type(artifacts) is not dict or not artifacts:
            raise ValueError("retrieval generation requires a nonempty artifact manifest")
        for name in sorted(artifacts):
            _text(name, "artifact name", max_bytes=256)
            row = artifacts[name]
            if type(row) is not dict:
                raise ValueError("artifact records must be mappings")
            relative = _text(row.get("path"), f"artifact {name} path", max_bytes=4096)
            p = Path(relative)
            if p.is_absolute() or ".." in p.parts:
                raise ValueError("artifact paths must be relative and traversal-free")
            normalized[name] = {
                "path": p.as_posix(),
                "sha256": _sha_text(row.get("sha256"), f"artifact {name} sha256"),
                "size_bytes": _positive_int(row.get("size_bytes"), f"artifact {name} size_bytes", maximum=1 << 50),
            }
        payload = {
            "schema_version": GENERATION_SCHEMA,
            "generation_id": generation_id,
            "state": "candidate",
            "identity": asdict(identity),
            "artifacts": normalized,
        }
        target = self._manifest_path(generation_id)
        if target.exists():
            actual = json.loads(target.read_text(encoding="utf-8"))
            if actual != payload:
                raise ValueError("generation ID collision or attempted in-place mutation")
            return actual
        _atomic_json(target, payload)
        return payload

    def load_manifest(self, generation_id: str) -> dict[str, object]:
        return json.loads(self._manifest_path(generation_id).read_text(encoding="utf-8"))

    def validate_artifacts(self, generation_id: str, artifact_root: Path) -> dict[str, object]:
        manifest = self.load_manifest(generation_id)
        root = artifact_root.resolve(strict=True)
        errors: list[str] = []
        for name, row in dict(manifest["artifacts"]).items():
            path = root / str(row["path"])
            try:
                resolved = path.resolve(strict=True)
                resolved.relative_to(root)
                if path.is_symlink() or resolved.is_symlink() or not resolved.is_file():
                    raise ValueError("not a regular admitted file")
                stat = resolved.stat()
                if stat.st_size != int(row["size_bytes"]):
                    raise ValueError("size mismatch")
                if _digest_file(resolved) != row["sha256"]:
                    raise ValueError("digest mismatch")
            except (OSError, ValueError) as error:
                errors.append(f"{name}: {error}")
        return {"valid": not errors, "generation_id": generation_id, "errors": tuple(errors)}

    def record_validation(self, generation_id: str, evidence: RetrievalGateEvidence) -> dict[str, object]:
        self.load_manifest(generation_id)
        admission = evidence.admission()
        payload = {
            "schema_version": VALIDATION_SCHEMA,
            "generation_id": generation_id,
            "evidence": asdict(evidence),
            "admission": admission,
        }
        receipt_sha = _sha(payload)
        directory = self.generations / generation_id / "validations"
        target = directory / f"{receipt_sha}.json"
        immutable = {**payload, "validation_sha256": receipt_sha}
        if target.exists() and json.loads(target.read_text(encoding="utf-8")) != immutable:
            raise ValueError("validation receipt mutation detected")
        if not target.exists():
            _atomic_json(target, immutable)
        _atomic_json(directory / "head.json", {"schema_version": "px.retrieval-validation-head/1.0", "generation_id": generation_id, "validation_sha256": receipt_sha})
        return immutable

    def _load_validation(self, generation_id: str, validation_sha256: str) -> dict[str, object]:
        _sha_text(validation_sha256, "validation_sha256")
        path = self.generations / generation_id / "validations" / f"{validation_sha256}.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("validation_sha256") != validation_sha256 or _sha({k: v for k, v in value.items() if k != "validation_sha256"}) != validation_sha256:
            raise ValueError("validation receipt digest mismatch")
        return value

    def active_generation(self) -> str | None:
        if not self.active_path.is_file():
            return None
        value = json.loads(self.active_path.read_text(encoding="utf-8"))
        return _sha_text(value.get("generation_id"), "active generation_id")

    def activate(self, generation_id: str, validation_sha256: str, *, supplied_authority: bool) -> dict[str, object]:
        if supplied_authority is not True:
            raise PermissionError("retrieval-generation activation requires explicit authority")
        self.load_manifest(generation_id)
        validation = self._load_validation(generation_id, validation_sha256)
        if validation.get("admission", {}).get("allowed") is not True:
            raise ValueError("retrieval generation has not passed admission")
        previous = self.active_generation()
        receipt = {
            "schema_version": ACTIVE_SCHEMA,
            "generation_id": generation_id,
            "validation_sha256": validation_sha256,
            "previous_active_generation": previous,
            "activated_at": _now(),
        }
        _atomic_json(self.active_path, receipt)
        if previous and previous != generation_id:
            _atomic_json(self.rollback_path, {"schema_version": "px.retrieval-rollback-head/1.0", "generation_id": previous})
        return receipt

    def rollback(self, *, supplied_authority: bool) -> dict[str, object]:
        if supplied_authority is not True:
            raise PermissionError("retrieval-generation rollback requires explicit authority")
        value = json.loads(self.rollback_path.read_text(encoding="utf-8"))
        target = _sha_text(value.get("generation_id"), "rollback generation_id")
        self.load_manifest(target)
        previous = self.active_generation()
        receipt = {"schema_version": ACTIVE_SCHEMA, "generation_id": target, "validation_sha256": None, "previous_active_generation": previous, "activated_at": _now(), "rollback": True}
        _atomic_json(self.active_path, receipt)
        return receipt

    def reconcile_active(self, artifact_root: Path) -> dict[str, object]:
        generation_id = self.active_generation()
        if generation_id is None:
            return {"valid": True, "active_generation": None, "errors": ()}
        report = self.validate_artifacts(generation_id, artifact_root)
        return {"valid": bool(report["valid"]), "active_generation": generation_id, "errors": report["errors"]}
