from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable
from contracts.types import MultiLegExecutionPlan

TRACK2_STRATEGY_ID="track2_asymmetric_trap"
TRACK2_ENTRY_SEQUENCE=(("inner_put","BUY","PUT"),("inner_call","BUY","CALL"),("outer_put","SELL","PUT"),("outer_call","SELL","CALL"))

class Track2EntrySequenceError(ValueError): pass

@dataclass(frozen=True)
class Track2EntryProgress:
    status: str
    next_leg_id: str | None
    reason: str

def validate_track2_entry_plan(plan: MultiLegExecutionPlan) -> None:
    if plan.strategy_id != TRACK2_STRATEGY_ID: raise Track2EntrySequenceError("TRACK2_STRATEGY_REQUIRED")
    if len(plan.legs)!=4: raise Track2EntrySequenceError("TRACK2_FOUR_LEG_PLAN_REQUIRED")
    for leg, expected in zip(plan.legs,TRACK2_ENTRY_SEQUENCE):
        if (str(leg.leg_id),str(leg.side).upper(),str(leg.option_type).upper()) != expected:
            raise Track2EntrySequenceError("TRACK2_ENTRY_SEQUENCE_MISMATCH")
        if int(leg.quantity)<=0: raise Track2EntrySequenceError("TRACK2_LEG_QUANTITY_INVALID")

def evaluate_track2_entry_progress(plan: MultiLegExecutionPlan,reports: Iterable[object])->Track2EntryProgress:
    """No later leg until each predecessor is fully filled and reconciled.
    Partial/unknown/rejected states BLOCK; no repair/flatten choice (S2-U16).
    """
    validate_track2_entry_plan(plan)
    grouped={}
    for r in reports:
        if str(getattr(r,"group_id","") or "")==plan.group_id:
            lid=str(getattr(r,"leg_id","") or "")
            if lid: grouped.setdefault(lid,[]).append(r)
    unresolved={"NEW","WORKING","PENDING","PARTIALLY_FILLED","CANCEL_REQUESTED","CANCEL_PENDING","UNKNOWN","RECONCILIATION_REQUIRED"}
    expected_ids = {leg.leg_id for leg in plan.legs}
    if set(grouped) - expected_ids:
        return Track2EntryProgress("BLOCKED", None, "UNEXPECTED_LEG_EVIDENCE")
    for index, leg in enumerate(plan.legs):
        items=grouped.get(leg.leg_id,[])
        if not items:
            if any(grouped.get(later.leg_id) for later in plan.legs[index + 1:]):
                return Track2EntryProgress("BLOCKED", None, "OUT_OF_SEQUENCE_LEG_EVIDENCE")
            return Track2EntryProgress("READY",leg.leg_id,"PREVIOUS_LEGS_RECONCILED")
        filled=sum(int(getattr(x,"filled_quantity",0) or 0) for x in items)
        statuses={str(getattr(getattr(x,"status",""),"value",getattr(x,"status",""))).upper() for x in items}
        if statuses & unresolved: return Track2EntryProgress("BLOCKED",None,"LEG_NOT_TERMINAL_OR_PARTIAL")
        if filled==int(leg.quantity) and statuses=={"FILLED"}: continue
        return Track2EntryProgress("BLOCKED",None,"LEG_NOT_FULLY_FILLED_OR_POLICY_UNRESOLVED")
    return Track2EntryProgress("COMPLETE",None,"ALL_FOUR_LEGS_FILLED_AND_RECONCILED")
