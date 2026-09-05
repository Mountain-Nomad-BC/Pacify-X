"""Immutable exact model attachments for task execution plans."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Iterable, Mapping, Sequence


SCHEMA_VERSION = "px.model-attachment/1.0"
_SHA = re.compile(r"^[0-9a-f]{64}$")
_FLOATING = frozenset({"latest", "main", "master", "head", "stable"})
_PRIVACY = {"policy_gated": 0, "isolated": 1, "local": 2}
_AUTHORITY = {"contained": 0, "installed_host": 1, "external_authority": 2}


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class ModelFallback:
    model_id: str
    model_revision: str
    artifact_sha256: str
    privacy: str
    authority_class: str

    def as_dict(self) -> dict[str, str]:
        return {
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "artifact_sha256": self.artifact_sha256,
            "privacy": self.privacy,
            "authority_class": self.authority_class,
        }


@dataclass(frozen=True, slots=True)
class ModelAttachment:
    schema_version: str
    attachment_id: str
    model_id: str
    model_revision: str
    artifact_sha256: str
    runtime: str
    context_tokens: int
    modalities: tuple[str, ...]
    supports_tools: bool
    privacy: str
    authority_class: str
    benchmark_revision: str
    hardware_requirements: tuple[tuple[str, str], ...]
    local_artifact_path: str | None
    quantization: str | None
    fallback_chain: tuple[ModelFallback, ...]
    attachment_sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "attachment_id": self.attachment_id,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "artifact_sha256": self.artifact_sha256,
            "runtime": self.runtime,
            "context_tokens": self.context_tokens,
            "modalities": list(self.modalities),
            "supports_tools": self.supports_tools,
            "privacy": self.privacy,
            "authority_class": self.authority_class,
            "benchmark_revision": self.benchmark_revision,
            "hardware_requirements": dict(self.hardware_requirements),
            "local_artifact_path": self.local_artifact_path,
            "quantization": self.quantization,
            "fallback_chain": [item.as_dict() for item in self.fallback_chain],
            "attachment_sha256": self.attachment_sha256,
        }


def model_attachment_from_dict(payload: Mapping[str, object]) -> ModelAttachment:
    """Decode an attachment without weakening its content validation."""
    fallbacks = tuple(
        ModelFallback(
            str(item.get("model_id", "")),
            str(item.get("model_revision", "")),
            str(item.get("artifact_sha256", "")),
            str(item.get("privacy", "")),
            str(item.get("authority_class", "")),
        )
        for item in payload.get("fallback_chain", ())
        if isinstance(item, Mapping)
    )
    requirements = payload.get("hardware_requirements")
    return ModelAttachment(
        str(payload.get("schema_version", "")),
        str(payload.get("attachment_id", "")),
        str(payload.get("model_id", "")),
        str(payload.get("model_revision", "")),
        str(payload.get("artifact_sha256", "")),
        str(payload.get("runtime", "")),
        int(payload.get("context_tokens", 0)),
        tuple(map(str, payload.get("modalities", ()))),
        bool(payload.get("supports_tools")),
        str(payload.get("privacy", "")),
        str(payload.get("authority_class", "")),
        str(payload.get("benchmark_revision", "")),
        tuple(
            sorted(
                (str(key), str(value))
                for key, value in (
                    requirements.items() if isinstance(requirements, Mapping) else ()
                )
            )
        ),
        str(payload["local_artifact_path"])
        if payload.get("local_artifact_path") is not None
        else None,
        str(payload["quantization"])
        if payload.get("quantization") is not None
        else None,
        fallbacks,
        str(payload.get("attachment_sha256", "")),
    )


def _revision(value: object) -> str:
    revision = str(value or "").strip()
    if revision.casefold() in _FLOATING or revision.casefold().endswith(":latest"):
        raise ValueError("model revision must be exact, not floating")
    if not revision:
        raise ValueError("model revision is required")
    return revision


def build_model_attachment(
    root: Path,
    *,
    model_id: str,
    model_revision: str,
    artifact_sha256: str,
    runtime: str,
    context_tokens: int,
    modalities: Sequence[str],
    supports_tools: bool,
    privacy: str,
    authority_class: str,
    benchmark_revision: str,
    hardware_requirements: Mapping[str, object],
    local_artifact_path: str | None = None,
    quantization: str | None = None,
    fallback_chain: Sequence[Mapping[str, object]] = (),
) -> ModelAttachment:
    root = root.resolve()
    revision = _revision(model_revision)
    artifact_hash = str(artifact_sha256).casefold()
    if local_artifact_path is not None:
        path = (root / local_artifact_path).resolve()
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError as error:
            raise ValueError("local model path escapes the project") from error
        if path.suffix.casefold() != ".gguf" or not path.is_file():
            raise ValueError("local model artifact must be an existing GGUF")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != artifact_hash:
            raise ValueError("local model artifact hash does not match")
        if not quantization:
            raise ValueError("local GGUF requires exact quantization")
        local_artifact_path = relative
    elif quantization is not None:
        raise ValueError("quantization requires a local GGUF path")
    fallbacks = tuple(
        ModelFallback(
            str(item.get("model_id") or ""),
            _revision(item.get("model_revision")),
            str(item.get("artifact_sha256") or ""),
            str(item.get("privacy") or ""),
            str(item.get("authority_class") or ""),
        )
        for item in fallback_chain
    )
    base: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "model_id": str(model_id),
        "model_revision": revision,
        "artifact_sha256": artifact_hash,
        "runtime": str(runtime),
        "context_tokens": context_tokens,
        "modalities": sorted(set(map(str, modalities))),
        "supports_tools": supports_tools,
        "privacy": privacy,
        "authority_class": authority_class,
        "benchmark_revision": benchmark_revision,
        "hardware_requirements": dict(
            sorted((str(key), str(value)) for key, value in hardware_requirements.items())
        ),
        "local_artifact_path": local_artifact_path,
        "quantization": quantization,
        "fallback_chain": [item.as_dict() for item in fallbacks],
    }
    content_hash = _hash(base)
    base["attachment_id"] = f"model-attachment-{content_hash[:24]}"
    base["attachment_sha256"] = _hash(base)
    attachment = ModelAttachment(
        SCHEMA_VERSION,
        str(base["attachment_id"]),
        str(model_id),
        revision,
        artifact_hash,
        str(runtime),
        context_tokens,
        tuple(base["modalities"]),  # type: ignore[arg-type]
        supports_tools,
        privacy,
        authority_class,
        benchmark_revision,
        tuple(base["hardware_requirements"].items()),  # type: ignore[union-attr]
        local_artifact_path,
        quantization,
        fallbacks,
        str(base["attachment_sha256"]),
    )
    report = validate_model_attachment(attachment, root=root)
    if not report["valid"]:
        raise ValueError("invalid model attachment: " + "; ".join(report["errors"]))
    return attachment


def validate_model_attachment(
    attachment: ModelAttachment,
    *,
    root: Path | None = None,
    expected_attachment_sha256: str | None = None,
) -> dict[str, object]:
    payload = attachment.as_dict()
    errors: list[str] = []
    for field in ("model_id", "runtime"):
        if not payload[field]:
            errors.append(f"{field} is required")
    try:
        _revision(attachment.model_revision)
    except ValueError as error:
        errors.append(str(error))
    for field in ("artifact_sha256", "benchmark_revision", "attachment_sha256"):
        if not _SHA.fullmatch(str(payload[field])):
            errors.append(f"{field} must be a sha256")
    if attachment.context_tokens < 1:
        errors.append("context_tokens must be positive")
    if not attachment.modalities:
        errors.append("at least one modality is required")
    if attachment.privacy not in _PRIVACY:
        errors.append("privacy class is invalid")
    if attachment.authority_class not in _AUTHORITY:
        errors.append("authority class is invalid")
    if not attachment.hardware_requirements:
        errors.append("hardware requirements are required")
    for fallback in attachment.fallback_chain:
        if not fallback.model_id or not _SHA.fullmatch(fallback.artifact_sha256):
            errors.append("fallback identity is incomplete")
        if fallback.privacy not in _PRIVACY or (
            attachment.privacy in _PRIVACY
            and _PRIVACY.get(fallback.privacy, -1) < _PRIVACY[attachment.privacy]
        ):
            errors.append(f"fallback {fallback.model_id} weakens privacy")
        if fallback.authority_class not in _AUTHORITY or (
            attachment.authority_class in _AUTHORITY
            and _AUTHORITY.get(fallback.authority_class, -1)
            < _AUTHORITY[attachment.authority_class]
        ):
            errors.append(f"fallback {fallback.model_id} weakens authority")
    unsigned = dict(payload)
    unsigned.pop("attachment_sha256")
    expected_id = f"model-attachment-{_hash({key: value for key, value in unsigned.items() if key != 'attachment_id'})[:24]}"
    if attachment.attachment_id != expected_id:
        errors.append("attachment_id does not match content")
    if attachment.attachment_sha256 != _hash(unsigned):
        errors.append("attachment_sha256 does not match content")
    if expected_attachment_sha256 and attachment.attachment_sha256 != expected_attachment_sha256:
        errors.append("model attachment drifted from the task plan")
    if attachment.local_artifact_path:
        if root is None:
            errors.append("root is required to verify a local artifact")
        else:
            path = root.resolve() / attachment.local_artifact_path
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != attachment.artifact_sha256:
                errors.append("local model artifact is missing or drifted")
        if not attachment.quantization:
            errors.append("local GGUF requires quantization")
    return {
        "schema_version": SCHEMA_VERSION,
        "valid": not errors,
        "attachment_id": attachment.attachment_id,
        "attachment_sha256": attachment.attachment_sha256,
        "errors": errors,
    }


def select_model_attachment(
    root: Path,
    route: object,
    inventory: Iterable[Mapping[str, object]],
    *,
    semantic_profile: Mapping[str, object] | None = None,
    required_traits: Sequence[str] = (),
    required_modalities: Sequence[str] = ("text",),
    min_context_tokens: int = 1,
    tools_required: bool = False,
    sensitive: bool = False,
    policy=None,
) -> tuple[ModelAttachment, dict[str, object]]:
    """Join task semantics, canonical ranking, inventory, and exact attachment."""
    from .models import ModelCapability, rank_models

    rows = tuple(dict(item) for item in inventory)
    if not rows:
        raise ValueError("no model inventory is available")
    available_traits = {
        str(trait) for row in rows for trait in row.get("traits", ())
    }
    envelope = getattr(route, "envelope", None)
    if envelope is None or getattr(route, "package", None) is None:
        raise TypeError("canonical route result is required")
    semantic_values = []
    if semantic_profile:
        for key in ("domains", "mechanisms", "positive_intents"):
            value = semantic_profile.get(key, ())
            if isinstance(value, (list, tuple)):
                semantic_values.extend(map(str, value))
    inferred = set(map(str, required_traits))
    inferred.update(set(map(str, envelope.semantic_concepts)) & available_traits)
    inferred.update(set(semantic_values) & available_traits)
    if not inferred and "reasoning" in available_traits:
        inferred.add("reasoning")
    modalities = set(map(str, required_modalities))
    capabilities = []
    eligible_rows = []
    for row in rows:
        row_modalities = set(map(str, row.get("modalities", ("text",))))
        if not modalities <= row_modalities:
            continue
        if tools_required and not bool(row.get("supports_tools")):
            continue
        capability = ModelCapability(
            str(row.get("model_id", "")),
            str(row.get("runtime", "")),
            bool(row.get("available")),
            int(row.get("context_tokens", 0)),
            tuple(map(str, row.get("traits", ()))),
            bool(row.get("supports_tools")),
            str(row.get("privacy", "")),
            str(row.get("cost_class", "high")),
            str(row.get("latency_class", "high")),
            float(row.get("warm_cost", 0)),
            float(row.get("cold_cost", 0)),
            tuple(map(str, row.get("failure_modes", ()))),
        )
        capabilities.append(capability)
        eligible_rows.append(row)
    ranking = rank_models(
        tuple(sorted(inferred)),
        capabilities,
        min_context_tokens=min_context_tokens,
        sensitive=sensitive,
        policy=policy,
    )
    if not ranking or ranking[0].model_id is None:
        raise ValueError("no compatible model satisfies the task plan")
    selected_route = ranking[0]
    selected = next(row for row in eligible_rows if row["model_id"] == selected_route.model_id)
    attachment = build_model_attachment(
        root,
        model_id=str(selected["model_id"]),
        model_revision=str(selected.get("model_revision", "")),
        artifact_sha256=str(selected.get("artifact_sha256", "")),
        runtime=str(selected["runtime"]),
        context_tokens=int(selected["context_tokens"]),
        modalities=tuple(map(str, selected.get("modalities", ("text",)))),
        supports_tools=bool(selected.get("supports_tools")),
        privacy=str(selected["privacy"]),
        authority_class=str(selected.get("authority_class", "contained")),
        benchmark_revision=str(selected.get("benchmark_revision", "")),
        hardware_requirements=dict(selected.get("hardware_requirements", {})),
        local_artifact_path=selected.get("local_artifact_path"),
        quantization=selected.get("quantization"),
        fallback_chain=tuple(selected.get("fallback_chain", ())),
    )
    receipt_payload = {
        "schema_version": "px.model-selection-receipt/1.0",
        "task_envelope_sha256": envelope.task_envelope_sha256,
        "package_receipt_sha256": route.package.receipt_sha256,
        "required_traits": tuple(sorted(inferred)),
        "required_modalities": tuple(sorted(modalities)),
        "min_context_tokens": min_context_tokens,
        "tools_required": tools_required,
        "sensitive": sensitive,
        "ranking": tuple(
            {
                "model_id": item.model_id,
                "score": item.score,
                "explanation": item.explanation,
                "fallback_required": item.fallback_required,
            }
            for item in ranking
        ),
        "selected_attachment_sha256": attachment.attachment_sha256,
    }
    return attachment, {**receipt_payload, "receipt_sha256": _hash(receipt_payload)}
