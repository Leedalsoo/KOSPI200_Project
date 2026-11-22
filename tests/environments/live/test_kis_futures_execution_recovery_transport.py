import json
from urllib.parse import parse_qs, urlparse

import pytest

from environments.live.execution.kis_futures_execution_recovery_adapter import KISExecutionRecoveryQuery
from environments.live.execution.kis_futures_execution_recovery_transport import KISFuturesExecutionRecoveryTransport


class _Auth:
    base_url = "https://kis.synthetic.invalid"

    def get_auth_headers(self, *, tr_id):
        return {"tr_id": tr_id, "authorization": "Bearer SYNTHETIC_ONLY"}


class _Response:
    def __init__(self, body, tr_cont):
        self._body = json.dumps(body).encode("utf-8")
        self.headers = {"tr_cont": tr_cont}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self._body


@pytest.mark.parametrize("first_page_continuation", ["F", "M"])
def test_recovery_transport_fetches_all_pages_and_sends_n_on_continuation(first_page_continuation):
    requests = []
    responses = [
        _Response(
            {"rt_cd": "0", "output1": [{"odno": "order-page-1"}], "ctx_area_fk200": "FK-NEXT", "ctx_area_nk200": "NK-NEXT"},
            first_page_continuation,
        ),
        _Response({"rt_cd": "0", "output1": [{"odno": "order-page-2"}]}, "D"),
    ]

    def fake_urlopen(request, timeout):
        requests.append(request)
        assert timeout == 10.0
        return responses.pop(0)

    transport = KISFuturesExecutionRecoveryTransport(auth=_Auth(), urlopen=fake_urlopen)
    query = KISExecutionRecoveryQuery(
        cano="SYNTHETIC-CANO",
        account_product_code="SYNTHETIC-PRODUCT",
        start_order_date="20261122",
        end_order_date="20261122",
        virtual=True,
    )

    result = transport.inquire(query)

    assert result["output1"] == [{"odno": "order-page-1"}, {"odno": "order-page-2"}]
    assert len(requests) == 2
    next_headers = {key.lower(): value for key, value in requests[1].header_items()}
    assert next_headers["tr_cont"] == "N"
    next_params = parse_qs(urlparse(requests[1].full_url).query)
    assert next_params["CTX_AREA_FK200"] == ["FK-NEXT"]
    assert next_params["CTX_AREA_NK200"] == ["NK-NEXT"]
