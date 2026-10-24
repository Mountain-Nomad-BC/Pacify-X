"""Console human-approval recovery verifier — the explicit host adapter.

The Gremlin commissioning command never fabricates a recovery verifier; the
operator supplies one. This adapter is that explicit choice for a supervised
workstation: every recovery challenge is displayed to the human at the console,
and the verifier returns True only when

* the presented approval binds the exact challenge digest,
* the approval is granted and carries a strong authenticator factor, and
* the human operator re-types the approval id at the prompt (an explicit,
  logged act of confirmation — never an automatic pass).

It performs no credential trust of its own: ``auth_factor`` is limited to
factors the recovery authority already bounds, and the durable replay/revocation
ledger remains the canonical replay owner.
"""

from __future__ import annotations

import hashlib
import hmac
import sys
from typing import Any

SCHEMA_VERSION = "px.recovery-verifier-console/1.0"

_STRONG_FACTORS = frozenset({"passkey", "mfa", "hardware_key", "offline_recovery_token"})


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class ConsoleHumanApprovalVerifier:
    """Interactive, explicit human confirmation for recovery challenges."""

    def __init__(self, *, input_stream=None, output_stream=None) -> None:
        self._input = input_stream or sys.stdin
        self._output = output_stream or sys.stdout

    def verify(self, challenge: Any, approval: Any) -> bool:
        # The approval must bind the exact challenge presented (digest check is
        # local and cannot be skipped by the caller).
        challenge_body = "|".join(
            str(getattr(challenge, name, "")) for name in (
                "challenge_id", "requesting_authority_id", "protected_execution_id",
                "operation", "reason_code", "nonce",
            )
        )
        if not hmac.compare_digest(_sha256_hex(challenge_body), str(approval.challenge_sha256)):
            return False
        if approval.granted is not True or str(approval.auth_factor) not in _STRONG_FACTORS:
            return False
        self._output.write(
            "\n[PX recovery verification] A protected-execution recovery request requires "
            "explicit human confirmation.\n"
            f"  challenge : {challenge.challenge_id}\n"
            f"  operation : {challenge.operation} ({challenge.reason_code})\n"
            f"  execution : {challenge.protected_execution_id}\n"
            f"  principal : {approval.principal_id} ({approval.auth_factor})\n"
            f"  approval  : {approval.approval_id}\n"
            "Type the approval id exactly to confirm; anything else refuses: "
        )
        self._output.flush()
        try:
            typed = self._input.readline().strip()
        except (OSError, ValueError):
            return False
        return bool(typed) and hmac.compare_digest(typed, str(approval.approval_id))
