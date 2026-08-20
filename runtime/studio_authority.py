"""Project-scoped authenticated authority registry for Studio control planes.

The registry does not create host authority.  It preserves PX admission decisions
against casual record substitution and forces runtimes to resolve current records
instead of accepting authoritative dataclass objects from callers. Secret HMAC keys
remain in host-only state while portable project identities travel with the project.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from .file_lock import FileLock
from .studio_models import (
    CapabilityBinding,
    EffectGrant,
    canonical_bytes,
    verify_safe_ancestors,
    write_json_atomic,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime | None = None) -> str:
    return (value or _now()).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def studio_authority_locator_environment(
    source: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Forward only host-state locators needed to resolve the same authority key.

    These values identify storage locations; authority key bytes and unrelated
    parent environment values never cross the worker boundary.
    """

    environment = source if source is not None else os.environ
    locators = {
        name: str(environment[name])
        for name in ("PX_STUDIO_KEY_ROOT", "XDG_STATE_HOME", "LOCALAPPDATA")
        if str(environment.get(name, "")).strip()
    }
    configured_root = locators.get("PX_STUDIO_KEY_ROOT")
    if configured_root:
        candidate = Path(configured_root).expanduser()
        if not candidate.is_absolute():
            raise ValueError("PX_STUDIO_KEY_ROOT must be an absolute path")
        locators["PX_STUDIO_KEY_ROOT"] = str(candidate.resolve(strict=False))
    return locators


def _base64url_decode(value: str) -> bytes:
    encoded = value.encode("ascii")
    return base64.urlsafe_b64decode(encoded + b"=" * (-len(encoded) % 4))


def _rsa_pkcs1_sha256_verify(
    public_key: Mapping[str, Any], message: bytes, signature: str
) -> bool:
    """Verify an RS256 signature without introducing a runtime dependency.

    The VS Code host owns the private RSA key in SecretStorage. Python only
    receives the public JWK and performs the narrow PKCS#1 v1.5 verification
    needed for exact Studio approval claims.
    """

    if (
        set(public_key) != {"kty", "n", "e"}
        or public_key.get("kty") != "RSA"
    ):
        return False
    try:
        modulus_bytes = _base64url_decode(str(public_key["n"]))
        exponent_bytes = _base64url_decode(str(public_key["e"]))
        signature_bytes = _base64url_decode(signature)
        modulus = int.from_bytes(modulus_bytes, "big")
        exponent = int.from_bytes(exponent_bytes, "big")
    except (KeyError, TypeError, ValueError, UnicodeError):
        return False
    if (
        len(modulus_bytes) < 256
        or exponent < 3
        or len(signature_bytes) != len(modulus_bytes)
    ):
        return False
    decoded = pow(int.from_bytes(signature_bytes, "big"), exponent, modulus).to_bytes(
        len(modulus_bytes), "big"
    )
    digest_info = bytes.fromhex("3031300d060960864801650304020105000420") + hashlib.sha256(
        message
    ).digest()
    padding_length = len(decoded) - len(digest_info) - 3
    if padding_length < 8:
        return False
    expected = b"\x00\x01" + (b"\xff" * padding_length) + b"\x00" + digest_info
    return hmac.compare_digest(decoded, expected)


class StudioAuthorityStore:
    """Authenticated canonical records scoped to exactly one project root."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve(strict=True)
        self.root = (
            self.project_root / ".engineering-bootstrap" / "studios" / "authority"
        )
        verify_safe_ancestors(self.project_root, self.root / "placeholder")
        self.root.mkdir(parents=True, exist_ok=True)
        verify_safe_ancestors(self.project_root, self.root / "placeholder")
        identity_path = self.root / "project-identity.json"
        if identity_path.is_file():
            identity = json.loads(identity_path.read_text(encoding="utf-8"))
            self.project_identity = str(identity.get("project_identity") or "")
        else:
            self.project_identity = f"px-project-{uuid4().hex}"
            write_json_atomic(identity_path, {
                "schema_version": "px.studio-project-identity/1.0",
                "project_identity": self.project_identity,
            })
        if not self.project_identity.startswith("px-project-"):
            raise ValueError("studio project identity is invalid")
        configured_root = os.environ.get("PX_STUDIO_KEY_ROOT", "").strip()
        if configured_root:
            key_root = Path(configured_root).expanduser()
            if not key_root.is_absolute():
                raise ValueError("PX_STUDIO_KEY_ROOT must be an absolute path")
        elif os.name == "nt":
            local_app_data = os.environ.get("LOCALAPPDATA")
            key_root = (Path(local_app_data) if local_app_data else Path.home() / "AppData/Local") / "Pacify-X" / "authority-keys"
        else:
            key_root = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "pacify-x" / "authority-keys"
        key_root = key_root.resolve(strict=False)
        if key_root == self.project_root or self.project_root in key_root.parents:
            raise ValueError("Studio authority key root must remain outside the project")
        key_root.mkdir(parents=True, exist_ok=True)
        self.key_root = key_root.resolve(strict=True)
        self.key_path = self.key_root / f"{self.project_identity}.key"
        self.approval_verifier_path = (
            self.key_root / "approval-verifiers" / f"{self.project_identity}.json"
        )
        legacy_key = self.root / ".receipt-key"
        migrated = False
        legacy_backup: Path | None = None
        if not self.key_path.exists():
            prepared = key_root / f".{self.project_identity}.{uuid4().hex}.prepared"
            if legacy_key.is_file():
                legacy_bytes = legacy_key.read_bytes()
                if len(legacy_bytes) != 32:
                    raise ValueError("legacy studio authority key has invalid identity")
                legacy_backup = key_root / "backups" / self.project_identity / f"legacy-{uuid4().hex}.key"
                legacy_backup.parent.mkdir(parents=True, exist_ok=True)
                prepared.write_bytes(legacy_bytes)
                migrated = True
            else:
                prepared.write_bytes(os.urandom(32))
            try:
                os.chmod(prepared, 0o600)
            except OSError:
                pass
            os.replace(prepared, self.key_path)
        if legacy_key.is_file():
            if legacy_key.read_bytes() != self.key_path.read_bytes():
                raise PermissionError("host and legacy Studio authority keys conflict")
            if legacy_backup is None:
                legacy_backup = key_root / "backups" / self.project_identity / f"legacy-{uuid4().hex}.key"
                legacy_backup.parent.mkdir(parents=True, exist_ok=True)
            os.replace(legacy_key, legacy_backup)
            migrated = True
        self._key = self.key_path.read_bytes()
        if len(self._key) != 32:
            raise ValueError("studio authority key has invalid identity")
        if migrated:
            write_json_atomic(
                self.root / "key-migration-receipt.json",
                self.sign({
                    "schema_version": "px.studio-key-migration/1.0",
                    "project_identity": self.project_identity,
                    "host_secure_storage": True,
                    "legacy_key_removed_from_project": True,
                    "recoverable_backup_retained_outside_project": True,
                    "threat_model": "protects against repository-only readers; same-user host compromise remains out of scope",
                }),
            )

    @classmethod
    def open_existing(cls, project_root: Path) -> "StudioAuthorityStore":
        """Open existing verification material without initializing or migrating state."""
        instance = cls.__new__(cls)
        instance.project_root = project_root.resolve(strict=True)
        instance.root = (
            instance.project_root
            / ".engineering-bootstrap"
            / "studios"
            / "authority"
        )
        verify_safe_ancestors(instance.project_root, instance.root / "placeholder")
        if not instance.root.is_dir() or instance.root.is_symlink():
            raise FileNotFoundError("Studio authority has not been initialized")
        identity_path = instance.root / "project-identity.json"
        if not identity_path.is_file() or identity_path.is_symlink():
            raise FileNotFoundError("Studio project identity is unavailable")
        identity = json.loads(identity_path.read_text(encoding="utf-8"))
        instance.project_identity = str(identity.get("project_identity") or "")
        if not instance.project_identity.startswith("px-project-"):
            raise ValueError("studio project identity is invalid")
        configured_root = os.environ.get("PX_STUDIO_KEY_ROOT", "").strip()
        if configured_root:
            key_root = Path(configured_root).expanduser()
            if not key_root.is_absolute():
                raise ValueError("PX_STUDIO_KEY_ROOT must be an absolute path")
        elif os.name == "nt":
            local_app_data = os.environ.get("LOCALAPPDATA")
            key_root = (
                Path(local_app_data)
                if local_app_data
                else Path.home() / "AppData/Local"
            ) / "Pacify-X" / "authority-keys"
        else:
            key_root = Path(
                os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")
            ) / "pacify-x" / "authority-keys"
        instance.key_root = key_root.resolve(strict=True)
        if (
            instance.key_root == instance.project_root
            or instance.project_root in instance.key_root.parents
        ):
            raise ValueError("Studio authority key root must remain outside the project")
        instance.key_path = instance.key_root / f"{instance.project_identity}.key"
        instance.approval_verifier_path = (
            instance.key_root
            / "approval-verifiers"
            / f"{instance.project_identity}.json"
        )
        if not instance.key_path.is_file() or instance.key_path.is_symlink():
            raise FileNotFoundError("Studio authority verification key is unavailable")
        instance._key = instance.key_path.read_bytes()
        if len(instance._key) != 32:
            raise ValueError("studio authority key has invalid identity")
        return instance

    def sign(self, value: Mapping[str, Any]) -> dict[str, Any]:
        unsigned = {
            str(key): item for key, item in value.items() if key != "authentication"
        }
        authentication = {
            "algorithm": "hmac-sha256",
            "issuer": "px-project-studio-authority",
            "project_identity": self.project_identity,
            "payload_sha256": hashlib.sha256(canonical_bytes(unsigned)).hexdigest(),
        }
        authentication["mac"] = hmac.new(
            self._key,
            canonical_bytes({**unsigned, "authentication": authentication}),
            hashlib.sha256,
        ).hexdigest()
        return {**unsigned, "authentication": authentication}

    def verify(self, value: Mapping[str, Any]) -> dict[str, Any]:
        authentication = value.get("authentication")
        if not isinstance(authentication, Mapping):
            raise PermissionError("authenticated Studio record is required")
        unsigned = {
            str(key): item for key, item in value.items() if key != "authentication"
        }
        auth_without_mac = {
            str(key): item for key, item in authentication.items() if key != "mac"
        }
        expected = hmac.new(
            self._key,
            canonical_bytes({**unsigned, "authentication": auth_without_mac}),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(str(authentication.get("mac", "")), expected):
            raise PermissionError("Studio record authentication failed")
        if "project_identity" in authentication:
            if authentication.get("project_identity") != self.project_identity:
                raise PermissionError("Studio record belongs to a different project")
        elif authentication.get("project_root_sha256") != hashlib.sha256(
            str(self.project_root).encode("utf-8")
        ).hexdigest():
            # Legacy receipts remain readable at their original root after the
            # secret is migrated; all newly signed receipts are root-portable.
            raise PermissionError("legacy Studio record belongs to a different project root")
        if (
            authentication.get("payload_sha256")
            != hashlib.sha256(canonical_bytes(unsigned)).hexdigest()
        ):
            raise PermissionError("Studio record payload identity failed")
        return unsigned

    def _path(self, kind: str, identity: str) -> Path:
        component = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        return self.root / kind / f"{component}.json"

    def _publish_unlocked(
        self, kind: str, identity: str, record: Mapping[str, Any]
    ) -> dict[str, Any]:
        value = self.sign(
            {
                "schema_version": f"px.studio-authority-{kind}/1.0",
                "record": dict(record),
                "record_sha256": hashlib.sha256(canonical_bytes(record)).hexdigest(),
                "issued_utc": _timestamp(),
                "nonce": uuid4().hex,
            }
        )
        path = self._path(kind, identity)
        verify_safe_ancestors(self.project_root, path)
        write_json_atomic(path, value)
        return value

    def _publish(
        self, kind: str, identity: str, record: Mapping[str, Any]
    ) -> dict[str, Any]:
        with FileLock(self.root / ".authority.lock", timeout_seconds=10):
            return self._publish_unlocked(kind, identity, record)

    def register_authority_transaction(
        self,
        bindings: tuple[CapabilityBinding, ...],
        grants: tuple[EffectGrant, ...],
        executors: Mapping[str, str] | None = None,
    ) -> dict[str, object]:
        """Publish one fully prevalidated authority set with compensating rollback."""
        executor_map = {str(key): str(value) for key, value in (executors or {}).items()}
        grant_map = {grant.grant_id: grant for grant in grants}
        binding_map = {binding.binding_id: binding for binding in bindings}
        if len(grant_map) != len(grants) or len(binding_map) != len(bindings):
            raise ValueError("authority transaction contains duplicate identities")
        if any(grant.state != "admitted" for grant in grants):
            raise ValueError("authority transaction contains a non-admitted grant")
        if any(binding.state != "admitted" for binding in bindings):
            raise ValueError("authority transaction contains a non-admitted binding")
        subjects = {grant.subject_id for grant in grants} | {binding.subject_id for binding in bindings}
        if len(subjects) != 1:
            raise ValueError("authority transaction must belong to exactly one subject")
        capability_records: dict[str, dict[str, object]] = {}
        referenced_grants: set[str] = set()
        for binding in bindings:
            referenced = [grant_map.get(grant_id) for grant_id in binding.effect_grant_ids]
            if not referenced or any(grant is None for grant in referenced):
                raise ValueError(f"binding references a grant outside this transaction: {binding.binding_id}")
            if any(grant.subject_id != binding.subject_id for grant in referenced if grant):
                raise ValueError(f"binding/grant subject mismatch: {binding.binding_id}")
            referenced_grants.update(binding.effect_grant_ids)
            effects = sorted({effect for grant in referenced if grant for effect in grant.effects})
            identity = f"{binding.capability_id}@{binding.capability_version}"
            record = {
                "capability_id": binding.capability_id,
                "version": binding.capability_version,
                "effects": effects,
                "state": "admitted",
                "approved_by": next(grant.approved_by for grant in referenced if grant),
            }
            prior = capability_records.get(identity)
            if prior is not None and prior != record:
                raise ValueError(f"one capability version has conflicting authority definitions: {identity}")
            capability_records[identity] = record
            adapter = executor_map.get(binding.binding_id)
            if adapter is not None and adapter not in {"identity", "increment", "double", "fail", "sleep"}:
                raise ValueError(f"workflow executor adapter is not in the closed registry: {adapter}")
        unknown_executors = sorted(set(executor_map) - set(binding_map))
        if unknown_executors:
            raise ValueError(f"executor adapters reference unknown bindings: {unknown_executors}")
        if referenced_grants != set(grant_map):
            raise ValueError("authority transaction contains orphan or omitted grants")

        planned: list[tuple[str, str, Mapping[str, Any]]] = []
        planned.extend(("grants", grant.grant_id, asdict(grant)) for grant in grants)
        planned.extend(("capabilities", identity, record) for identity, record in sorted(capability_records.items()))
        planned.extend(("bindings", binding.binding_id, asdict(binding)) for binding in bindings)
        for binding_id, adapter in sorted(executor_map.items()):
            binding = binding_map[binding_id]
            planned.append(("executors", binding_id, {
                "binding_id": binding_id,
                "adapter_id": adapter,
                "state": "admitted",
                "approved_by": next(grant_map[item].approved_by for item in binding.effect_grant_ids),
            }))

        originals: dict[Path, bytes | None] = {}
        published: list[dict[str, Any]] = []
        transaction_id = f"authority-{uuid4().hex}"
        with FileLock(self.root / ".authority.lock", timeout_seconds=10):
            for identity, record in capability_records.items():
                path = self._path("capabilities", identity)
                if path.is_file():
                    existing = self._resolve("capabilities", identity)
                    semantic_fields = ("capability_id", "version", "effects", "state")
                    if any(existing.get(field) != record.get(field) for field in semantic_fields):
                        raise PermissionError(f"capability version is immutable and already differs: {identity}")
                    record.clear()
                    record.update(existing)
            try:
                for kind, identity, record in planned:
                    path = self._path(kind, identity)
                    originals[path] = path.read_bytes() if path.is_file() else None
                    if originals[path] is not None:
                        history = self.root / "history" / kind / path.stem / f"{transaction_id}.json"
                        write_json_atomic(history, json.loads(originals[path].decode("utf-8")))
                    published.append(self._publish_unlocked(kind, identity, record))
            except Exception:
                for path, original in reversed(list(originals.items())):
                    if original is None:
                        path.unlink(missing_ok=True)
                    else:
                        write_json_atomic(path, json.loads(original.decode("utf-8")))
                raise
        return {
            "schema_version": "px.studio-authority-transaction/1.0",
            "transaction_id": transaction_id,
            "status": "registered",
            "authenticated": True,
            "records_published": len(published),
            "bindings_registered": len(bindings),
            "grants_registered": len(grants),
            "executors_registered": len(executor_map),
            "rollback": "compensating restore completed on publication failure",
        }

    def _resolve(self, kind: str, identity: str) -> dict[str, Any]:
        path = self._path(kind, identity)
        if not path.is_file():
            raise PermissionError(f"canonical {kind} record is missing: {identity}")
        value = json.loads(path.read_text(encoding="utf-8"))
        unsigned = self.verify(value)
        record = unsigned.get("record")
        if (
            not isinstance(record, Mapping)
            or unsigned.get("record_sha256")
            != hashlib.sha256(canonical_bytes(record)).hexdigest()
        ):
            raise PermissionError(
                f"canonical {kind} record identity failed: {identity}"
            )
        return dict(record)

    def admit_capability(
        self,
        capability_id: str,
        version: str,
        effects: tuple[str, ...],
        *,
        approved_by: str,
    ) -> dict[str, Any]:
        if not approved_by.strip() or not effects:
            raise ValueError("capability admission requires approver and effects")
        return self._publish(
            "capabilities",
            f"{capability_id}@{version}",
            {
                "capability_id": capability_id,
                "version": version,
                "effects": list(effects),
                "state": "admitted",
                "approved_by": approved_by,
            },
        )

    def admit_grant(self, grant: EffectGrant) -> dict[str, Any]:
        if grant.state != "admitted":
            raise ValueError(
                "only an admitted effect grant may enter canonical authority"
            )
        return self._publish("grants", grant.grant_id, asdict(grant))

    def admit_binding(self, binding: CapabilityBinding) -> dict[str, Any]:
        if binding.state != "admitted":
            raise ValueError("only an admitted binding may enter canonical authority")
        return self._publish("bindings", binding.binding_id, asdict(binding))

    def resolve_grant(
        self, grant_id: str, *, subject_id: str, required_effects: tuple[str, ...] = ()
    ) -> tuple[dict[str, Any], str]:
        record = self._resolve("grants", grant_id)
        if record.get("state") != "admitted" or record.get("subject_id") != subject_id:
            raise PermissionError(f"effect grant subject/state mismatch: {grant_id}")
        expiry = record.get("expires_utc")
        if (
            expiry
            and datetime.fromisoformat(str(expiry).replace("Z", "+00:00")) <= _now()
        ):
            raise PermissionError(f"effect grant expired: {grant_id}")
        if (
            not record.get("approved_by")
            or not record.get("evidence_refs")
            or not record.get("scope_roots")
        ):
            raise PermissionError(f"effect grant authority is incomplete: {grant_id}")
        if not set(required_effects).issubset(set(record.get("effects", []))):
            raise PermissionError(
                f"effect grant does not cover required effects: {grant_id}"
            )
        return record, hashlib.sha256(canonical_bytes(record)).hexdigest()

    def resolve_binding(
        self, binding_id: str, *, subject_kind: str, subject_id: str
    ) -> tuple[dict[str, Any], str]:
        record = self._resolve("bindings", binding_id)
        if (
            record.get("state") != "admitted"
            or record.get("subject_kind") != subject_kind
            or record.get("subject_id") != subject_id
        ):
            raise PermissionError(
                f"capability binding subject/state mismatch: {binding_id}"
            )
        capability_id = str(record.get("capability_id", ""))
        version = str(record.get("capability_version", ""))
        capability = self._resolve("capabilities", f"{capability_id}@{version}")
        if capability.get("state") != "admitted":
            raise PermissionError(
                f"capability is not admitted: {capability_id}@{version}"
            )
        grant_ids = tuple(str(item) for item in record.get("effect_grant_ids", []))
        granted_effects: set[str] = set()
        for grant_id in grant_ids:
            grant, _ = self.resolve_grant(
                grant_id,
                subject_id=subject_id,
            )
            granted_effects.update(str(item) for item in grant.get("effects", []))
        if not set(str(item) for item in capability.get("effects", [])).issubset(
            granted_effects
        ):
            raise PermissionError(
                f"combined effect grants do not cover capability effects: {binding_id}"
            )
        if (
            not record.get("cost_policy")
            or not record.get("egress_policy")
            or not record.get("evidence_refs")
        ):
            raise PermissionError(
                f"capability binding policy is incomplete: {binding_id}"
            )
        return record, hashlib.sha256(canonical_bytes(record)).hexdigest()

    def sign_receipt(self, receipt: Mapping[str, Any]) -> dict[str, Any]:
        return self.sign(receipt)

    def verify_receipt(self, receipt: Mapping[str, Any]) -> dict[str, Any]:
        return self.verify(receipt)

    def consume_host_operation_approval(
        self,
        proof: Mapping[str, Any],
        *,
        kind: str,
        operation: str,
        supplied_payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if set(proof) != {"claim", "payload_json", "signature"} or not isinstance(
            proof.get("claim"), Mapping
        ):
            raise PermissionError("host-signed Studio approval proof is required")
        payload_json = proof.get("payload_json")
        if not isinstance(payload_json, str):
            raise PermissionError("host-signed Studio approval payload bytes are required")
        try:
            payload_bytes = payload_json.encode("utf-8")
        except UnicodeEncodeError as error:
            raise PermissionError("host-signed Studio approval payload is invalid") from error
        if len(payload_bytes) > 256 * 1024:
            raise PermissionError("host-signed Studio approval payload exceeds 256 KiB")
        try:
            approved_payload = json.loads(payload_json)
        except (json.JSONDecodeError, UnicodeError) as error:
            raise PermissionError("host-signed Studio approval payload is invalid") from error
        if not isinstance(approved_payload, Mapping):
            raise PermissionError("host-signed Studio approval payload must be an object")
        if supplied_payload is not None and dict(approved_payload) != dict(supplied_payload):
            raise PermissionError("operation approval does not match the exact payload")
        payload_sha256 = hashlib.sha256(payload_bytes).hexdigest()
        claim = dict(proof["claim"])
        required_claim = {
            "schema_version", "project_identity", "kind", "operation",
            "payload_sha256", "approved_by", "issued_utc", "expires_utc",
            "nonce", "key_id",
        }
        if set(claim) != required_claim:
            raise PermissionError("Studio approval claim shape is invalid")
        try:
            verifier = json.loads(
                self.approval_verifier_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as error:
            raise PermissionError("Studio host approval verifier is not enrolled") from error
        required_verifier = {
            "schema_version", "project_identity", "host_surface", "approved_by",
            "key_id", "public_key_jwk", "created_utc", "revision", "rotation",
        }
        public_key = verifier.get("public_key_jwk")
        if (
            set(verifier) != required_verifier
            or verifier.get("schema_version") != "px.studio-host-approval-verifier/2.0"
            or verifier.get("project_identity") != self.project_identity
            or verifier.get("host_surface") != "vscode-extension-host"
            or verifier.get("approved_by") != "human:vscode-local-user"
            or not isinstance(public_key, Mapping)
            or verifier.get("key_id")
            != hashlib.sha256(canonical_bytes(public_key)).hexdigest()
        ):
            raise PermissionError("Studio host approval verifier is invalid")
        if (
            claim.get("schema_version") != "px.studio-host-approval/2.1"
            or claim.get("project_identity") != self.project_identity
            or claim.get("kind") != kind
            or claim.get("operation") != operation
            or claim.get("payload_sha256") != payload_sha256
            or claim.get("approved_by") != "human:vscode-local-user"
            or claim.get("key_id") != verifier.get("key_id")
            or not isinstance(claim.get("nonce"), str)
            or len(str(claim.get("nonce"))) < 32
        ):
            raise PermissionError("operation approval does not match the exact payload")
        try:
            issued = datetime.fromisoformat(
                str(claim["issued_utc"]).replace("Z", "+00:00")
            )
            expires = datetime.fromisoformat(
                str(claim["expires_utc"]).replace("Z", "+00:00")
            )
        except (KeyError, ValueError) as error:
            raise PermissionError("operation approval timestamps are invalid") from error
        now = _now()
        if (
            issued.tzinfo is None
            or expires.tzinfo is None
            or issued > now + timedelta(seconds=30)
            or expires <= now
            or expires - issued > timedelta(seconds=300)
        ):
            raise PermissionError("operation approval expired")
        if not _rsa_pkcs1_sha256_verify(
            public_key, canonical_bytes(claim), str(proof.get("signature", ""))
        ):
            raise PermissionError("Studio approval host signature is invalid")
        nonce = str(claim["nonce"])
        marker = self.root / "operation-approval-consumption" / f"{hashlib.sha256(nonce.encode()).hexdigest()}.json"
        marker.parent.mkdir(parents=True, exist_ok=True)
        verify_safe_ancestors(self.project_root, marker)
        try:
            descriptor = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as error:
            raise PermissionError("operation approval replay denied") from error
        consumption = self.sign(
            {
                "schema_version": "px.studio-operation-approval-consumption/1.0",
                "approval_nonce_sha256": hashlib.sha256(nonce.encode()).hexdigest(),
                "approval_key_id": claim["key_id"],
                "kind": kind,
                "operation": operation,
                "payload_sha256": payload_sha256,
                "consumed_utc": _timestamp(),
            }
        )
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(consumption, stream, sort_keys=True)
            stream.write("\n")
        return {**claim, "payload": dict(approved_payload)}

    def admit_executor(
        self, binding_id: str, adapter_id: str, *, approved_by: str
    ) -> dict[str, Any]:
        if adapter_id not in {"identity", "increment", "double", "fail", "sleep"}:
            raise ValueError("workflow executor adapter is not in the closed registry")
        if not approved_by.strip():
            raise ValueError("workflow executor admission requires an approver")
        return self._publish(
            "executors",
            binding_id,
            {
                "binding_id": binding_id,
                "adapter_id": adapter_id,
                "state": "admitted",
                "approved_by": approved_by,
            },
        )

    def resolve_executor(self, binding_id: str) -> tuple[dict[str, Any], str]:
        record = self._resolve("executors", binding_id)
        if record.get("state") != "admitted" or record.get("adapter_id") not in {
            "identity",
            "increment",
            "double",
            "fail",
            "sleep",
        }:
            raise PermissionError(f"workflow executor is not admitted: {binding_id}")
        return record, hashlib.sha256(canonical_bytes(record)).hexdigest()

    def issue_approval(
        self,
        *,
        subject_id: str,
        revision_sha256: str,
        node_id: str,
        effects: tuple[str, ...],
        approved_by: str,
        expires_utc: str,
    ) -> dict[str, Any]:
        expiry = datetime.fromisoformat(expires_utc.replace("Z", "+00:00"))
        if expiry <= _now() or not approved_by.strip():
            raise ValueError(
                "approval must have a future expiry and identified approver"
            )
        approval_id = f"approval:{uuid4().hex}"
        return self._publish(
            "approvals",
            approval_id,
            {
                "approval_id": approval_id,
                "subject_id": subject_id,
                "revision_sha256": revision_sha256,
                "node_id": node_id,
                "effects": list(effects),
                "approved_by": approved_by,
                "expires_utc": expires_utc,
                "state": "approved",
                "replay_policy": "single-use",
            },
        )

    def consume_approval(
        self,
        approval_id: str,
        *,
        subject_id: str,
        revision_sha256: str,
        node_id: str,
        effects: tuple[str, ...],
        run_id: str,
    ) -> tuple[dict[str, Any], str]:
        record = self._resolve("approvals", approval_id)
        expected = (subject_id, revision_sha256, node_id)
        actual = (
            record.get("subject_id"),
            record.get("revision_sha256"),
            record.get("node_id"),
        )
        if (
            record.get("state") != "approved"
            or actual != expected
            or set(record.get("effects", [])) != set(effects)
        ):
            raise PermissionError(
                "workflow approval scope does not match this run node"
            )
        if (
            datetime.fromisoformat(str(record["expires_utc"]).replace("Z", "+00:00"))
            <= _now()
        ):
            raise PermissionError("workflow approval expired")
        marker = (
            self.root
            / "approval-consumption"
            / f"{hashlib.sha256(approval_id.encode()).hexdigest()}.json"
        )
        verify_safe_ancestors(self.project_root, marker)
        marker.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as error:
            raise PermissionError("workflow approval replay denied") from error
        consumption = self.sign(
            {
                "schema_version": "px.workflow-approval-consumption/1.0",
                "approval_id": approval_id,
                "run_id": run_id,
                "consumed_utc": _timestamp(),
            }
        )
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(consumption, stream, sort_keys=True)
            stream.write("\n")
        return record, hashlib.sha256(canonical_bytes(record)).hexdigest()

    def admit_source(self, source: Path, *, approved_by: str, tree_sha256: str) -> str:
        source = source.resolve(strict=True)
        if (
            not source.is_dir()
            or source == Path(source.anchor)
            or not approved_by.strip()
        ):
            raise ValueError(
                "Studio source admission requires a bounded directory and approver"
            )
        token = f"source:{uuid4().hex}"
        self._publish(
            "sources",
            token,
            {
                "token": token,
                "source": str(source),
                "source_identity": f"{source.stat().st_dev}:{source.stat().st_ino}",
                "tree_sha256": tree_sha256,
                "approved_by": approved_by,
                "state": "admitted",
            },
        )
        return token

    def resolve_source(self, token: str, source: Path) -> dict[str, Any]:
        record = self._resolve("sources", token)
        resolved = source.resolve(strict=True)
        identity = f"{resolved.stat().st_dev}:{resolved.stat().st_ino}"
        if (
            record.get("state") != "admitted"
            or record.get("source") != str(resolved)
            or record.get("source_identity") != identity
        ):
            raise PermissionError(
                "Studio source token does not match the selected directory"
            )
        return record
