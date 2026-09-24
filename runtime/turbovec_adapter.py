"""Bounded TurboVec adapter.

TurboVec is a candidate-provider only.  It never owns ranking, authorization or
retrieval-generation promotion; :mod:`runtime.retrieval` remains canonical.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Iterable, Sequence

try:  # optional dependency by design
    import numpy as _np
except Exception:  # pragma: no cover
    _np = None
try:  # optional dependency by design
    from turbovec import IdMapIndex as _IdMapIndex
except Exception:  # pragma: no cover
    _IdMapIndex = None


@dataclass(slots=True)
class TurboVecManifest:
    schema_version: str
    generation_id: str
    embedding_model_id: str
    embedding_revision: str
    dimensions: int
    normalization: str = "l2"
    bit_width: int = 4
    calibration_sha256: str | None = None
    row_count: int = 0

    def validate(self) -> None:
        if self.schema_version != "px.turbovec-manifest/1.0":
            raise ValueError("unsupported TurboVec manifest schema")
        for name in ("generation_id",):
            value = getattr(self, name)
            if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                raise ValueError(f"{name} must be a lowercase SHA-256")
        for name in ("embedding_model_id", "embedding_revision"):
            value = getattr(self, name)
            if type(value) is not str or not value.strip() or len(value.encode()) > 512:
                raise ValueError(f"{name} must be bounded nonempty text")
        if type(self.dimensions) is not int or not 1 <= self.dimensions <= 131072:
            raise ValueError("dimensions out of bounds")
        if self.normalization != "l2":
            raise ValueError("TurboVec integration requires l2-normalized vectors")
        if type(self.bit_width) is not int or self.bit_width not in {1,2,3,4,5,6,7,8}:
            raise ValueError("bit_width must be an integer in [1,8]")
        if type(self.row_count) is not int or self.row_count < 0:
            raise ValueError("row_count must be a nonnegative integer")


def _vectors(values: Iterable[Sequence[float]], dimensions: int, *, require_unit: bool = True) -> list[list[float]]:
    rows = [list(row) for row in values]
    if not rows:
        raise ValueError("vector batch must be nonempty")
    for row in rows:
        if len(row) != dimensions:
            raise ValueError(f"expected vectors with {dimensions} dimensions")
        if any(type(v) not in (int,float) or type(v) is bool or not math.isfinite(float(v)) for v in row):
            raise ValueError("vectors must contain finite numbers")
        if require_unit:
            norm = math.sqrt(sum(float(v) * float(v) for v in row))
            if not math.isclose(norm, 1.0, rel_tol=1e-4, abs_tol=1e-4):
                raise ValueError("vectors claiming l2 normalization must be unit length")
    return [[float(v) for v in row] for row in rows]


def cosine_to_relevance(value: float) -> float:
    if type(value) not in (int,float) or type(value) is bool or not math.isfinite(float(value)):
        raise ValueError("TurboVec score must be finite")
    score=float(value)
    if score < -1.0001 or score > 1.0001:
        raise ValueError("TurboVec inner-product score is outside cosine bounds; normalization contract is broken")
    score=max(-1.0,min(1.0,score))
    return (score + 1.0) / 2.0


class TurboVecAdapter:
    def __init__(self, index_path: Path, manifest: TurboVecManifest, *, backend: object | None = None) -> None:
        manifest.validate()
        self.path = Path(index_path)
        self.manifest = manifest
        self.manifest_path = self.path.with_suffix(self.path.suffix + ".manifest.json")
        if backend is None:
            if _np is None or _IdMapIndex is None:
                raise RuntimeError("TurboVec adapter requires numpy and turbovec, or an injected backend")
            backend = _IdMapIndex.load(str(self.path)) if self.path.exists() else _IdMapIndex(dim=manifest.dimensions, bit_width=manifest.bit_width)
        self.backend = backend

    def calibrate(self, representative_vectors: Iterable[Sequence[float]], *, minimum_rows: int = 128) -> str:
        if type(minimum_rows) is not int or not 1 <= minimum_rows <= 1_000_000:
            raise ValueError("minimum_rows is invalid")
        rows = _vectors(representative_vectors, self.manifest.dimensions)
        if len(rows) < minimum_rows:
            raise ValueError("calibration sample is too small")
        array = _np.asarray(rows, dtype=_np.float32) if _np is not None else rows
        calibration_bytes = array.tobytes(order="C") if _np is not None else json.dumps(rows, separators=(",", ":")).encode()
        digest = hashlib.sha256(calibration_bytes).hexdigest()
        self.backend.calibrate(array)
        self.manifest.calibration_sha256 = digest
        return digest

    def add(self, vectors: Iterable[Sequence[float]], ids: Sequence[int]) -> None:
        rows = _vectors(vectors, self.manifest.dimensions)
        if type(ids) not in (list,tuple) or len(ids) != len(rows) or len(set(ids)) != len(ids):
            raise ValueError("TurboVec IDs must be a unique list matching the vector count")
        if any(type(value) is not int or value < 0 or value >= 2**64 for value in ids):
            raise ValueError("TurboVec IDs must be unsigned 64-bit integers")
        array = _np.asarray(rows, dtype=_np.float32) if _np is not None else rows
        id_values = _np.asarray(ids, dtype=_np.uint64) if _np is not None else list(ids)
        self.backend.add_with_ids(array, id_values)
        self.manifest.row_count += len(ids)

    def search(self, query: Sequence[float], *, k: int, allowlist: Sequence[int] | None = None) -> tuple[tuple[int,float], ...]:
        if type(k) is not int or not 1 <= k <= 1000:
            raise ValueError("k must be in [1,1000]")
        row = _vectors([query], self.manifest.dimensions)[0]
        q = _np.asarray([row], dtype=_np.float32) if _np is not None else [row]
        if allowlist is not None:
            if type(allowlist) not in (list,tuple) or len(allowlist) > 100_000 or any(type(v) is not int or v < 0 for v in allowlist):
                raise ValueError("allowlist is invalid or over budget")
            allowed = _np.asarray(allowlist, dtype=_np.uint64) if _np is not None else list(allowlist)
            raw = self.backend.search(q, k=k, allowlist=allowed)
        else:
            raw = self.backend.search(q, k=k)
        # Accept common (scores, ids) or iterable[(id,score)] test/backend shapes.
        if isinstance(raw, tuple) and len(raw) == 2:
            scores, ids = raw
            scores = list(scores[0] if hasattr(scores, "__len__") and len(scores) and hasattr(scores[0], "__len__") else scores)
            ids = list(ids[0] if hasattr(ids, "__len__") and len(ids) and hasattr(ids[0], "__len__") else ids)
            pairs = zip(ids, scores)
        else:
            pairs = raw
        out=[]
        for identifier, score in pairs:
            identifier=int(identifier)
            if identifier < 0:
                continue
            out.append((identifier, cosine_to_relevance(float(score))))
            if len(out) >= k:
                break
        return tuple(out)

    def persist(self) -> dict[str, object]:
        if self.manifest.calibration_sha256 is None:
            raise RuntimeError("refusing to persist an uncalibrated TurboVec index")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists() and hasattr(self.backend, "sync"):
            self.backend.sync(str(self.path))
        elif hasattr(self.backend, "write"):
            self.backend.write(str(self.path))
        else:
            raise RuntimeError("TurboVec backend cannot persist")
        observed = getattr(self.backend, "row_count", getattr(self.backend, "ntotal", None))
        if observed is None:
            try:
                observed = len(self.backend)
            except (TypeError, AttributeError):
                observed = None
        if observed is not None and int(observed) != self.manifest.row_count:
            raise RuntimeError("TurboVec persisted row count disagrees with the manifest")
        payload=asdict(self.manifest)
        self.manifest_path.write_text(json.dumps(payload, sort_keys=True, indent=2)+"\n", encoding="utf-8")
        return payload
