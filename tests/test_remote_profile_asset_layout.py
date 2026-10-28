from pathlib import Path
import pytest
from tests.test_remote_model_bridge import configured
from runtime.remote_provider_profiles import load_profiles
from runtime import paths


@pytest.mark.parametrize("installed", [False, True])
def test_profile_schema_uses_canonical_framework_asset_layout(configured,tmp_path,monkeypatch,installed):
    engine,project,_,profile,_ = configured
    if installed:
        package = tmp_path / "site-packages/runtime"
        package.mkdir(parents=True)
        monkeypatch.setattr(paths,"__file__",str(package / "paths.py"))
        data = tmp_path / "data"
        assets = data / "share/agentic-engineering-os-px"
        (assets / "bootstrap").mkdir(parents=True)
        (assets / "bootstrap/startup.toml").write_text("# fixture asset marker")
        schema = "contracts/operations/remote-provider-profile.schema.json"
        (assets / schema).parent.mkdir(parents=True)
        (assets / schema).write_bytes((Path.cwd() / schema).read_bytes())
        monkeypatch.setattr(paths.sysconfig,"get_path",lambda key:str(data))
        assert paths.framework_root() == assets
    _,rows = load_profiles(project)
    assert rows == [profile]
