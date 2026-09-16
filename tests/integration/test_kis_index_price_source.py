from datetime import datetime
from decimal import Decimal
import json

import pytest

from infrastructure.kis.auth import KISAuthManager
from infrastructure.kis.index_price_source import KISKOSPI200IndexPriceSource


class Response:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_kospi200_source_uses_authoritative_kis_contract():
    seen = {}

    def fake_market_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["tr_id"] = request.headers.get("Tr_id")
        return Response({"rt_cd": "0", "output": {"bstp_nmix_prpr": "351.25"}})

    def fake_auth_urlopen(request, timeout):
        return Response({"access_token": "token", "expires_in": 3600})

    auth = KISAuthManager(
        app_key="key", app_secret="secret", base_url="https://example.test",
        urlopen=fake_auth_urlopen,
    )
    auth.issue_token()
    source = KISKOSPI200IndexPriceSource(
        auth, urlopen=fake_market_urlopen,
        clock=lambda: datetime(2026, 9, 16, 10, 0, 1),
    )
    observation = source.refresh()
    assert seen["tr_id"] == "FHPUP02100000"
    assert "FID_INPUT_ISCD=2001" in seen["url"]
    assert observation.underlying_symbol == "KOSPI200"
    assert observation.index_code == "2001"
    assert observation.price == Decimal("351.25")


def test_kospi200_source_fails_closed_without_credentials():
    source = KISKOSPI200IndexPriceSource(KISAuthManager())
    with pytest.raises(RuntimeError, match="KIS_INDEX_PRICE_CREDENTIALS_UNAVAILABLE"):
        source.refresh()
