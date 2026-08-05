from __future__ import annotations
import re


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def detect(claims: list[dict]) -> list[dict]:
    findings = []
    by_subject: dict[str, list[dict]] = {}
    for claim in claims:
        by_subject.setdefault(claim.get("subject", ""), []).append(claim)
    for subject, group in by_subject.items():
        for index, left in enumerate(group):
            for right in group[index + 1 :]:
                conflict, reason = False, ""
                if (
                    left.get("value") is not None
                    and right.get("value") is not None
                    and left.get("value") != right.get("value")
                ):
                    conflict, reason = True, "different values"
                ls, rs = (
                    normalize(left.get("statement", "")),
                    normalize(right.get("statement", "")),
                )
                if ls == "not " + rs or rs == "not " + ls:
                    conflict, reason = True, "explicit negation"
                if conflict:
                    findings.append(
                        {
                            "subject": subject,
                            "claim_a": left.get("id"),
                            "claim_b": right.get("id"),
                            "reason": reason,
                            "resolution": "unresolved",
                        }
                    )
    return findings
