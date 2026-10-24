"""Read-only current certification denominator; assignments never become acceptance."""
from pathlib import Path
from .plan_registry import (requirement_report, readiness_report, _planning_object,
                           LEDGER_RELATIVE, _require_valid_ledger)


def current_certification_acceptance(root: Path, *, authority=None) -> dict:
    root=Path(root).resolve(strict=True)
    try:
        trace_report=requirement_report(root)
        policy=_planning_object(root/"policies/rev1xx-validation.json")
        trace=_planning_object(root/policy["requirement_trace"]["path"])
        ledger=_planning_object(root/LEDGER_RELATIVE);_require_valid_ledger(ledger)
        readiness=readiness_report(root,authority=authority)
        if readiness.get("valid") is not True:
            raise ValueError("current criterion acceptance authority unavailable: "+str(readiness.get("errors",[])))
        accepted=set(readiness["accepted_card_ids"])
        conformant=set(readiness["campaign_conformant_cards"])
        deferrals=readiness["owner_deferred_criteria"]
        if any(card not in deferrals or not deferrals[card] for card in conformant):
            raise ValueError("campaign conformance lacks exact native criterion deferrals")
        complete=accepted|conformant
        locked={row["card_id"] for row in ledger["cards"]}
        if not complete<=locked:raise ValueError("current acceptance references unknown locked cards")
        missing=sorted(locked-complete)
        requirements=[]
        for row in trace["records"]:
            ids=row["card_ids"]
            if not ids or not set(ids)<=locked:raise ValueError("requirement has no exact locked owner mapping")
            requirements.append({"requirement_id":row["requirement_id"],"card_ids":ids,
                "accepted":set(ids)<=accepted,"campaign_conformant":set(ids)<=complete,
                "missing_card_ids":sorted(set(ids)-complete)})
        errors=["current locked criterion proof missing: "+card for card in missing]
        errors.extend("current requirement proof missing: "+row["requirement_id"] for row in requirements if not row["campaign_conformant"])
        return {"valid":not errors,"errors":errors,"base_ledger_sha256":ledger["ledger_sha256"],
            "requirement_trace":trace_report["path"],"requirement_count":len(requirements),"requirements":requirements,
            "locked_card_count":len(locked),"accepted_card_ids":sorted(accepted),"campaign_conformant_cards":sorted(conformant),
            "owner_deferred_criteria":deferrals,"git_acceptance_satisfied":False,
            "circular_finalizer_exemptions":[]}
    except (OSError,ValueError,TypeError,KeyError) as error:
        return {"valid":False,"errors":[str(error)],"git_acceptance_satisfied":False,"circular_finalizer_exemptions":[]}
