#!/usr/bin/env python3
from __future__ import annotations
import argparse,json
from pathlib import Path
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('out'); ap.add_argument('--title',required=True); ap.add_argument('--expected',required=True); ap.add_argument('--actual',required=True); a=ap.parse_args(); root=Path(a.out); root.mkdir(parents=True,exist_ok=True)
 (root/'README.md').write_text(f'# {a.title}\n\n## Expected\n{a.expected}\n\n## Actual\n{a.actual}\n\n## Reproduction\n1. Pin versions.\n2. Run `python reproduce.py`.\n3. Capture evidence in evidence.json.\n')
 (root/'reproduce.py').write_text("#!/usr/bin/env python3\nimport json\nprint(json.dumps({\"reproduced\": False, \"reason\": \"Implement minimal trigger here\"}, indent=2))\n")
 (root/'acceptance.json').write_text(json.dumps({'title':a.title,'expected':a.expected,'actual':a.actual,'required_evidence':['versions','input','command','output','exit_code']},indent=2)+'\n'); print(json.dumps({'created':str(root)},indent=2))
if __name__=='__main__': main()
