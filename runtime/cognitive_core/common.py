from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable, Mapping
from typing import Any

TOKEN = re.compile(r"[a-z0-9]+")
STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "how",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "use",
        "what",
        "when",
        "where",
        "which",
        "with",
    }
)


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def stable_hash(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def normalize_text(value: str) -> str:
    return " ".join(TOKEN.findall(value.casefold()))


def tokens(value: str) -> tuple[str, ...]:
    return tuple(
        token for token in TOKEN.findall(value.casefold()) if token not in STOPWORDS
    )


def token_set(value: str) -> set[str]:
    return set(tokens(value))


def char_ngrams(value: str, n: int = 3) -> set[str]:
    normalized = f"  {normalize_text(value)}  "
    if len(normalized) <= n:
        return {normalized}
    return {normalized[index : index + n] for index in range(len(normalized) - n + 1)}


def jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return 0.0 if not union else len(left & right) / len(union)


def entropy(probabilities: Iterable[float]) -> float:
    values = [max(0.0, float(value)) for value in probabilities]
    total = sum(values)
    if total <= 0:
        return 0.0
    return -sum(
        (value / total) * math.log2(value / total) for value in values if value > 0
    )


def ensure_probability(value: float, name: str) -> float:
    number = float(value)
    if not 0.0 <= number <= 1.0:
        raise ValueError(f"{name} must be in [0, 1]")
    return number


def require_mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value
