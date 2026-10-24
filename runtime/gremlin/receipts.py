"""Containment receipts / acknowledgments.

A containment receipt is the *external* proof that a protected execution's
containment was established and acknowledged before workload release. It is signed
by the containment authority, not the workload: workload code cannot manufacture
an acknowledgment or mark itself healthy.

The receipt carries the exact identity tuple it attests and the GN policy revision,
so a stale receipt cannot be replayed into a newer generation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import hmac
import re
from typing import Callable, Mapping

from ..json_io import bounded_canonical_json_bytes
from .runtime_identity import (
    GremlinRuntimeIdentityStore,
    RuntimeIdentityError,
    RuntimeIdentityMetadata,
)

SCHEMA_VERSION = "px.gremlin-containment-receipt/1.0"


class ReceiptForgeryError(ValueError):
    """Raised when a receipt signature does not verify against the authority key."""


@dataclass(frozen=True, slots=True)
class ContainmentReceipt:
    receipt_id: str
    agent_execution_id: str
    agent_id: str
    pid: int
    process_start_identity: str
    sandbox_id: str | None
    policy_profile: str
    gremlin_revision: str
    identity_sha256: str
    issued_at_utc: str
    issued_by: str
    signature: str = ""
    sandbox_policy_sha256: str | None = None
    job_object_id: str | None = None
    job_custody_sha256: str | None = None

    def __post_init__(self) -> None:
        if self.job_object_id is not None and (
            type(self.job_object_id) is not str
            or not self.job_object_id.strip()
            or len(self.job_object_id) > 512
        ):
            raise ValueError("Job Object identity must be bounded nonempty text or null")
        if self.job_custody_sha256 is not None and re.fullmatch(
            r"[0-9a-f]{64}", self.job_custody_sha256
        ) is None:
            raise ValueError("Job custody digest must be a lowercase SHA-256 or null")
        if self.sandbox_policy_sha256 is not None and re.fullmatch(
            r"[0-9a-f]{64}", self.sandbox_policy_sha256
        ) is None:
            raise ValueError("sandbox policy digest must be a lowercase SHA-256 or null")

    def _body(self) -> dict[str, object]:
        payload = asdict(self)
        payload.pop("signature", None)
        if payload["job_object_id"] is None:
            payload.pop("job_object_id")
        if payload["job_custody_sha256"] is None:
            payload.pop("job_custody_sha256")
        return {"schema_version": SCHEMA_VERSION, **payload}

    @property
    def receipt_sha256(self) -> str:
        return hashlib.sha256(bounded_canonical_json_bytes(self._body(), max_bytes=16384)).hexdigest()

    def as_dict(self) -> dict[str, object]:
        return {**self._body(), "receipt_sha256": self.receipt_sha256, "signature": self.signature}


class ContainmentAuthority:
    """The signing authority for containment receipts.

    The signing key is held by the containment authority (external to the
    workload). Only :meth:`issue` and :meth:`verify` use it; no workload-facing
    API accepts a caller-supplied signature as proof.
    """

    def __init__(
        self,
        *,
        authority_id: str,
        signing_key: bytes | None = None,
        signing_key_provider: Callable[[], bytes] | None = None,
    ) -> None:
        if not authority_id.strip():
            raise ValueError("containment authority requires an identity")
        if (signing_key is None) == (signing_key_provider is None):
            raise ValueError(
                "containment authority requires exactly one signing-key source"
            )
        if signing_key_provider is not None and not callable(signing_key_provider):
            raise ValueError("signing-key provider must be callable")
        initial_key = signing_key_provider() if signing_key_provider else signing_key
        if not isinstance(initial_key, (bytes, bytearray)) or len(initial_key) < 16:
            raise ValueError("containment authority requires a strong signing key")
        self.authority_id = authority_id
        self._key = bytes(initial_key) if signing_key_provider is None else None
        self._signing_key_provider = signing_key_provider

    @classmethod
    def from_runtime_identity(
        cls,
        *,
        authority_id: str,
        identity_store: GremlinRuntimeIdentityStore,
        identity: RuntimeIdentityMetadata,
    ) -> "ContainmentAuthority":
        """Bind signing to a protected local identity, reloading it on each use."""
        if identity.authority_id != authority_id:
            raise ValueError("runtime identity belongs to a different authority")
        provider = identity_store.signing_key_provider(identity)
        return cls(
            authority_id=authority_id,
            signing_key_provider=provider,
        )

    def _current_key(self) -> bytes:
        key = self._signing_key_provider() if self._signing_key_provider else self._key
        if not isinstance(key, (bytes, bytearray)) or len(key) < 16:
            raise ReceiptForgeryError("containment signing authority is unavailable")
        return bytes(key)

    def signing_key(self) -> bytes:
        """Expose the trusted signing key to key-hosted sub-controls only.

        Used by the containment facade to key its own protected admin control;
        never exposed through any workload-facing surface.
        """
        return self._current_key()

    def _sign(self, receipt_sha256: str) -> str:
        key = self._current_key()
        return hmac.new(key, receipt_sha256.encode("ascii"), hashlib.sha256).hexdigest()

    def issue(self, receipt: ContainmentReceipt) -> ContainmentReceipt:
        if receipt.issued_by != self.authority_id:
            raise ReceiptForgeryError("receipt is not issued by this containment authority")
        signature = self._sign(receipt.receipt_sha256)
        return ContainmentReceipt(**{**asdict(receipt), "signature": signature})

    def verify(self, receipt: ContainmentReceipt) -> bool:
        if not receipt.signature:
            return False
        try:
            expected = self._sign(receipt.receipt_sha256)
        except RuntimeIdentityError:
            return False
        return hmac.compare_digest(expected, receipt.signature)

    def require(self, receipt: ContainmentReceipt) -> ContainmentReceipt:
        if not self.verify(receipt):
            raise ReceiptForgeryError("containment receipt signature is invalid")
        return receipt