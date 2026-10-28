@echo off
set "PATH=%LOCALAPPDATA%\Programs\Python\Python311;%LOCALAPPDATA%\Programs\Python\Python311\Scripts;%PATH%"
cd /d %~dp0..
python -c "import json; from runtime.structural_integrity import audit_structural_integrity; from pathlib import Path; r = audit_structural_integrity(Path('.')); fails = {k: v for k, v in r['audit_items'].items() if not v.get('passed')}; out = {'errors': r['errors'], 'failed_items': fails, 'category_count': r['category_count'], 'reachability_records': r['reachability_records'], 'required_audit_item_count': r['required_audit_item_count'], 'duplicate_groups': r['duplicate_file_groups'], 'logic_groups': r.get('duplicate_logic_groups', [])}; open('.engineering-bootstrap/tmp/audit_live.json','w').write(json.dumps(out, indent=2))" > .engineering-bootstrap/tmp/audit_live.log 2>&1
echo exit=%ERRORLEVEL% > .engineering-bootstrap/tmp/audit_live.exitcode
