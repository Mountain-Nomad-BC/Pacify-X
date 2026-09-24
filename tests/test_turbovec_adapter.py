from __future__ import annotations
import hashlib
from pathlib import Path
import pytest
from runtime.turbovec_adapter import TurboVecAdapter, TurboVecManifest, cosine_to_relevance

class Fake:
    def __init__(self): self.rows=0; self.last=None; self.row_count=0
    def calibrate(self,a): self.last='calibrate'
    def add_with_ids(self,a,ids): self.rows += len(ids); self.row_count=self.rows
    def search(self,q,k,allowlist=None): return ([ [1.0,0.0,-1.0] ], [[7,8,9]])
    def write(self,p): Path(p).write_bytes(b'idx')

def manifest():
    return TurboVecManifest('px.turbovec-manifest/1.0','a'*64,'embed','b'*64,2)

def test_cosine_scores_map_to_canonical_relevance():
    assert cosine_to_relevance(1.0)==1.0 and cosine_to_relevance(0.0)==0.5 and cosine_to_relevance(-1.0)==0.0
    with pytest.raises(ValueError): cosine_to_relevance(1.2)

def test_adapter_requires_unit_vectors_and_calibration(tmp_path: Path):
    f=Fake(); a=TurboVecAdapter(tmp_path/'i.bin',manifest(),backend=f)
    with pytest.raises(ValueError,match='unit length'): a.add([[1,1]],[1])
    rows=[[1.0,0.0] for _ in range(128)]; a.calibrate(rows); a.add([[1.0,0.0]],[7])
    assert a.manifest.row_count==1
    assert a.search([1.0,0.0],k=3)==((7,1.0),(8,0.5),(9,0.0))
    a.persist(); assert (tmp_path/'i.bin.manifest.json').is_file()

def test_persist_refuses_uncalibrated_or_row_count_mismatch(tmp_path: Path):
    f=Fake(); a=TurboVecAdapter(tmp_path/'i.bin',manifest(),backend=f)
    with pytest.raises(RuntimeError,match='uncalibrated'): a.persist()
    a.manifest.calibration_sha256='c'*64; a.manifest.row_count=2; f.row_count=1
    with pytest.raises(RuntimeError,match='row count'): a.persist()

def test_ids_must_be_unique_and_bounded(tmp_path: Path):
    a=TurboVecAdapter(tmp_path/'i.bin',manifest(),backend=Fake())
    a.manifest.calibration_sha256='c'*64
    with pytest.raises(ValueError,match='unique'): a.add([[1.0,0],[1.0,0]],[1,1])

def test_query_vector_must_also_obey_unit_normalization(tmp_path: Path):
    a=TurboVecAdapter(tmp_path/'i.bin',manifest(),backend=Fake())
    with pytest.raises(ValueError,match='unit length'):
        a.search([0.5,0.0],k=1)


def test_manifest_rejects_non_l2_normalization():
    m=manifest(); m.normalization='none'
    with pytest.raises(ValueError,match='l2'):
        m.validate()
