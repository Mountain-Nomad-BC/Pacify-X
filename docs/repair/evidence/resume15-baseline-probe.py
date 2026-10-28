"""Run the group suite with my custody change fully reverted, then restore.

The file is untracked, so there is no git baseline; this restores the exact
original body in a temporary copy of the working file and puts it back after.
"""
import subprocess
from pathlib import Path

PY = str(Path("Python/pythoncore-3.14-64/python.exe").resolve())
TARGET = Path("runtime/remote_provider_placement.py")
BACKUP = Path(".tmp/resume9/rpp.mine.py")

ORIGINAL = '''def require_complete_group_provider_custody(task_plan, *, project_root):
    """Preflight every local shared writer through its current signed native owner."""
    from .model_group_preparation import member_execution_input
    plan=task_plan.as_dict() if hasattr(task_plan,'as_dict') else task_plan
    members=plan.get('model_group_preparation',{}).get('members',[])
    if any(row['attachment'].get('schema_version') == REMOTE_ATTACHMENT_SCHEMA for row in members):
        local = [row for row in members if row['attachment'].get('schema_version') != REMOTE_ATTACHMENT_SCHEMA]
        if local:
            try:
                from .remote_member_execution import _current_local_identity
            except ImportError as error:
                raise PermissionError("mixed group local provider custody owner is unavailable") from error
        for row in members:
            if row['attachment'].get('schema_version') != REMOTE_ATTACHMENT_SCHEMA:
                _current_local_identity(project_root,member_execution_input(plan,row))
'''

BACKUP.write_bytes(TARGET.read_bytes())
text = BACKUP.read_text(encoding="utf-8")
start = text.index("def require_complete_group_provider_custody(")
end = text.find("\ndef ", start + 1)
end = len(text) if end == -1 else end + 1

# Also revert the caller signature in agent_runtime to the original one-arg call.
agent = Path("runtime/agent_runtime.py")
agent_backup = agent.read_bytes()
try:
    TARGET.write_text(text[:start] + ORIGINAL + text[end:], encoding="utf-8")
    agent_text = agent.read_text(encoding="utf-8")
    agent_text = agent_text.replace(
        'require_complete_group_provider_custody(\n            task_plan, project_root=self.project_root,\n            adapter_for=getattr(member_executor, "adapter_for", None))',
        'require_complete_group_provider_custody(task_plan, project_root=self.project_root)',
    )
    agent.write_text(agent_text, encoding="utf-8")
    proc = subprocess.run(
        [PY, "-m", "pytest", "tests/test_governed_prepared_member.py",
         "-q", "--no-header", "-p", "no:cacheprovider"],
        capture_output=True, text=True,
    )
    print("WITH ORIGINAL BODY exit:", proc.returncode)
    print("\n".join(proc.stdout.strip().splitlines()[-3:]))
finally:
    TARGET.write_bytes(BACKUP.read_bytes())
    agent.write_bytes(agent_backup)
    print("restored:", TARGET.read_bytes() == BACKUP.read_bytes(), agent.read_bytes() == agent_backup)
