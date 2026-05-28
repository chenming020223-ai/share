import ssl
import unittest

from worldcup_predictor.api_football import (
    ApiFootballError,
    _http_error,
    _is_retryable_transport_error,
    _transport_error,
)
from worldcup_predictor.web_server import _api_error_status


class ApiFootballErrorTest(unittest.TestCase):
    def test_ssl_eof_is_retryable_network_error(self):
        error = ssl.SSLError("UNEXPECTED_EOF_WHILE_READING")

        self.assertTrue(_is_retryable_transport_error(error))

        api_error = _transport_error(error, retries=3)
        self.assertEqual(api_error.kind, "network")
        self.assertTrue(api_error.retryable)
        self.assertIn("自动重试 3 次", str(api_error))

    def test_http_rate_limit_is_structured(self):
        error = _http_error(429, '{"message":"rate limit"}')

        self.assertEqual(error.kind, "rate_limit")
        self.assertTrue(error.retryable)
        self.assertEqual(error.status_code, 429)
        self.assertIn("额度", str(error))

    def test_web_status_code_for_api_error_kind(self):
        auth = ApiFootballError("bad key", kind="auth")
        network = ApiFootballError("network", kind="network", retryable=True)

        self.assertEqual(_api_error_status(auth).value, 401)
        self.assertEqual(_api_error_status(network).value, 502)


if __name__ == "__main__":
    unittest.main()
