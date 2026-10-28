"""Explicit disposable native Foundry authority; never a production fixture."""
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from runtime.studio_authority import StudioAuthorityStore
from runtime.operational_gap_ledger import append_event
from tests.test_operational_gap_ledger import initialize,card,evidence

def admit_publication_fixture(root):
    initialize(root);append_event(root,"card_discovered",card(),actor="disposable-fixture")
    checkpoint=append_event(root,"work_checkpoint",{"active_gap_id":"PX-GAP-0001","learned":"Disposable candidate owner test.","next_action":card()["next_action"],"unresolved_branch_gap_ids":[],"newly_discovered_gap_ids":[],"evidence":evidence("unit checkpoint")},actor="disposable-fixture")
    admission=append_event(root,"work_admitted",{"gap_id":"PX-GAP-0001","checkpoint_event_id":checkpoint["event_id"],"session_id":"pxsession.foundry-unit","expires_utc":"2099-01-01T00:00:00Z","effect_scopes":[{"effect":"write","scope":[".agentic_engineering_os_px/runtime-core",".agentic_engineering_os_px/resource-lifecycle"]}],"authority":"Explicit isolated native publication fixture, never production authority.","expected_effect":"Candidate byte evidence only.","rollback":"Preserve disposable evidence until test teardown.","evidence":evidence("unit admission")},actor="disposable-fixture")
    return admission

@contextmanager
def publication_host(root):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    with patch.dict("os.environ",{"PX_STUDIO_KEY_ROOT":str(root.parent/(root.name+"-unit-host-keys"))}):
        authority=StudioAuthorityStore(root)
        admission=admit_publication_fixture(root)
        destination=root/".agentic_engineering_os_px/runtime-core/knowledge-foundry/candidates"
        yield destination,dict(project_root=root,project_id=authority.project_identity,run_id="disposable-run",admission_event_id=admission["event_id"])
