"""Validation-only SYN-EVT scenario catalogue; no prices/runtime/strategy/orders are produced."""
from __future__ import annotations
import json
from dataclasses import asdict, dataclass
from hashlib import sha256
from typing import Iterable

GENERATOR_VERSION = "psb-validation-only-syn-evt-v1"
PROVENANCE = "DERIVED_SCENARIO"
SOURCE_STATUS = "SYNTHETIC_SCENARIO_SPEC_ONLY"
IDENTITY_SOURCE_STATUS = "BLOCKED_IDENTITY_OWNER_UNRESOLVED"
DEFAULT_STRATEGY_ORDER = (6, 7, 8, 1, 9, 5, 2)
_DEFS = (
("missing_quote",(6,7,8,1,9,5,2),"quote_missing","Missing quote fails closed; never fabricate price.","UNAVAILABLE"),
("delayed_stale_quote",(6,7,8,1,9,5,2),"quote_delayed_stale","Stale source time is not current market data.","BLOCKED"),
("duplicate_event",(6,7,8,1,9,5,2),"event_duplicate","Detect duplicate identity; preserve deterministic ordering.","BLOCKED"),
("zero_invalid_quote",(6,7,8,1,9,5,2),"quote_invalid_zero","Reject zero/invalid quote; never use fallback price.","UNAVAILABLE"),
("orderbook_gap",(6,7,8,1,9,5),"orderbook_gap","Missing depth blocks liquidity-dependent decisions/fills.","BLOCKED"),
("wide_spread",(6,7,8,1,9,5,2),"orderbook_wide_spread","Keep spread visible; do not assume fill.","BLOCKED"),
("insufficient_depth",(6,7,8,1,9,5),"orderbook_insufficient_depth","Insufficient depth/volume cannot support fill.","BLOCKED"),
("underlying_gap",(6,8,1,5,2),"underlying_price_gap","Preserve gap provenance and event chronology.","PASS_WITH_LIMITATION"),
("volatility_1_3x",(6,7,8,1,9,5,2),"volatility_regime_1_3x","Tag configured 1.3x regime; do not tune threshold.","PASS_WITH_LIMITATION"),
("whipsaw_reversal_1",(6,8,1,5,2),"whipsaw_reversal","Represent first reversal in deterministic order.","PASS_WITH_LIMITATION"),
("whipsaw_reversal_2",(6,8,1,5,2),"whipsaw_reversal","Represent second reversal after reversal 1.","PASS_WITH_LIMITATION"),
("trend_then_reversal",(8,1,5,2),"trend_reversal","Keep trend/reversal phases distinguishable.","PASS_WITH_LIMITATION"),
("crash_rebound",(6,8,1,9,5,2),"crash_rebound","Preserve crash/rebound chronology; no profitability inference.","PASS_WITH_LIMITATION"),
("d4_transition",(7,8,1,9,5,2),"d4_transition","D-4 is scenario-only; expiry authority unverified.","BLOCKED"),
("expiry_cutoff",(6,7,8,1,9,5,2),"expiry_cutoff","Expiry cutoff is scenario assumption, not authority.","BLOCKED"),
("data_quality_recovery",(6,7,8,1,9,5,2),"data_quality_recovery","Recover only after new valid observation; no stale reuse.","PASS_WITH_LIMITATION"),
("identity_conflict",(6,7,8,1,9,5,2),"contract_identity_conflict","Unresolved identity stays blocked; no production ID mint/alias.","BLOCKED"),
("unknown_multiplier",(7,8,1,9,5,2),"contract_multiplier_missing","Missing multiplier blocks valuation and sizing.","BLOCKED"),
("limit_wait_cancel_no_price_reach",(6,7,8,1,9,5,2),"limit_order_wait_cancel","No price reach means no fill; preserve wait/cancel.","PASS_WITH_LIMITATION"),
("limit_price_reached_insufficient_volume",(6,7,8,1,9,5,2),"limit_order_volume_gate","Price reach without volume support is not a fill.","PASS_WITH_LIMITATION"),
("one_order_at_a_time",(6,7,8,1,9,5,2),"order_serialization","Preserve sequential one-order-at-a-time constraint.","PASS_WITH_LIMITATION"),
("synthetic_input_rejected_real_vts_live",(6,7,8,1,9,5,2),"provenance_boundary","REAL_VTS/Live reject DERIVED_SCENARIO before routing.","BLOCKED"),
)

@dataclass(frozen=True, slots=True)
class SynEvtScenario:
    scenario_id: str
    event_id: str
    sequence: int
    strategy_ids: tuple[int, ...]
    event_kind: str
    expected_invariant: str
    runtime_expected_status: str
    synthetic: bool
    provenance: str
    source_status: str
    generator_version: str
    schema_version: int
    seed: int
    config_hash: str
    identity_source_status: str
    production_runtime_eligible: bool
    validation_only: bool
    def as_record(self) -> dict[str, object]:
        record = asdict(self)
        record["strategy_ids"] = list(self.strategy_ids)
        return record

@dataclass(frozen=True, slots=True)
class SynEvtValidation:
    scenario_id: str
    status: str
    checks: tuple[str, ...]
    reasons: tuple[str, ...]

def _config_hash(seed: int) -> str:
    config = {"schema_version":1,"generator_version":GENERATOR_VERSION,"seed":seed,
        "strategy_order":list(DEFAULT_STRATEGY_ORDER),
        "events":[[sid,list(st),kind,inv,exp] for sid,st,kind,inv,exp in _DEFS],
        "threshold_policy":"configuration-only-no-tuning-in-A1-2",
        "output_kind":"scenario-specification-only","timezone":"Asia/Seoul"}
    return sha256(json.dumps(config,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def produce_syn_evt_scenarios(*, seed: int) -> tuple[SynEvtScenario, ...]:
    """Return deterministic scenario definitions; seed is mandatory."""
    if isinstance(seed,bool) or not isinstance(seed,int):
        raise TypeError("SEED_MUST_BE_INTEGER")
    config_hash = _config_hash(seed)
    return tuple(SynEvtScenario(
        scenario_id=sid,event_id=sha256(f"{GENERATOR_VERSION}:{seq}:{sid}".encode()).hexdigest(),
        sequence=seq,strategy_ids=st,event_kind=kind,expected_invariant=inv,
        runtime_expected_status=exp,synthetic=True,provenance=PROVENANCE,source_status=SOURCE_STATUS,
        generator_version=GENERATOR_VERSION,schema_version=1,seed=seed,config_hash=config_hash,
        identity_source_status=IDENTITY_SOURCE_STATUS,production_runtime_eligible=False,validation_only=True)
        for seq,(sid,st,kind,inv,exp) in enumerate(_DEFS,1))

def validate_syn_evt_catalog(scenarios: Iterable[SynEvtScenario]) -> tuple[SynEvtValidation, ...]:
    """Check catalogue structure only; not event behavior or runtime execution."""
    items=tuple(scenarios); ids=[x.scenario_id for x in items]; results=[]
    for x in items:
        checks=[]; reasons=[]
        rules=(
            (x.synthetic is True and x.provenance==PROVENANCE,"synthetic_provenance","SYNTHETIC_PROVENANCE_REQUIRED"),
            (x.generator_version==GENERATOR_VERSION and x.schema_version==1,"versioned_schema","GENERATOR_SCHEMA_MISMATCH"),
            (isinstance(x.seed,int) and not isinstance(x.seed,bool) and len(x.config_hash)==64,"reproducibility_metadata","SEED_OR_CONFIG_HASH_INVALID"),
            (bool(x.event_id) and x.sequence>0 and bool(x.expected_invariant.strip()),"stable_event_and_invariant","EVENT_ID_SEQUENCE_OR_INVARIANT_MISSING"),
            (bool(x.strategy_ids) and all(s in DEFAULT_STRATEGY_ORDER for s in x.strategy_ids),"approved_strategy_scope","STRATEGY_SCOPE_INVALID"),
            (x.identity_source_status==IDENTITY_SOURCE_STATUS and x.production_runtime_eligible is False and x.validation_only is True,"identity_runtime_isolation","IDENTITY_OR_RUNTIME_BOUNDARY_VIOLATION"),
            (ids.count(x.scenario_id)==1,"unique_scenario_id","DUPLICATE_SCENARIO_ID"))
        for ok,check,reason in rules:
            (checks if ok else reasons).append(check if ok else reason)
        results.append(SynEvtValidation(x.scenario_id,"PASS" if not reasons else "FAIL",tuple(checks),tuple(reasons)))
    return tuple(results)
