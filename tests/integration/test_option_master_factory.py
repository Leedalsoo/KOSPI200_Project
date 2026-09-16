import unittest
from decimal import Decimal

from unittest.mock import patch
from application.composition.option_master_factory import create_production_option_master, create_production_trading_calendar
from infrastructure.kis.auth import KISAuthManager

class OptionMasterCompositionTests(unittest.TestCase):
    def test_calendar_can_be_composed_without_core_infrastructure_import(self):
        auth=KISAuthManager("key","secret",cache_file_path=None)
        calendar=create_production_trading_calendar(auth_manager=auth,auto_load_kis=False)
        self.assertTrue(hasattr(calendar,"is_trading_day"))

    @patch("application.composition.option_master_factory.create_default_option_master")
    def test_master_receives_composed_calendar(self, create_master):
        auth=KISAuthManager("key","secret",cache_file_path=None)
        create_production_option_master(auth_manager=auth,auto_load_calendar=False,auto_load_kis_master=False)
        self.assertIn("calendar",create_master.call_args.kwargs)

if __name__ == "__main__":
    unittest.main()


def test_virtual_option_master_uses_explicit_historical_source(tmp_path):
    from application.composition.option_master_factory import create_virtual_option_master

    source = tmp_path / "historical.mst"
    source.write_text(
        "6|C01609335|KR4C01693350|KOSPI200 202609 P 335||335.00\n",
        encoding="cp949",
    )
    master = create_virtual_option_master(historical_source_path=str(source))
    identity = master.get_contract_identity("C01609335")
    assert identity is not None
    assert identity.shrn_iscd == "C01609335"
    assert identity.option_type == "PUT"
    assert identity.strike == Decimal("335.00")
