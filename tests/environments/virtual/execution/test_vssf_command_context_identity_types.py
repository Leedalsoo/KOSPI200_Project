from decimal import Decimal

import pytest

from contracts.futures_contract_spec import FuturesProductType
from contracts.futures_identity_source_port import FuturesInstrumentIdentity
from contracts.types import BrokerOrderCommand, OptionInstrumentIdentity
from environments.virtual.execution.vssf_command_context_provider import (
    CanonicalVSSFCommandContextProvider,
    VSSFCommandContextError,
)


def _option_identity():
    return OptionInstrumentIdentity(
        instrument_id="SYNTHETIC_CONTRACT:S2:CALL:20261112:500",
        symbol="SYNTHETIC_CONTRACT:S2:CALL:20261112:500",
        expiry="20261112", option_type="CALL", strike=Decimal("500"),
        contract_multiplier=Decimal("250000"),
        identity_source="SYNTHETIC:DERIVED_SCENARIO",
    )


def _futures_identity():
    return FuturesInstrumentIdentity(
        instrument_id="KIS-FUTURES-2001", symbol="KIS-FUTURES-2001",
        product_type=FuturesProductType.MINI, contract_multiplier=Decimal("50000"),
        identity_source="KIS_FUTURES_MASTER",
    )


def _command(asset_type, identity):
    return BrokerOrderCommand(
        client_order_id="identity-type-test", instrument_id=identity.instrument_id,
        side="BUY", quantity=1, order_type="LIMIT", broker_symbol=identity.symbol,
        instrument_identity=identity, asset_type=asset_type,
        requested_price=Decimal("10"), track_id="identity-test", tag_id="LEG-1",
    )


def test_vssf_context_accepts_matching_option_identity_type():
    result = CanonicalVSSFCommandContextProvider().build_command(
        _command("OPTION", _option_identity())
    )
    assert result.asset_type.value == "OPTION"
    assert result.option_type.value == "CALL"
    assert result.instrument_id.startswith("SYNTHETIC_CONTRACT:")


def test_vssf_context_accepts_matching_futures_identity_type():
    result = CanonicalVSSFCommandContextProvider().build_command(
        _command("FUTURES", _futures_identity())
    )
    assert result.asset_type.value == "FUTURES"
    assert result.option_type is None
    assert result.instrument_id == "KIS-FUTURES-2001"


def test_vssf_context_rejects_option_identity_mislabeled_as_futures():
    with pytest.raises(VSSFCommandContextError, match="FUTURES_IDENTITY_TYPE_REQUIRED"):
        CanonicalVSSFCommandContextProvider().build_command(
            _command("FUTURES", _option_identity())
        )


def test_vssf_context_rejects_futures_identity_mislabeled_as_option():
    with pytest.raises(VSSFCommandContextError, match="OPTION_IDENTITY_TYPE_REQUIRED"):
        CanonicalVSSFCommandContextProvider().build_command(
            _command("OPTION", _futures_identity())
        )
