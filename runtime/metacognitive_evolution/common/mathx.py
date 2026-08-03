from __future__ import annotations
import math
from collections.abc import Iterable

def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(x)))

def entropy(probs: Iterable[float]) -> float:
    values = [max(0.0, float(p)) for p in probs]
    total = sum(values)
    if total <= 0:
        return 0.0
    values = [p / total for p in values]
    return -sum(p * math.log(p, 2) for p in values if p > 0)

def weighted_jaccard(a: dict[str, float], b: dict[str, float]) -> float:
    keys = set(a) | set(b)
    denominator = sum(max(a.get(k, 0.0), b.get(k, 0.0)) for k in keys)
    if denominator == 0:
        return 0.0
    return sum(min(a.get(k, 0.0), b.get(k, 0.0)) for k in keys) / denominator

def cosine(a: Iterable[float], b: Iterable[float]) -> float:
    av, bv = list(map(float, a)), list(map(float, b))
    if len(av) != len(bv):
        raise ValueError("vectors must have equal length")
    da = sum(x*x for x in av) ** 0.5
    db = sum(x*x for x in bv) ** 0.5
    return 0.0 if da == 0 or db == 0 else sum(x*y for x,y in zip(av,bv)) / (da*db)
