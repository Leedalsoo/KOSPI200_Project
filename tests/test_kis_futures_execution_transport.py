from infrastructure.kis.auth import KISAuthManager
from infrastructure.kis.futures_execution_transport import (
    KISFuturesExecutionTransport,
    KISFuturesExecutionTransportConfig,
)


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return b'{"approval_key":"TEST-APPROVAL"}'


def test_issue_approval_key_uses_auth_base_url_and_injected_urlopen():
    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return _Response()

    auth = KISAuthManager(
        app_key="APP",
        app_secret="SECRET",
        base_url="https://vts.example.test:29443/",
        is_vts=True,
    )
    transport = KISFuturesExecutionTransport(
        auth,
        KISFuturesExecutionTransportConfig(timeout=7.5),
        urlopen=fake_urlopen,
    )

    assert transport._issue_approval_key() == "TEST-APPROVAL"
    assert len(requests) == 1
    request, timeout = requests[0]
    assert request.full_url == "https://vts.example.test:29443/oauth2/Approval"
    assert timeout == 7.5
