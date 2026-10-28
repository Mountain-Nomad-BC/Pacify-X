"""Which contract directories have no explicit owner rule in the generator?

A directory with no branch falls through to the root table, which is how the
semantic contract silently got a guess instead of a source-derived owner.
"""
import re
from pathlib import Path

source = Path("scripts/build_contract_ownership_registry.py").read_text(encoding="utf-8")
handled = set(re.findall(r'path\.parent\.name == "([a-z_]+)"', source))
directories = sorted(p.name for p in Path("contracts").iterdir() if p.is_dir())
print("handled:", sorted(handled))
print("unhandled:", sorted(set(directories) - handled))
