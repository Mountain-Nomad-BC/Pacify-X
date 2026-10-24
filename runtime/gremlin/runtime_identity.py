"""Protected local lifecycle for the Gremlin runtime signing identity.

The identity is generated only when setup explicitly calls ``create``. Secret
bytes are persisted through an OS-backed credential provider and are never
written to project files or included in lifecycle receipts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
import re
import secrets
from contextlib import contextmanager
from typing import Callable, ContextManager, Iterator, Mapping, Protocol
from uuid import uuid4


SCHEMA_VERSION = "px.gremlin-runtime-identity/1.0"
LIFECYCLE_SCHEMA_VERSION = "px.gremlin-runtime-identity-event/1.0"
_AUTHORITY_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_IDENTITY_ID = re.compile(r"[0-9a-f-]{36}\Z")
_KEY_SIZE_BYTES = 32
_MAX_CREDENTIAL_BLOB_BYTES = 2_560
_CRED_TYPE_GENERIC = 1
_CRED_PERSIST_LOCAL_MACHINE = 2
_ERROR_NOT_FOUND = 1168
_WAIT_OBJECT_0 = 0
_WAIT_ABANDONED = 0x80
_WAIT_TIMEOUT = 0x102
_MUTEX_WAIT_MS = 30_000


class RuntimeIdentityError(RuntimeError):
    """A local Gremlin runtime identity could not be used safely."""


class RuntimeIdentityNotFound(RuntimeIdentityError):
    """No runtime identity is enrolled for this authority."""


class RuntimeIdentityRevoked(RuntimeIdentityError):
    """The requested identity generation is no longer current."""


class ProtectedCredentialBackend(Protocol):
    """OS-protected storage contract; implementations must not persist plaintext."""

    backend_id: str

    def read(self, target: str) -> bytes | None: ...

    def write(self, target: str, value: bytes) -> None: ...

    def delete(self, target: str) -> bool: ...

    def transaction(self, target: str) -> ContextManager[None]: ...


@dataclass(frozen=True, slots=True)
class RuntimeIdentityMetadata:
    authority_id: str
    identity_id: str
    generation: int
    created_at_utc: str
    updated_at_utc: str
    backend_id: str
    signing_key_sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "authority_id": self.authority_id,
            "identity_id": self.identity_id,
            "generation": self.generation,
            "created_at_utc": self.created_at_utc,
            "updated_at_utc": self.updated_at_utc,
            "backend_id": self.backend_id,
            "signing_key_sha256": self.signing_key_sha256,
        }


@dataclass(frozen=True, slots=True)
class RuntimeIdentityEvent:
    event_type: str
    authority_id: str
    identity_id: str
    generation: int
    occurred_at_utc: str
    result: str
    backend_id: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": LIFECYCLE_SCHEMA_VERSION,
            "event_type": self.event_type,
            "authority_id": self.authority_id,
            "identity_id": self.identity_id,
            "generation": self.generation,
            "occurred_at_utc": self.occurred_at_utc,
            "result": self.result,
            "backend_id": self.backend_id,
        }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _validate_authority_id(authority_id: str) -> str:
    if type(authority_id) is not str or _AUTHORITY_ID.fullmatch(authority_id) is None:
        raise ValueError("authority_id must be a bounded identifier")
    return authority_id


def _target(authority_id: str) -> str:
    authority_id = _validate_authority_id(authority_id)
    return f"Pacify-X/Gremlin/runtime/{authority_id}"


class WindowsCredentialManagerBackend:
    """Windows Credential Manager adapter using machine-persistent credentials.

    Credential Manager protects the blob using Windows account facilities and
    persists it on this machine. It is not a substitute for a hardware-backed,
    non-exportable TPM key; deployments that require that assurance must provide
    a stronger ``ProtectedCredentialBackend``.
    """

    backend_id = "windows-credential-manager"

    class _CredentialW(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", wintypes.FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    def __init__(self) -> None:
        if os.name != "nt":
            raise RuntimeIdentityError(
                "Windows Credential Manager is available only on Windows"
            )
        advapi32 = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
        self._cred_write = advapi32.CredWriteW
        self._cred_write.argtypes = [
            ctypes.POINTER(self._CredentialW),
            wintypes.DWORD,
        ]
        self._cred_write.restype = wintypes.BOOL
        self._cred_read = advapi32.CredReadW
        self._cred_read.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.POINTER(self._CredentialW)),
        ]
        self._cred_read.restype = wintypes.BOOL
        self._cred_delete = advapi32.CredDeleteW
        self._cred_delete.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
        ]
        self._cred_delete.restype = wintypes.BOOL
        self._cred_free = advapi32.CredFree
        self._cred_free.argtypes = [ctypes.c_void_p]
        self._cred_free.restype = None
        kernel32 = ctypes.WinDLL("Kernel32.dll", use_last_error=True)
        self._create_mutex = kernel32.CreateMutexW
        self._create_mutex.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        self._create_mutex.restype = wintypes.HANDLE
        self._wait_for_single_object = kernel32.WaitForSingleObject
        self._wait_for_single_object.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self._wait_for_single_object.restype = wintypes.DWORD
        self._release_mutex = kernel32.ReleaseMutex
        self._release_mutex.argtypes = [wintypes.HANDLE]
        self._release_mutex.restype = wintypes.BOOL
        self._close_handle = kernel32.CloseHandle
        self._close_handle.argtypes = [wintypes.HANDLE]
        self._close_handle.restype = wintypes.BOOL

    @contextmanager
    def transaction(self, target: str) -> Iterator[None]:
        """Serialize per-authority read/modify/write across local processes."""
        mutex_name = "Local\\PacifyX-Gremlin-" + hashlib.sha256(
            target.encode("utf-8")
        ).hexdigest()
        handle = self._create_mutex(None, False, mutex_name)
        if not handle:
            raise RuntimeIdentityError(
                f"runtime identity mutex creation failed (error {ctypes.get_last_error()})"
            )
        acquired = False
        try:
            result = int(self._wait_for_single_object(handle, _MUTEX_WAIT_MS))
            if result not in {_WAIT_OBJECT_0, _WAIT_ABANDONED}:
                if result == _WAIT_TIMEOUT:
                    raise RuntimeIdentityError("runtime identity operation timed out")
                raise RuntimeIdentityError(
                    f"runtime identity mutex wait failed (result {result})"
                )
            acquired = True
            yield
        finally:
            if acquired and not self._release_mutex(handle):
                self._close_handle(handle)
                raise RuntimeIdentityError(
                    f"runtime identity mutex release failed (error {ctypes.get_last_error()})"
                )
            if not self._close_handle(handle):
                raise RuntimeIdentityError(
                    f"runtime identity mutex close failed (error {ctypes.get_last_error()})"
                )

    def read(self, target: str) -> bytes | None:
        credential = ctypes.POINTER(self._CredentialW)()
        if not self._cred_read(target, _CRED_TYPE_GENERIC, 0, ctypes.byref(credential)):
            error_code = ctypes.get_last_error()
            if error_code == _ERROR_NOT_FOUND:
                return None
            raise RuntimeIdentityError(
                f"Windows Credential Manager read failed (error {error_code})"
            )
        try:
            record = credential.contents
            size = int(record.CredentialBlobSize)
            if size > _MAX_CREDENTIAL_BLOB_BYTES:
                raise RuntimeIdentityError("stored runtime identity exceeds its bound")
            if size == 0:
                raise RuntimeIdentityError("stored runtime identity is empty")
            return ctypes.string_at(record.CredentialBlob, size)
        finally:
            self._cred_free(credential)

    def write(self, target: str, value: bytes) -> None:
        if type(value) is not bytes or not 1 <= len(value) <= _MAX_CREDENTIAL_BLOB_BYTES:
            raise ValueError("credential payload is outside the supported bound")
        blob = ctypes.create_string_buffer(value)
        record = self._CredentialW()
        record.Flags = 0
        record.Type = _CRED_TYPE_GENERIC
        record.TargetName = target
        record.Comment = "Pacify-X Gremlin runtime identity"
        record.CredentialBlobSize = len(value)
        record.CredentialBlob = ctypes.cast(
            blob, ctypes.POINTER(ctypes.c_ubyte)
        )
        record.Persist = _CRED_PERSIST_LOCAL_MACHINE
        record.AttributeCount = 0
        record.Attributes = None
        record.TargetAlias = None
        record.UserName = "Pacify-X Gremlin"
        if not self._cred_write(ctypes.byref(record), 0):
            error_code = ctypes.get_last_error()
            raise RuntimeIdentityError(
                f"Windows Credential Manager write failed (error {error_code})"
            )

    def delete(self, target: str) -> bool:
        if self._cred_delete(target, _CRED_TYPE_GENERIC, 0):
            return True
        error_code = ctypes.get_last_error()
        if error_code == _ERROR_NOT_FOUND:
            return False
        raise RuntimeIdentityError(
            f"Windows Credential Manager delete failed (error {error_code})"
        )


class GremlinRuntimeIdentityStore:
    """Create, rotate, resolve, and revoke one authority's protected signing key."""

    def __init__(
        self,
        backend: ProtectedCredentialBackend,
        *,
        audit_sink: Callable[[Mapping[str, object]], object],
    ) -> None:
        backend_id = getattr(backend, "backend_id", None)
        if type(backend_id) is not str or not backend_id.strip():
            raise ValueError("protected credential backend must declare backend_id")
        if not callable(audit_sink):
            raise ValueError("canonical audit sink is required")
        self._backend = backend
        self._audit_sink = audit_sink
        self.backend_id = backend_id

    def inspect(self, authority_id: str) -> RuntimeIdentityMetadata:
        target = _target(authority_id)
        with self._backend.transaction(target):
            raw = self._backend.read(target)
            if raw is None:
                raise RuntimeIdentityNotFound("no runtime identity is enrolled")
            payload, key = self._decode(raw, authority_id)
            return self._metadata(payload, key)

    def create(
        self, authority_id: str, *, now_utc: str | None = None
    ) -> RuntimeIdentityMetadata:
        authority_id = _validate_authority_id(authority_id)
        target = _target(authority_id)
        with self._backend.transaction(target):
            if self._backend.read(target) is not None:
                raise RuntimeIdentityError(
                    "runtime identity already exists; use explicit rotation"
                )
            moment = now_utc or _utc_now()
            payload = {
                "schema_version": SCHEMA_VERSION,
                "authority_id": authority_id,
                "identity_id": str(uuid4()),
                "generation": 1,
                "created_at_utc": moment,
                "updated_at_utc": moment,
                "signing_key": secrets.token_hex(_KEY_SIZE_BYTES),
            }
            key = bytes.fromhex(str(payload["signing_key"]))
            self._backend.write(target, self._encode(payload))
            metadata = self._metadata(payload, key)
            try:
                self._emit("runtime_identity_created", metadata, moment)
            except Exception:
                self._backend.delete(target)
                raise RuntimeIdentityError(
                    "identity creation audit failed; the new identity was revoked"
                ) from None
            return metadata

    def rotate(
        self,
        current: RuntimeIdentityMetadata,
        *,
        now_utc: str | None = None,
    ) -> RuntimeIdentityMetadata:
        target = _target(current.authority_id)
        with self._backend.transaction(target):
            raw = self._require_current(current)
            payload, _old_key = self._decode(raw, current.authority_id)
            moment = now_utc or _utc_now()
            rotated = {
                **payload,
                "generation": current.generation + 1,
                "updated_at_utc": moment,
                "signing_key": secrets.token_hex(_KEY_SIZE_BYTES),
            }
            key = bytes.fromhex(str(rotated["signing_key"]))
            self._backend.write(target, self._encode(rotated))
            metadata = self._metadata(rotated, key)
            try:
                self._emit("runtime_identity_rotated", metadata, moment)
            except Exception:
                self._backend.write(target, raw)
                raise RuntimeIdentityError(
                    "identity rotation audit failed; the prior identity was restored"
                ) from None
            return metadata

    def revoke(
        self,
        current: RuntimeIdentityMetadata,
        *,
        now_utc: str | None = None,
    ) -> RuntimeIdentityEvent:
        target = _target(current.authority_id)
        with self._backend.transaction(target):
            raw = self._require_current(current)
            if not self._backend.delete(target):
                raise RuntimeIdentityNotFound(
                    "runtime identity disappeared during revocation"
                )
            event = RuntimeIdentityEvent(
                "runtime_identity_revoked",
                current.authority_id,
                current.identity_id,
                current.generation,
                now_utc or _utc_now(),
                "succeeded",
                self.backend_id,
            )
            try:
                self._audit_sink(event.as_dict())
            except Exception:
                self._backend.write(target, raw)
                raise RuntimeIdentityError(
                    "identity revocation audit failed; the prior identity was restored"
                ) from None
            return event

    def signing_key_provider(
        self, identity: RuntimeIdentityMetadata
    ) -> Callable[[], bytes]:
        """Return a provider that reloads current OS-protected state on each use."""
        def load_current_key() -> bytes:
            raw = self._require_current(identity)
            _payload, key = self._decode(raw, identity.authority_id)
            return key

        return load_current_key

    def _require_current(self, metadata: RuntimeIdentityMetadata) -> bytes:
        target = _target(metadata.authority_id)
        with self._backend.transaction(target):
            raw = self._backend.read(target)
            if raw is None:
                raise RuntimeIdentityRevoked("runtime identity is missing or revoked")
            payload, key = self._decode(raw, metadata.authority_id)
            if (
                payload["identity_id"] != metadata.identity_id
                or payload["generation"] != metadata.generation
                or hashlib.sha256(key).hexdigest() != metadata.signing_key_sha256
            ):
                raise RuntimeIdentityRevoked(
                    "runtime identity generation is no longer current"
                )
            return raw

    def _emit(
        self, event_type: str, metadata: RuntimeIdentityMetadata, moment: str
    ) -> None:
        event = RuntimeIdentityEvent(
            event_type,
            metadata.authority_id,
            metadata.identity_id,
            metadata.generation,
            moment,
            "succeeded",
            self.backend_id,
        )
        self._audit_sink(event.as_dict())

    @staticmethod
    def _encode(payload: Mapping[str, object]) -> bytes:
        encoded = (
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            )
            .encode("ascii")
        )
        if not 1 <= len(encoded) <= _MAX_CREDENTIAL_BLOB_BYTES:
            raise ValueError("runtime identity payload exceeds its bound")
        return encoded

    @staticmethod
    def _decode(raw: bytes, expected_authority_id: str) -> tuple[dict[str, object], bytes]:
        try:
            value = json.loads(raw.decode("ascii"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RuntimeIdentityError("stored runtime identity is malformed") from error
        required = {
            "schema_version",
            "authority_id",
            "identity_id",
            "generation",
            "created_at_utc",
            "updated_at_utc",
            "signing_key",
        }
        if type(value) is not dict or value.keys() != required:
            raise RuntimeIdentityError("stored runtime identity fields are invalid")
        if (
            value["schema_version"] != SCHEMA_VERSION
            or value["authority_id"] != expected_authority_id
            or type(value["generation"]) is not int
            or value["generation"] < 1
            or type(value["identity_id"]) is not str
            or _IDENTITY_ID.fullmatch(value["identity_id"]) is None
        ):
            raise RuntimeIdentityError("stored runtime identity metadata is invalid")
        for field in ("created_at_utc", "updated_at_utc"):
            if type(value[field]) is not str or not value[field].strip():
                raise RuntimeIdentityError("stored runtime identity timestamp is invalid")
        encoded_key = value["signing_key"]
        if (
            type(encoded_key) is not str
            or re.fullmatch(r"[0-9a-f]{64}", encoded_key) is None
        ):
            raise RuntimeIdentityError("stored runtime identity key is invalid")
        return value, bytes.fromhex(encoded_key)

    def _metadata(
        self, payload: Mapping[str, object], signing_key: bytes
    ) -> RuntimeIdentityMetadata:
        return RuntimeIdentityMetadata(
            authority_id=str(payload["authority_id"]),
            identity_id=str(payload["identity_id"]),
            generation=int(payload["generation"]),
            created_at_utc=str(payload["created_at_utc"]),
            updated_at_utc=str(payload["updated_at_utc"]),
            backend_id=self.backend_id,
            signing_key_sha256=hashlib.sha256(signing_key).hexdigest(),
        )
