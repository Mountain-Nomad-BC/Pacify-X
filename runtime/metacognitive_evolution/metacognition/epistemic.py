from __future__ import annotations
from ..common.mathx import clamp, entropy


def bayes_update(
    prior: float, likelihood_if_true: float, likelihood_if_false: float
) -> float:
    prior = clamp(prior)
    lt = clamp(likelihood_if_true)
    lf = clamp(likelihood_if_false)
    denominator = lt * prior + lf * (1 - prior)
    return prior if denominator == 0 else clamp((lt * prior) / denominator)


def brier(predictions, outcomes) -> float:
    ps, ys = list(map(float, predictions)), list(map(float, outcomes))
    if len(ps) != len(ys) or not ps:
        raise ValueError("equal non-empty arrays required")
    return sum((p - y) ** 2 for p, y in zip(ps, ys)) / len(ps)


def expected_calibration_error(predictions, outcomes, bins: int = 10) -> float:
    ps, ys = list(map(float, predictions)), list(map(float, outcomes))
    if len(ps) != len(ys) or not ps:
        raise ValueError("equal non-empty arrays required")
    total, result = len(ps), 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        idx = [
            i for i, p in enumerate(ps) if lo <= p < hi or (b == bins - 1 and p == 1.0)
        ]
        if idx:
            confidence = sum(ps[i] for i in idx) / len(idx)
            accuracy = sum(ys[i] for i in idx) / len(idx)
            result += len(idx) / total * abs(accuracy - confidence)
    return result


def build_state(case: dict) -> dict:
    hypotheses = [dict(h) for h in case.get("hypotheses", [])]
    for hypothesis in hypotheses:
        posterior = float(hypothesis.get("prior", 0.5))
        for evidence in hypothesis.get("evidence", []):
            posterior = bayes_update(
                posterior,
                float(evidence["likelihood_if_true"]),
                float(evidence["likelihood_if_false"]),
            )
        hypothesis["posterior"] = posterior
    probabilities = [h.get("posterior", h.get("prior", 0.5)) for h in hypotheses]
    return {
        "id": case.get("id", "case"),
        "hypotheses": hypotheses,
        "entropy_bits": entropy(probabilities),
        "unknowns": case.get("unknowns", []),
        "assumptions": case.get("assumptions", []),
    }
