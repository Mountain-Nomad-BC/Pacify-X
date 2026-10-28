"""Profile-bound router presets; exact executable format must be commissioned.

This owner knows INI serialization, not llama.cpp's per-build preset dialect.
The host must supply an independently verified format declaration. CLI help
option presence alone is not evidence that a particular INI key is supported.
No model, process, routing, or certification authority is granted here.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import re
from pathlib import Path
from typing import Callable, Mapping

from .llama_cpp_capabilities import (
    LlamaCppCapabilityFingerprint, launch_policy_from_profile, render_launch_policy,
)
from .model_profile import ModelRuntimeProfile

MAX_PRESET_BYTES = 1_048_576
_SHA = re.compile(r"^[0-9a-f]{64}$")
_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


from runtime.hash_utils import json_utf8_hash as _sha


def _value(value: object) -> str:
    text = str(value)
    if not text or len(text.encode("utf-8")) > 4096 or any(ord(c) < 32 or c in "\r\n" for c in text):
        raise ValueError("router preset value must be bounded single-line text")
    # No interpolation, inline-comment, continuation, or section interpretation.
    if any(c in text for c in "[];#%") or text != text.strip():
        raise ValueError("router preset value is not safe for the commissioned INI format")
    return text


@dataclass(frozen=True, slots=True)
class RouterPresetFormat:
    schema_version: str
    executable_sha256: str
    capability_fingerprint_sha256: str
    format_evidence_sha256: str
    section_prefix: str
    section_suffix: str
    # Each row is (advertised CLI option, verified INI key, flag-only value).
    # An empty flag value means the option takes a value, rather than a flag.
    option_keys: tuple[tuple[str, str, str], ...]
    declaration_sha256: str

    def identity_payload(self) -> dict[str, object]:
        body = asdict(self)
        body.pop("declaration_sha256")
        return body

    def validate(self, fingerprint: LlamaCppCapabilityFingerprint) -> None:
        from .contracts import validate_instance
        validate_instance(json.loads(json.dumps(asdict(self))),
                          Path(__file__).resolve().parents[1] / "contracts/models/model-router-preset-format.schema.json")
        fingerprint.validate()
        if self.schema_version != "px.model-router-preset-format/1.0":
            raise ValueError("unsupported router preset format declaration")
        if (self.executable_sha256 != fingerprint.executable_sha256 or
                self.capability_fingerprint_sha256 != fingerprint.fingerprint_sha256):
            raise ValueError("router preset format belongs to a different executable fingerprint")
        if not _SHA.fullmatch(self.format_evidence_sha256):
            raise ValueError("router preset format requires actual format evidence identity")
        for affix in (self.section_prefix, self.section_suffix):
            if type(affix) is not str or len(affix) > 64 or re.fullmatch(r"[A-Za-z0-9_.:-]*", affix) is None:
                raise ValueError("router preset section affix is invalid")
        if type(self.option_keys) is not tuple or not 3 <= len(self.option_keys) <= 64:
            raise ValueError("router preset option mapping must be bounded and immutable")
        options: set[str] = set()
        keys: set[str] = set()
        for row in self.option_keys:
            if type(row) is not tuple or len(row) != 3:
                raise ValueError("router preset option mapping is malformed")
            option, key, flag_value = row
            if not fingerprint.supports(option) or option in options or not _KEY.fullmatch(key) or key.lower() in keys:
                raise ValueError("router preset key is duplicate or option is not advertised")
            if type(flag_value) is not str:
                raise ValueError("router preset flag representation must be explicit text")
            if flag_value:
                _value(flag_value)
            options.add(option)
            keys.add(key.lower())
        if self.declaration_sha256 != _sha(self.identity_payload()):
            raise ValueError("router preset format declaration digest is invalid")


@dataclass(frozen=True, slots=True)
class ModelRouterPreset:
    schema_version: str
    executable_sha256: str
    capability_fingerprint_sha256: str
    format_declaration_sha256: str
    format_evidence_sha256: str
    models: tuple[dict[str, object], ...]
    preset_sha256: str
    binding_sha256: str
    authority: bool = False

    def identity_payload(self) -> dict[str, object]:
        body = asdict(self)
        body.pop("binding_sha256")
        return body


def router_preset_format_from_mapping(payload: Mapping[str, object]) -> RouterPresetFormat:
    """Decode the complete versioned declaration without guessing missing keys."""
    expected = {"schema_version", "executable_sha256", "capability_fingerprint_sha256",
                "format_evidence_sha256", "section_prefix", "section_suffix",
                "option_keys", "declaration_sha256"}
    if type(payload) is not dict or set(payload) != expected:
        raise ValueError("router preset declaration fields are incomplete or unknown")
    rows = payload["option_keys"]
    if type(rows) is not list or not 3 <= len(rows) <= 64:
        raise ValueError("router preset declaration option mapping is not bounded")
    if any(type(row) is not list or len(row) != 3 or any(type(item) is not str for item in row) for row in rows):
        raise ValueError("router preset declaration option mapping is malformed")
    return RouterPresetFormat(**{**payload, "option_keys": tuple(tuple(row) for row in rows)})


def render_model_router_preset(
    models: Mapping[str, object], profiles: Mapping[str, ModelRuntimeProfile],
    fingerprint: LlamaCppCapabilityFingerprint, declaration: RouterPresetFormat,
    *, verify_format: Callable[[RouterPresetFormat, LlamaCppCapabilityFingerprint], None],
) -> tuple[bytes, ModelRouterPreset]:
    """Render exact bytes and a digest binding; performs no file or process effects.

    verify_format must be the commissioned host evidence consumer. It must raise
    unless evidence independently confirms this exact executable's INI dialect.
    No caller-provided boolean or self-hashed declaration substitutes for it.
    """
    if type(declaration) is not RouterPresetFormat or not callable(verify_format):
        raise ValueError("router preset format and independent host verifier are not configured")
    declaration.validate(fingerprint)
    if verify_format(declaration, fingerprint) is not None:
        raise ValueError("router preset format verifier must consume evidence or raise")
    if type(models) is not dict or type(profiles) is not dict or not 1 <= len(models) <= 128 or set(models) != set(profiles):
        raise ValueError("router preset requires exact admitted model/profile coverage")
    mapping = {option: (key, flag) for option, key, flag in declaration.option_keys}
    lines: list[str] = []
    bindings: list[dict[str, object]] = []
    for model_id in sorted(models):
        if type(model_id) is not str or _KEY.fullmatch(model_id) is None:
            raise ValueError("model identity cannot be represented by the commissioned INI format")
        profile = profiles[model_id]
        if type(profile) is not ModelRuntimeProfile or profile.model_id != model_id:
            raise ValueError("router preset profile does not match its model")
        profile.validate()
        if not profile.is_certified:
            raise ValueError("router launch requires certified frozen profiles; candidates remain unavailable")
        admission = models[model_id]
        if not getattr(admission, "compatible", False):
            raise ValueError("router preset model is not admitted")
        model_sha = getattr(admission, "model_sha256", None)
        if type(model_sha) is not str or not _SHA.fullmatch(model_sha):
            raise ValueError("router preset model has no actual artifact digest")
        # These are established server options, still required in the exact help.
        args = ("--model", str(admission.model_path), "--ctx-size", str(profile.context_tokens),
                "--parallel", str(profile.parallel_slots),
                *render_launch_policy(launch_policy_from_profile(profile), fingerprint))
        settings: dict[str, str] = {}
        index = 0
        while index < len(args):
            option = args[index]
            if option not in mapping or not fingerprint.supports(option):
                raise ValueError(f"preset format has no verified key for requested option: {option}")
            key, flag = mapping[option]
            if flag:
                value = flag
                index += 1
            else:
                if index + 1 >= len(args) or str(args[index + 1]).startswith("--"):
                    raise ValueError("preset declaration option arity conflicts with native launch policy")
                value = _value(args[index + 1])
                index += 2
            if key in settings:
                raise ValueError("preset profile repeats an INI setting")
            settings[key] = value
        section = declaration.section_prefix + model_id + declaration.section_suffix
        lines.append(f"[{section}]")
        lines.extend(f"{key}={settings[key]}" for key in sorted(settings))
        lines.append("")
        bindings.append({"model_id": model_id, "model_sha256": model_sha,
                         "profile_id": profile.profile_id, "profile_sha256": profile.profile_sha256,
                         "settings_sha256": _sha(settings)})
    data = ("\n".join(lines) + "\n").encode("utf-8")
    if len(data) > MAX_PRESET_BYTES:
        raise ValueError("router preset exceeds its bounded byte contract")
    body = {"schema_version": "px.model-router-preset/1.0",
            "executable_sha256": fingerprint.executable_sha256,
            "capability_fingerprint_sha256": fingerprint.fingerprint_sha256,
            "format_declaration_sha256": declaration.declaration_sha256,
            "format_evidence_sha256": declaration.format_evidence_sha256,
            "models": tuple(bindings), "preset_sha256": hashlib.sha256(data).hexdigest(),
            "authority": False}
    binding = ModelRouterPreset(**body, binding_sha256=_sha(body))
    from .contracts import validate_instance
    validate_instance(json.loads(json.dumps(asdict(binding))),
                      Path(__file__).resolve().parents[1] / "contracts/models/model-router-preset.schema.json")
    return data, binding
