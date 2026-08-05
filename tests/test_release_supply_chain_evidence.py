from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile

from runtime.release_certification import _write_supply_chain_evidence


def test_release_supply_chain_outputs_bind_exact_artifacts_and_source() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        artifacts = [
            {
                "filename": "pacify-x.whl",
                "sha256": "a" * 64,
                "size_bytes": 10,
                "type": "wheel",
            },
            {
                "filename": "pacify-x.tar.gz",
                "sha256": "b" * 64,
                "size_bytes": 20,
                "type": "sdist",
            },
        ]
        outputs = _write_supply_chain_evidence(
            root,
            release="1.2.3",
            source_control={
                "repository": "https://example.invalid/repo",
                "commit": "c" * 40,
                "tree": "d" * 40,
                "tag": "v1.2.3",
            },
            product_digest="e" * 64,
            artifacts=artifacts,
            toolchain={"python": "3.14.0"},
        )
        assert set(outputs) == {"checksums", "sbom", "provenance"}
        checksums = (root / outputs["checksums"]).read_text(encoding="utf-8")
        assert f"{'a' * 64}  pacify-x.whl" in checksums
        sbom = json.loads((root / outputs["sbom"]).read_text(encoding="utf-8"))
        assert sbom["metadata"]["component"]["version"] == "1.2.3"
        provenance_path = root / outputs["provenance"]
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        assert provenance["subject"][0]["digest"]["sha256"] == "b" * 64
        assert hashlib.sha256(provenance_path.read_bytes()).hexdigest()
