import json
import time
import unittest
from unittest.mock import patch

from infrastructure.kis.auth import KISAuthManager, KISAuthToken


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class KISAuthManagerTests(unittest.TestCase):
    def test_from_env_resolves_vts_credentials(self):
        with patch.dict(
            "os.environ",
            {"KIS_VTS_APP_KEY": "key", "KIS_VTS_APP_SECRET": "secret"},
            clear=True,
        ):
            auth = KISAuthManager.from_env(cache_file_path=None)
        self.assertTrue(auth.has_credentials())
        self.assertEqual(auth.app_key, "key")

    def test_valid_token_is_reused_without_http_call(self):
        calls = []
        auth = KISAuthManager(
            "key", "secret", cache_file_path=None,
            urlopen=lambda *_args, **_kwargs: calls.append(1),
        )
        auth._current_token = KISAuthToken(
            access_token="live-token",
            token_expired_at=time.time() + 3600,
        )
        self.assertEqual(auth.get_access_token(), "live-token")
        self.assertEqual(calls, [])

    def test_expired_token_is_reissued(self):
        calls = []
        def urlopen(*_args, **_kwargs):
            calls.append(1)
            return _Response({"access_token": "new-token", "expires_in": 3600})

        auth = KISAuthManager("key", "secret", cache_file_path=None, urlopen=urlopen)
        auth._current_token = KISAuthToken(
            access_token="old-token",
            token_expired_at=time.time() - 1,
        )
        self.assertEqual(auth.get_access_token(), "new-token")
        self.assertEqual(len(calls), 1)

    def test_auth_headers_include_tr_id(self):
        auth = KISAuthManager("key", "secret", cache_file_path=None)
        auth._current_token = KISAuthToken(
            access_token="token",
            token_expired_at=time.time() + 3600,
        )
        headers = auth.get_auth_headers("FHPST02300000")
        self.assertEqual(headers["authorization"], "Bearer token")
        self.assertEqual(headers["tr_id"], "FHPST02300000")

    def test_vts_does_not_fallback_to_generic_or_real_credentials(self):
        with patch.dict("os.environ", {"KIS_APP_KEY": "generic-key", "KIS_APP_SECRET": "generic-secret", "REAL_BROKER_APP_KEY": "real-key", "REAL_BROKER_APP_SECRET": "real-secret"}, clear=True):
            auth = KISAuthManager.from_env(is_vts=True, env_file="__missing_test_env__.env", cache_file_path=None)
        self.assertFalse(auth.has_credentials())
        self.assertEqual(auth.app_key, "")
        self.assertEqual(auth.app_secret, "")

    def test_vts_does_not_inherit_generic_base_url(self):
        with patch.dict("os.environ", {"KIS_VTS_APP_KEY": "vts-key", "KIS_VTS_APP_SECRET": "vts-secret", "KIS_BASE_URL": "https://openapi.koreainvestment.com:9443"}, clear=True):
            auth = KISAuthManager.from_env(is_vts=True, cache_file_path=None)
        self.assertEqual(auth.base_url, "https://openapivts.koreainvestment.com:29443")

    def test_real_does_not_fallback_to_generic_credentials(self):
        with patch.dict("os.environ", {"KIS_APP_KEY": "generic-key", "KIS_APP_SECRET": "generic-secret"}, clear=True):
            auth = KISAuthManager.from_env(is_vts=False, cache_file_path=None)
        self.assertFalse(auth.has_credentials())
        self.assertEqual(auth.app_key, "")
        self.assertEqual(auth.app_secret, "")


if __name__ == "__main__":
    pass
# unittest.main()
