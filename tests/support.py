from decimal import Decimal

from core.option.option_master import InMemoryOptionContractMaster, KisOptionContractIdentity


def build_test_option_master() -> InMemoryOptionContractMaster:
    master = InMemoryOptionContractMaster()
    for option_type in ("CALL", "PUT"):
        for strike in (335, 350, 365):
            master.register_contract_identity(
                KisOptionContractIdentity(
                    shrn_iscd=f"TEST-{option_type[0]}-{strike}",
                    stnd_iscd=None,
                    expiry="2026-09-10",
                    option_type=option_type,
                    strike=Decimal(str(strike)),
                    contract_multiplier=Decimal("250000"),
                )
            )
    return master
