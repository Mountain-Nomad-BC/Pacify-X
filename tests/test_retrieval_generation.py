from __future__ import annotations
import hashlib, json
from pathlib import Path
import pytest
from runtime.retrieval_generation import RetrievalGenerationIdentity, RetrievalGenerationStore, RetrievalGateEvidence

D=lambda s: hashlib.sha256(s.encode()).hexdigest()

def identity() -> RetrievalGenerationIdentity:
    return RetrievalGenerationIdentity(D('corpus'),D('lex'),D('dense'),D('manifest'),'embed',D('embedrev'),4,'l2',D('cal'),'graph-r1','rerank',D('rerankrev'),D('policy'))

def evidence(ok: bool=True) -> RetrievalGateEvidence:
    return RetrievalGateEvidence(ok,ok,ok,ok,ok,ok,0.98,0.95,1.0,1.0,100,175,graph_ready=ok)

def make_artifact(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    p=root/'dense.idx'; p.write_bytes(b'index'); return {'dense':{'path':'dense.idx','sha256':hashlib.sha256(b'index').hexdigest(),'size_bytes':5}}

def test_stage_is_idempotent_and_identity_mutation_is_rejected(tmp_path: Path):
    store=RetrievalGenerationStore(tmp_path/'state'); artifacts=make_artifact(tmp_path/'artifacts')
    first=store.stage_candidate(identity(),artifacts); second=store.stage_candidate(identity(),artifacts)
    assert first==second and first['generation_id']==identity().generation_id
    bad={**artifacts,'dense':{**artifacts['dense'],'size_bytes':6}}
    with pytest.raises(ValueError,match='mutation'):
        store.stage_candidate(identity(),bad)

def test_validation_is_immutable_and_activation_requires_authority(tmp_path: Path):
    store=RetrievalGenerationStore(tmp_path/'state'); store.stage_candidate(identity(),make_artifact(tmp_path/'artifacts'))
    receipt=store.record_validation(identity().generation_id,evidence())
    with pytest.raises(PermissionError): store.activate(identity().generation_id,receipt['validation_sha256'],supplied_authority=False)
    active=store.activate(identity().generation_id,receipt['validation_sha256'],supplied_authority=True)
    assert active['generation_id']==identity().generation_id
    head=json.loads((tmp_path/'state/generations'/identity().generation_id/'validations/head.json').read_text())
    assert head['validation_sha256']==receipt['validation_sha256']

def test_failed_validation_cannot_activate(tmp_path: Path):
    store=RetrievalGenerationStore(tmp_path/'state'); store.stage_candidate(identity(),make_artifact(tmp_path/'artifacts'))
    receipt=store.record_validation(identity().generation_id,evidence(False))
    assert receipt['admission']['allowed'] is False
    with pytest.raises(ValueError,match='not passed'):
        store.activate(identity().generation_id,receipt['validation_sha256'],supplied_authority=True)

def test_artifact_reconciliation_stream_hashes_and_rejects_symlink(tmp_path: Path):
    art=tmp_path/'artifacts'; art.mkdir(); artifacts=make_artifact(art)
    store=RetrievalGenerationStore(tmp_path/'state'); store.stage_candidate(identity(),artifacts)
    assert store.validate_artifacts(identity().generation_id,art)['valid'] is True
    (art/'dense.idx').write_bytes(b'changed')
    assert store.validate_artifacts(identity().generation_id,art)['valid'] is False
    (art/'dense.idx').unlink(); target=tmp_path/'outside'; target.write_bytes(b'index')
    try:
        (art/'dense.idx').symlink_to(target)
    except OSError:
        pytest.skip('symlink unavailable')
    assert store.validate_artifacts(identity().generation_id,art)['valid'] is False

def test_rollback_restores_previous_generation(tmp_path: Path):
    art=tmp_path/'artifacts'; art.mkdir(); store=RetrievalGenerationStore(tmp_path/'state')
    id1=identity(); store.stage_candidate(id1,make_artifact(art)); r1=store.record_validation(id1.generation_id,evidence()); store.activate(id1.generation_id,r1['validation_sha256'],supplied_authority=True)
    id2=RetrievalGenerationIdentity(**{**id1.__dict__,'graph_revision':'graph-r2'}) if hasattr(id1,'__dict__') else RetrievalGenerationIdentity(id1.corpus_sha256,id1.lexical_index_sha256,D('dense2'),id1.dense_manifest_sha256,id1.embedding_model_id,id1.embedding_revision,id1.embedding_dimensions,id1.embedding_normalization,id1.calibration_sha256,'graph-r2',id1.reranker_model_id,id1.reranker_revision,id1.query_policy_sha256)
    store.stage_candidate(id2,make_artifact(art)); r2=store.record_validation(id2.generation_id,evidence()); store.activate(id2.generation_id,r2['validation_sha256'],supplied_authority=True)
    assert store.rollback(supplied_authority=True)['generation_id']==id1.generation_id

def test_record_validation_is_content_deterministic_and_head_tracks_latest(tmp_path: Path):
    store=RetrievalGenerationStore(tmp_path/'state'); store.stage_candidate(identity(),make_artifact(tmp_path/'artifacts'))
    r1=store.record_validation(identity().generation_id,evidence())
    r2=store.record_validation(identity().generation_id,evidence())
    assert r1==r2
    head=json.loads((tmp_path/'state/generations'/identity().generation_id/'validations/head.json').read_text())
    assert head['validation_sha256']==r1['validation_sha256']


def test_active_reconciliation_proves_bound_artifacts(tmp_path: Path):
    art=tmp_path/'artifacts'; store=RetrievalGenerationStore(tmp_path/'state'); store.stage_candidate(identity(),make_artifact(art))
    r=store.record_validation(identity().generation_id,evidence()); store.activate(identity().generation_id,r['validation_sha256'],supplied_authority=True)
    assert store.reconcile_active(art)['valid'] is True
    (art/'dense.idx').write_bytes(b'wrong')
    assert store.reconcile_active(art)['valid'] is False
