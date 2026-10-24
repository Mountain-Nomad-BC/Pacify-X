"""Workflow boundaries retain one explicit terminal disposition for every item."""
from dataclasses import dataclass, asdict

from .generation_bound_verdict import digest, validate_record

STATES = {"completed", "blocked", "handed_off", "superseded", "escalated", "cancelled"}


@dataclass(frozen=True)
class WorkDisposition:
    work_id: str
    state: str
    reason: str
    target_id: str | None = None

    def __post_init__(self):
        for value in (self.work_id, self.reason):
            if type(value) is not str or not value.strip() or len(value) > 512:
                raise ValueError("work identity and reason required")
        if self.state not in STATES:
            raise ValueError("nonterminal work disposition")
        if self.state in {"blocked", "handed_off", "superseded", "escalated"} and not self.target_id:
            raise ValueError("terminal relationship requires exact target")
        if self.target_id is not None and (type(self.target_id) is not str or not self.target_id or len(self.target_id) > 512):
            raise ValueError("invalid work target")


def settle_boundary(expected_work_ids, dispositions):
    expected = tuple(expected_work_ids)
    rows = tuple(dispositions)
    if not 1 <= len(expected) <= 1000 or len(set(expected)) != len(expected):
        raise ValueError("bounded unique work set required")
    if len(rows) != len(expected) or any(type(row) is not WorkDisposition for row in rows):
        raise ValueError("every work item requires a typed terminal disposition")
    if len({row.work_id for row in rows}) != len(rows) or {row.work_id for row in rows} != set(expected):
        raise ValueError("work membership does not match boundary")
    body = dict(schema_version="px.work-disposition/1.0", dispositions=[asdict(row) for row in sorted(rows, key=lambda row: row.work_id)])
    return validate_record({**body, "boundary_sha256": digest(body)}, "work-disposition")


def workflow_boundary(definition, receipt):
    """Describe every graph node at success, pause, failure or cancellation."""
    expected = tuple(node.node_id for node in definition.nodes)
    receipts = tuple(receipt.get("node_receipts", ()))
    rows = {row["node_id"]: row for row in receipts}
    if len(rows) != len(receipts):
        raise ValueError("workflow receipt contains duplicate work")
    if set(rows) - set(expected):
        raise ValueError("workflow receipt contains undeclared work")
    state = receipt.get("terminal_target") or receipt.get("run_state")
    failed = sorted(key for key, value in rows.items() if value.get("state") == "failed")
    dispositions = []
    for work_id in expected:
        row = rows.get(work_id, {})
        if row.get("state") == "succeeded":
            dispositions.append(WorkDisposition(work_id, "completed", "node execution succeeded"))
        elif state == "cancelled":
            dispositions.append(WorkDisposition(work_id, "cancelled", "workflow cancelled before successful completion"))
        else:
            target = ("workflow-node:" + failed[0]) if failed else ("workflow-run:" + str(receipt["run_id"]))
            reason = "node retry budget exhausted" if row.get("state") == "failed" else "workflow " + str(state) + "; work remains explicit"
            dispositions.append(WorkDisposition(work_id, "blocked", reason, target))
    return settle_boundary(expected, dispositions)
