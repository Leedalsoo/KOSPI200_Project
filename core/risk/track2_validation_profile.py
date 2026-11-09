from __future__ import annotations
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

DEFAULT_TRACK2_VALIDATION_PROFILE=Path(__file__).resolve().parents[2]/"config"/"validation_only"/"track2"/"risk_profile.v1.json"
class Track2ValidationProfileError(ValueError): pass

@dataclass(frozen=True)
class Track2ValidationProfile:
    profile_id:str
    strategy_id:str
    policy_dependencies:tuple[str,...]
    execution_enabled:bool
    order_submission_enabled:bool
    numeric_limits_resolved:bool
    def require_execution(self)->None:
        raise Track2ValidationProfileError("TRACK2_VALIDATION_ONLY_PROFILE_CANNOT_AUTHORIZE_EXECUTION")

def load_track2_validation_profile(path: str|Path=DEFAULT_TRACK2_VALIDATION_PROFILE)->Track2ValidationProfile:
    try: raw:Any=json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError,json.JSONDecodeError) as exc: raise Track2ValidationProfileError("TRACK2_VALIDATION_PROFILE_UNAVAILABLE_OR_INVALID") from exc
    if not isinstance(raw,dict) or raw.get("schema_version")!="1.0.0": raise Track2ValidationProfileError("TRACK2_VALIDATION_PROFILE_SCHEMA_UNSUPPORTED")
    if raw.get("profile_type")!="VALIDATION_ONLY" or raw.get("strategy_id")!="track2_asymmetric_trap": raise Track2ValidationProfileError("TRACK2_VALIDATION_PROFILE_IDENTITY_INVALID")
    if any(raw.get(key) is not False for key in ("execution_enabled","order_submission_enabled","live_api_enabled","real_vts_api_enabled")): raise Track2ValidationProfileError("TRACK2_VALIDATION_PROFILE_MUST_REMAIN_DISABLED")
    limits=raw.get("risk_limits")
    if not isinstance(limits,dict) or not limits or any(v is not None for v in limits.values()): raise Track2ValidationProfileError("TRACK2_VALIDATION_PROFILE_LIMITS_MUST_REMAIN_NULL")
    deps=raw.get("unresolved_policy_dependencies"); required={"S2-U16","S2-U17","S2-U18","S2-U19","S2-U20","S2-U21"}
    if not isinstance(deps,list) or set(deps)!=required: raise Track2ValidationProfileError("TRACK2_VALIDATION_PROFILE_POLICY_REGISTER_MISMATCH")
    return Track2ValidationProfile(str(raw.get("profile_id") or ""),str(raw["strategy_id"]),tuple(sorted(deps)),False,False,False)
