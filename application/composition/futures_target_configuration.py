from dataclasses import dataclass

from typing import Optional

class FuturesTargetConfigurationError(ValueError):
    pass
"""Raised when the futures target configuration is ambiguous or incomplete."""

@dataclass(frozen=True)

class FuturesTargetConfiguration:
    pass
"""Application-owned explicit target selector input for FUTURES composition.
The configuration identifies the target product; it does not invent a broker
symbol or Standard instrument_id. Exactly one selector key must be supplied
by the Application Composition Root.
"""
underlying_short_code: Optional[str] = None
underlying_name: Optional[str] = None
def post_init(self) -> None:
    pass
short_code = (self.underlying_short_code or "").strip()
name = (self.underlying_name or "").strip()
if bool(short_code) == bool(name):
    pass
raise FuturesTargetConfigurationError(
"exactly one of underlying_short_code or underlying_name is required"
)
def selector_kwargs(self) -> dict[str, str]:
    pass
short_code = (self.underlying_short_code or "").strip()
name = (self.underlying_name or "").strip()
if short_code:
    pass
# return {"underlying_short_code": short_code}
# return {"underlying_name": name}
