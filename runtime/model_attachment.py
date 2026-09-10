"""Immutable exact model attachments for task execution plans."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import time
from typing import Iterable, Mapping, Sequence

from .archive_io import portable_member_name, reject_path_links
from .json_io import bounded_json_text, bounded_strings


SCHEMA_VERSION = "px.model-attachment/1.0"
_SHA = re.compile(r"^[0-9a-f]{64}$")
_FLOATING = frozenset({"latest", "main", "master", "head", "stable"})
_PRIVACY = {"policy_gated": 0, "isolated": 1, "local": 2}
_AUTHORITY = {"contained": 0, "installed_host": 1, "external_authority": 2}
MAX_ATTACHMENT_BYTES = 65536
MAX_LOCAL_ARTIFACT_BYTES = 64 * 1024 * 1024 * 1024
LOCAL_HASH_SECONDS = 300.0


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


def _text(value: object, field: str, limit: int = 256) -> str:
    if (
        type(value) is not str
        or not value.strip()
        or len(value) > limit
        or len(value.encode("utf-8")) > limit
        or any(ord(char) < 32 for char in value)
    ):
        raise ValueError(f"{field} must be bounded nonempty text")
    return value


def _local_name(value: object) -> str:
    relative = portable_member_name(
        _text(value, "local_artifact_path", 4096), allow_directory=False
    )
    if Path(relative).suffix.casefold() != ".gguf":
        raise ValueError("local model artifact must be an existing GGUF")
    if any("quarantine" in part.casefold() for part in relative.split("/")[:-1]):
        raise ValueError("local model path is excluded from acquisition")
    return relative


def _validate_attachment_payload(payload: object) -> None:
    if (
        type(payload) is not dict
        or len(payload) != len(ModelAttachment.__dataclass_fields__)
        or set(payload) != set(ModelAttachment.__dataclass_fields__)
    ):
        raise ValueError("model attachment requires the exact declared fields")
    if payload["schema_version"] != SCHEMA_VERSION:
        raise ValueError("unsupported model attachment schema_version")
    for field in ("model_id", "runtime", "attachment_id"):
        _text(payload[field], field)
    if _revision(payload["model_revision"]) != payload["model_revision"]:
        raise ValueError("model revision must use canonical exact text")
    for field in ("artifact_sha256", "benchmark_revision", "attachment_sha256"):
        if type(payload[field]) is not str or _SHA.fullmatch(payload[field]) is None:
            raise ValueError(f"{field} must be a sha256")
    if (
        type(payload["context_tokens"]) is not int
        or not 1 <= payload["context_tokens"] <= 2**31
    ):
        raise ValueError("context_tokens must be a bounded positive integer")
    if type(payload["supports_tools"]) is not bool:
        raise ValueError("supports_tools must be boolean")
    modalities = payload["modalities"]
    if type(modalities) is not list or not 1 <= len(modalities) <= 16:
        raise ValueError("modalities require a bounded nonempty list")
    for modality in modalities:
        _text(modality, "modality", 64)
    if modalities != sorted(set(modalities)):
        raise ValueError("modalities must be unique and canonically ordered")
    if type(payload["privacy"]) is not str or payload["privacy"] not in _PRIVACY:
        raise ValueError("privacy class is invalid")
    if (
        type(payload["authority_class"]) is not str
        or payload["authority_class"] not in _AUTHORITY
    ):
        raise ValueError("authority class is invalid")
    hardware = payload["hardware_requirements"]
    if type(hardware) is not dict or not 1 <= len(hardware) <= 64:
        raise ValueError("hardware requirements require a bounded nonempty object")
    for key, value in hardware.items():
        _text(key, "hardware requirement key", 64)
        _text(value, "hardware requirement value", 256)
    local = payload["local_artifact_path"]
    if local is not None:
        _local_name(local)
        _text(payload["quantization"], "local GGUF quantization", 128)
    elif payload["quantization"] is not None:
        raise ValueError("quantization requires a local GGUF path")
    fallbacks = payload["fallback_chain"]
    if type(fallbacks) is not list or len(fallbacks) > 16:
        raise ValueError("fallback_chain requires a bounded list")
    identities = set()
    for fallback in fallbacks:
        if (
            type(fallback) is not dict
            or len(fallback) != len(ModelFallback.__dataclass_fields__)
            or set(fallback) != set(ModelFallback.__dataclass_fields__)
        ):
            raise ValueError("fallback requires the exact declared identity fields")
        _text(fallback["model_id"], "fallback model_id")
        if _revision(fallback["model_revision"]) != fallback["model_revision"]:
            raise ValueError("fallback model revision must be canonical")
        if (
            type(fallback["artifact_sha256"]) is not str
            or _SHA.fullmatch(fallback["artifact_sha256"]) is None
        ):
            raise ValueError("fallback artifact_sha256 must be a sha256")
        identity = tuple(
            fallback[key] for key in ("model_id", "model_revision", "artifact_sha256")
        )
        if identity in identities:
            raise ValueError("fallback identities must be unique")
        identities.add(identity)
        if (
            type(fallback["privacy"]) is not str
            or _PRIVACY.get(fallback["privacy"], -1) < _PRIVACY[payload["privacy"]]
        ):
            raise ValueError("fallback weakens privacy")
        if (
            type(fallback["authority_class"]) is not str
            or _AUTHORITY.get(fallback["authority_class"], -1)
            < _AUTHORITY[payload["authority_class"]]
        ):
            raise ValueError("fallback weakens authority")
    bounded_json_text(payload, max_bytes=MAX_ATTACHMENT_BYTES)


def _verify_local_model(root: Path, relative: str, expected_hash: str) -> None:
    reject_path_links(root)
    resolved_root = root.resolve(strict=True)
    path = root / _local_name(relative)
    reject_path_links(path)
    if not path.resolve(strict=True).is_relative_to(resolved_root):
        raise ValueError("local model path escapes the project")
    before = path.stat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("local model artifact must be a regular GGUF file")
    if before.st_size > MAX_LOCAL_ARTIFACT_BYTES:
        raise ValueError("local model artifact exceeds its byte budget")
    digest = hashlib.sha256()
    count = 0
    deadline = time.monotonic() + LOCAL_HASH_SECONDS
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino, opened.st_size) != (
            before.st_dev,
            before.st_ino,
            before.st_size,
        ):
            raise ValueError("local model changed before acquisition")
        while count <= before.st_size:
            if time.monotonic() > deadline:
                raise ValueError(
                    "local model hashing exceeded its cooperative duration budget"
                )
            chunk = stream.read(min(65536, before.st_size + 1 - count))
            if not chunk:
                break
            count += len(chunk)
            if count > before.st_size:
                raise ValueError("local model changed during acquisition")
            digest.update(chunk)
        after = os.fstat(stream.fileno())
    if count != before.st_size or (after.st_size, after.st_mtime_ns) != (
        before.st_size,
        before.st_mtime_ns,
    ):
        raise ValueError("local model changed during acquisition")
    if digest.hexdigest() != expected_hash:
        raise ValueError("local model artifact hash does not match or has drifted")


def model_attachment_from_dict(payload: Mapping[str, object]) -> ModelAttachment:
    """Decode an attachment without weakening its content validation."""
    _validate_attachment_payload(payload)
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
    revision = _text(value, "model revision").strip()
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
    model_id = _text(model_id, "model_id")
    runtime = _text(runtime, "runtime")
    revision = _revision(model_revision)
    artifact_hash = _text(artifact_sha256, "artifact_sha256", 64).casefold()
    if type(modalities) not in (tuple, list) or not 1 <= len(modalities) <= 16:
        raise ValueError("modalities require a bounded nonempty sequence")
    modalities = tuple(_text(item, "modality", 64) for item in modalities)
    if (
        type(hardware_requirements) is not dict
        or not 1 <= len(hardware_requirements) <= 64
    ):
        raise ValueError("hardware requirements require a bounded nonempty object")
    normalized_hardware = {}
    for key, value in hardware_requirements.items():
        _text(key, "hardware requirement key", 64)
        if type(value) not in (str, int, float, bool):
            raise ValueError("hardware requirement values must be scalar metadata")
        if type(value) in (int, float) and (
            abs(value) > 1e100 or not math.isfinite(value)
        ):
            raise ValueError(
                "hardware requirement numeric value is not bounded finite metadata"
            )
        normalized_hardware[key] = _text(str(value), "hardware requirement value", 256)
    hardware_requirements = normalized_hardware
    if local_artifact_path is not None:
        local_artifact_path = _local_name(local_artifact_path)
        if not quantization:
            raise ValueError("local GGUF requires exact quantization")
    elif quantization is not None:
        raise ValueError("quantization requires a local GGUF path")
    if type(fallback_chain) not in (tuple, list) or len(fallback_chain) > 16:
        raise ValueError("fallback_chain requires a bounded sequence")
    if any(
        type(item) is not dict
        or len(item) != len(ModelFallback.__dataclass_fields__)
        or set(item) != set(ModelFallback.__dataclass_fields__)
        for item in fallback_chain
    ):
        raise ValueError("fallback requires the exact declared identity fields")
    fallbacks = tuple(
        ModelFallback(
            item["model_id"],
            _revision(item.get("model_revision")),
            item["artifact_sha256"],
            item["privacy"],
            item["authority_class"],
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
            sorted(
                (str(key), str(value)) for key, value in hardware_requirements.items()
            )
        ),
        "local_artifact_path": local_artifact_path,
        "quantization": quantization,
        "fallback_chain": [item.as_dict() for item in fallbacks],
    }
    _validate_attachment_payload(
        {**base, "attachment_id": "unsealed-attachment", "attachment_sha256": "0" * 64}
    )
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
    try:
        if type(attachment) is not ModelAttachment:
            raise ValueError("typed model attachment is required")
        for field, limit in (
            ("modalities", 16),
            ("hardware_requirements", 64),
            ("fallback_chain", 16),
        ):
            value = getattr(attachment, field)
            if type(value) is not tuple or len(value) > limit:
                raise ValueError(f"{field} requires a bounded immutable tuple")
        if any(type(item) is not ModelFallback for item in attachment.fallback_chain):
            raise ValueError("fallback_chain requires typed fallback identities")
        keys = []
        for row in attachment.hardware_requirements:
            if type(row) is not tuple or len(row) != 2:
                raise ValueError("hardware requirement pair is malformed")
            keys.append(_text(row[0], "hardware requirement key", 64))
        if len(set(keys)) != len(keys):
            raise ValueError("hardware requirement keys must be unique")
        payload = attachment.as_dict()
        _validate_attachment_payload(payload)
    except (ValueError, TypeError, AttributeError) as error:
        return {
            "schema_version": SCHEMA_VERSION,
            "valid": False,
            "attachment_id": None,
            "attachment_sha256": None,
            "errors": [str(error)],
        }
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
    if (
        expected_attachment_sha256
        and attachment.attachment_sha256 != expected_attachment_sha256
    ):
        errors.append("model attachment drifted from the task plan")
    if attachment.local_artifact_path:
        if root is None:
            errors.append("root is required to verify a local artifact")
        else:
            if not errors:
                try:
                    _verify_local_model(
                        root, attachment.local_artifact_path, attachment.artifact_sha256
                    )
                except (OSError, ValueError) as error:
                    errors.append(str(error))
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
    from .models import (
        MAX_MODEL_CANDIDATES,
        ModelCapability,
        rank_models,
        validate_model_capability,
    )

    rows = []
    capabilities_by_id = {}
    seen_ids = set()
    if isinstance(inventory, (str, bytes, Mapping)):
        raise ValueError("model inventory requires bounded records")
    for item in inventory:
        if len(rows) >= MAX_MODEL_CANDIDATES:
            raise ValueError("model inventory record budget exceeded")
        if type(item) is not dict or len(item) > 64:
            raise ValueError("model inventory row requires a bounded object")
        model_id = _text(item.get("model_id"), "model_id")
        if model_id in seen_ids:
            raise ValueError("duplicate model inventory identity")
        seen_ids.add(model_id)
        row = dict(item)
        capability = ModelCapability(
            row["model_id"],
            row.get("runtime", ""),
            row.get("available", False),
            row.get("context_tokens", 0),
            row.get("traits", ()),
            row.get("supports_tools", False),
            row.get("privacy", ""),
            row.get("cost_class", "high"),
            row.get("latency_class", "high"),
            row.get("warm_cost", 0),
            row.get("cold_cost", 0),
            row.get("failure_modes", ()),
        )
        validate_model_capability(capability)
        capabilities_by_id[model_id] = capability
        row["traits"] = bounded_strings(
            capability.traits, max_items=64, max_item_bytes=256, max_bytes=16384
        )
        row["failure_modes"] = bounded_strings(
            capability.failure_modes, max_items=64, max_item_bytes=256, max_bytes=16384
        )
        row_modalities = row.get("modalities", ("text",))
        if type(row_modalities) not in (tuple, list):
            raise ValueError("model modalities require a bounded string sequence")
        row["modalities"] = bounded_strings(
            row_modalities, max_items=16, max_item_bytes=64, max_bytes=1024
        )
        rows.append(row)
    if not rows:
        raise ValueError("no model inventory is available")
    available_traits = {trait for row in rows for trait in row["traits"]}
    envelope = getattr(route, "envelope", None)
    if envelope is None or getattr(route, "package", None) is None:
        raise TypeError("canonical route result is required")
    semantic_values = []
    if semantic_profile is not None:
        if type(semantic_profile) is not dict or len(semantic_profile) > 64:
            raise ValueError("semantic profile requires a bounded object")
        for key in ("domains", "mechanisms", "positive_intents"):
            value = semantic_profile.get(key, ())
            if type(value) not in (list, tuple):
                raise ValueError(
                    "semantic requirements require bounded string sequences"
                )
            semantic_values.extend(
                bounded_strings(
                    value, max_items=512, max_item_bytes=256, max_bytes=65536
                )
            )
    inferred = set(
        bounded_strings(
            required_traits, max_items=64, max_item_bytes=256, max_bytes=16384
        )
    )
    inferred.update(
        set(
            bounded_strings(
                envelope.semantic_concepts,
                max_items=512,
                max_item_bytes=256,
                max_bytes=65536,
            )
        )
        & available_traits
    )
    inferred.update(set(semantic_values) & available_traits)
    if not inferred and "reasoning" in available_traits:
        inferred.add("reasoning")
    modalities = set(
        bounded_strings(
            required_modalities, max_items=16, max_item_bytes=64, max_bytes=1024
        )
    )
    if not modalities or type(tools_required) is not bool:
        raise ValueError(
            "model requirements need nonempty modalities and boolean tool support"
        )
    capabilities = []
    eligible_rows = []
    for row in rows:
        row_modalities = set(row["modalities"])
        if not modalities <= row_modalities:
            continue
        if tools_required and not capabilities_by_id[row["model_id"]].supports_tools:
            continue
        capabilities.append(capabilities_by_id[row["model_id"]])
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
    selected = next(
        row for row in eligible_rows if row["model_id"] == selected_route.model_id
    )
    attachment = build_model_attachment(
        root,
        model_id=selected["model_id"],
        model_revision=selected.get("model_revision", ""),
        artifact_sha256=selected.get("artifact_sha256", ""),
        runtime=selected["runtime"],
        context_tokens=selected["context_tokens"],
        modalities=selected["modalities"],
        supports_tools=capabilities_by_id[selected["model_id"]].supports_tools,
        privacy=selected["privacy"],
        authority_class=selected.get("authority_class", "contained"),
        benchmark_revision=selected.get("benchmark_revision", ""),
        hardware_requirements=selected.get("hardware_requirements", {}),
        local_artifact_path=selected.get("local_artifact_path"),
        quantization=selected.get("quantization"),
        fallback_chain=selected.get("fallback_chain", ()),
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
