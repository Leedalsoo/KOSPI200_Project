import pytest

from application.composition.track3_multi_leg_execution_plan_adapter import (
    Track3MultiLegExecutionPlanAdapter,
)


def test_track3_execution_plan_stays_blocked_until_tradable_spread_legs_are_defined():
    adapter = Track3MultiLegExecutionPlanAdapter()

    with pytest.raises(ValueError, match="TRACK3_SPREAD_LEG_DEFINITION_UNRESOLVED"):
        adapter.build_plan(
            strategy_id="Strategy_3_StatArb",
            group_id="s3-unresolved-spread",
            side="BUY",
            quantity=1,
            identity=None,
            hedge_identity_source=None,
        )


@pytest.mark.parametrize("asset_type", ("EQUITY", "ETF", "CASH_BASKET"))
def test_canonical_order_transport_rejects_synthetic_cash_proxy_asset_types(asset_type):
    from decimal import Decimal

    from contracts.canonical_order_transport import (
        CanonicalOrderTransportError,
        CanonicalOrderTransportInput,
        validate_lossless_transport,
    )

    request = CanonicalOrderTransportInput(
        client_order_id="S3-SYNTHETIC-CASH-001",
        asset_type=asset_type,
        side="BUY",
        quantity=1,
        price=Decimal("100"),
        option_type=None,
        strike=None,
        symbol=None,
        expiry=None,
        track_id="Strategy_3_StatArb",
        tag_id="S3_CASH_PROXY",
        instrument_id="SYNTHETIC_CONTRACT:S3:CASH_PROXY",
    )

    with pytest.raises(CanonicalOrderTransportError, match="ASSET_TYPE_REQUIRED"):
        validate_lossless_transport(request)


def test_track3_adapter_stays_blocked_even_with_synthetic_futures_identity():
    from decimal import Decimal

    from contracts.futures_contract_spec import FuturesProductType
    from contracts.futures_identity_source_port import FuturesInstrumentIdentity

    adapter = Track3MultiLegExecutionPlanAdapter()
    identity = FuturesInstrumentIdentity(
        instrument_id="SYNTHETIC_CONTRACT:S3:FUTURES_PROXY",
        symbol="SYNTHETIC_FUTURES_PROXY",
        product_type=FuturesProductType.STANDARD,
        contract_multiplier=Decimal("250000"),
        identity_source="SYNTHETIC:DERIVED_SCENARIO",
    )

    with pytest.raises(ValueError, match="TRACK3_SPREAD_LEG_DEFINITION_UNRESOLVED"):
        adapter.build_plan(
            strategy_id="Strategy_3_StatArb",
            group_id="s3-synthetic-futures-only",
            side="BUY",
            quantity=1,
            identity=identity,
            hedge_identity_source=object(),
        )


def test_virtual_multi_leg_bridge_does_not_alias_cash_proxy_identity_as_futures():
    from dataclasses import dataclass, replace
    from decimal import Decimal

    from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge
    from core.oms.multi_leg_plan import build_trap_plan

    @dataclass(frozen=True)
    class SyntheticCashBasketIdentity:
        instrument_id: str
        symbol: str

    plan = build_trap_plan(
        group_id="s3-cash-proxy-identity-boundary",
        strategy_id="Strategy_3_StatArb",
        purpose="S3_SYNTHETIC_CASH_PROXY",
        short_put=Decimal("90"),
        short_call=Decimal("110"),
        long_put=Decimal("95"),
        long_call=Decimal("105"),
        quantity=1,
    )
    cash_identity = SyntheticCashBasketIdentity(
        instrument_id="SYNTHETIC_CONTRACT:S3:CASH_PROXY",
        symbol="SYNTHETIC_CASH_PROXY",
    )
    plan = replace(plan, legs=(replace(plan.legs[0], instrument_identity=cash_identity), *plan.legs[1:]))
    bridge = VirtualMultiLegExecutionBridge.__new__(VirtualMultiLegExecutionBridge)

    with pytest.raises(ValueError, match="MULTI_LEG_STORED_INSTRUMENT_IDENTITY_TYPE_INVALID"):
        bridge.identity_for_leg(plan, plan.legs[0])
