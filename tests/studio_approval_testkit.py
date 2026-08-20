from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from runtime.studio_authority import StudioAuthorityStore
from runtime.studio_models import canonical_bytes, write_json_atomic


ROOT = Path(__file__).resolve().parents[1]


_PUBLIC_JWK = {
    "kty": "RSA",
    "n": "72Rlp6_dRPTFTofMLZtSXjomuTixQWTTQv4nb67P-3UuR-h2E56lsGCR1n7itzSB7sLO9bK8p00V_UwLZA_V5NrwxguPwTNVqKwz_29mXWYV2zXS2SnggPKn-ECPOPTAoVUi6Lh7XYsRwJ2HgHF41sClfoNDeeOr7THp_mJmHPlvz3KdWSTURlYD-3dwn0_xwaague_mFbNENsT3GtTV5v6Pf-TWMg-mYR6v8-XX-ZhyOkK9avASec2TXsU3Q7VFYN3wMAGC-zM9hfUwbSRvidFhN1_lFg5zaQ9mGhku503AOSSapkEENyDF8TjYZ2JUq-bhX53QPvxUh7cCAuazAw",
    "e": "AQAB",
}
_PRIVATE_D = "B_VLy9Sfg83_S9UH3JxFPgyrgjd4QmGaWafJTSp_5NlzExY56_0M1Qg2JkNMQNA7YYyTBL1PDYtqfQ6CHRl0VYn8ZxkLS7OWgrz2yDm-gBcHXaTfFYkRhY02OEfX0F-SknUaFqfLXMNlcQR2SgwmUD1R7cVqANX-E9c3nX_36mPv9eIliitFyERnRlnYxUvL1whoEhwMILFRR1WEOvgF4YDamY4YrTZ5GnCq2BZoZrpadrEDGYrMwEx4pptvBhzw5CC4q0D3xyPQujHtWcdjLCCBS9fkmPJx9Z8imKw_NnkGNftf7bUFgjyZSzQjP0ERFRe8Y9S2zwlusuBu8McIgQ"


def _decode(value: str) -> bytes:
    raw = value.encode("ascii")
    return base64.urlsafe_b64decode(raw + b"=" * (-len(raw) % 4))


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _sign(message: bytes) -> str:
    modulus_bytes = _decode(_PUBLIC_JWK["n"])
    modulus = int.from_bytes(modulus_bytes, "big")
    private_exponent = int.from_bytes(_decode(_PRIVATE_D), "big")
    digest_info = bytes.fromhex("3031300d060960864801650304020105000420") + hashlib.sha256(message).digest()
    encoded = b"\x00\x01" + b"\xff" * (len(modulus_bytes) - len(digest_info) - 3) + b"\x00" + digest_info
    return _encode(pow(int.from_bytes(encoded, "big"), private_exponent, modulus).to_bytes(len(modulus_bytes), "big"))


def approval_proof(root: Path, kind: str, operation: str, payload: dict[str, object]) -> dict[str, object]:
    authority = StudioAuthorityStore(root.resolve(strict=True))
    payload_json = json.dumps(
        payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    )
    key_id = hashlib.sha256(canonical_bytes(_PUBLIC_JWK)).hexdigest()
    write_json_atomic(authority.approval_verifier_path, {
        "schema_version": "px.studio-host-approval-verifier/2.0",
        "project_identity": authority.project_identity,
        "host_surface": "vscode-extension-host",
        "approved_by": "human:vscode-local-user",
        "key_id": key_id,
        "public_key_jwk": _PUBLIC_JWK,
        "created_utc": "2026-08-14T00:00:00Z",
        "revision": 1,
        "rotation": {"mode": "test-fixture", "previous_key_id": None, "authorization_signature": None},
    })
    issued = datetime.now(timezone.utc)
    claim = {
        "schema_version": "px.studio-host-approval/2.1",
        "project_identity": authority.project_identity,
        "kind": kind,
        "operation": operation,
        "payload_sha256": hashlib.sha256(payload_json.encode("utf-8")).hexdigest(),
        "approved_by": "human:vscode-local-user",
        "issued_utc": issued.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "expires_utc": (issued + timedelta(seconds=120)).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "nonce": uuid4().hex,
        "key_id": key_id,
    }
    return {
        "claim": claim,
        "payload_json": payload_json,
        "signature": _sign(canonical_bytes(claim)),
    }


def authorized_payload(root: Path, kind: str, operation: str, payload: dict[str, object]) -> dict[str, object]:
    return {**payload, "approval_capability": approval_proof(root, kind, operation, payload)}


def one_shot(root: Path, kind: str, operation: str, payload: dict[str, object]) -> dict[str, object]:
    completed = subprocess.run(
        [sys.executable, "-m", "runtime.studio_api", "--root", str(root), "--kind", kind, "--operation", operation, "--payload-stdin"],
        input=json.dumps(payload), text=True, capture_output=True, cwd=ROOT, timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)
