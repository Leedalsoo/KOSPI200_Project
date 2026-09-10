from __future__ import annotations

from typing import Protocol

from contracts.external_authoritative_option_identity_record import (
ExternalAuthoritativeOptionIdentityRecord,
)
from contracts.option_identity_source_port import (
OptionIdentitySelection,
OptionIdentitySource,
)
from contracts.types import OptionInstrumentIdentity


class AuthoritativeOptionIdentitySource(OptionIdentitySource, Protocol):
    """Compatibility view of the single external authoritative identity seam.

    New lookup paths use ``resolve(selection)`` and return the source-owned
    record. ``get_identity`` is retained only for callers that already hold a
    complete authoritative identity.
    """

    def get_identity(self, selector: object) -> OptionInstrumentIdentity | None:
        ...


class AuthoritativeOptionIdentityRecordSource(OptionIdentitySource, Protocol):
    """Explicit alias for implementations returning the external record."""

    def resolve(
self,
        selection: OptionIdentitySelection,
    ) -> ExternalAuthoritativeOptionIdentityRecord | None:
        ...
