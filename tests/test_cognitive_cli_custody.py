"""Cognitive metadata publication requires actual native registry custody."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from tests.test_studio_operation_mirror_custody import native


def test_direct_cli_without_admission_cannot_write(tmp_path):
    script = Path(__file__).resolve().parents[1] / 'scripts/build_cognitive_index.py'
    output = tmp_path / 'registry/cognitive_map.json'
    result = subprocess.run([sys.executable, '-B', str(script), '--root', str(tmp_path),
                             '--output', str(output)], capture_output=True, text=True, timeout=20)
    assert result.returncode != 0
    assert not output.exists()


def test_actual_native_publication_and_readback(native):
    from scripts.build_cognitive_index import main
    from runtime.cognitive_core.index_builder import build_cognitive_index
    from runtime.effect_intent import EffectIntentLedger
    from runtime.scope_lease import ScopeLeaseStore
    root, admission = native
    assert main(['--root', str(root), '--output', 'registry/cognitive_map.json',
                 '--admission-event-id', admission]) == 0
    image = (root / 'registry/cognitive_map.json').read_bytes()
    assert json.loads(image) == build_cognitive_index(root)
    assert any(row['state'] == 'committed' and row['result_sha256'] == hashlib.sha256(image).hexdigest()
               for row in EffectIntentLedger(root)._load()['intents'])
    assert ScopeLeaseStore(root).active(effect='write') == ()
