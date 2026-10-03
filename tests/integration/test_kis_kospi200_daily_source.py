from datetime import date
from decimal import Decimal
import json
import pytest

from infrastructure.kis.auth import KISAuthManager
from infrastructure.kis.kis_kospi200_daily_source import KISKOSPI200DailySource

class Response:
    def __init__(self, payload): self.payload = payload
    def read(self): return json.dumps(self.payload).encode()
    def __enter__(self): return self
    def __exit__(self, *args): return False

def test_kospi200_daily_source_maps_open_and_previous_close():
    seen = {}
    def market(request, timeout):
        seen["url"] = request.full_url; seen["tr_id"] = request.headers.get("Tr_id")
        return Response({"rt_cd":"0","output2":[
            {"stck_bsop_date":"20260929","bstp_nmix_oprc":"1110.10","bstp_nmix_prpr":"1118.20"},
            {"stck_bsop_date":"20260930","bstp_nmix_oprc":"1122.30","bstp_nmix_prpr":"1130.40"},
        ]})
    auth=KISAuthManager(app_key="key",app_secret="secret",base_url="https://example.test",urlopen=lambda r, timeout: Response({"access_token":"token","expires_in":3600}))
    auth.issue_token()
    source=KISKOSPI200DailySource(auth,urlopen=market)
    result=source.get_context(date(2026,9,30))
    assert seen["tr_id"] == "FHPUP02120000"
    assert "FID_INPUT_ISCD=2001" in seen["url"]
    assert result.trading_date == date(2026,9,30)
    assert result.open_price == Decimal("1122.30")
    assert result.previous_close == Decimal("1118.20")

def test_kospi200_daily_source_fails_closed_without_credentials():
    source=KISKOSPI200DailySource(KISAuthManager())
    with pytest.raises(RuntimeError, match="KIS_KOSPI200_DAILY_CREDENTIALS_UNAVAILABLE"):
        source.get_context(date(2026,9,30))
