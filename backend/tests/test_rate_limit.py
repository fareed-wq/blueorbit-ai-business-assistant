import unittest
from unittest.mock import patch

from fastapi import HTTPException

import main


class RateLimitTests(unittest.TestCase):
    def setUp(self):
        main._rate_limit_requests.clear()

    def test_rejects_request_21(self):
        with patch("main.time.monotonic", return_value=100.0):
            for _ in range(20):
                main.enforce_rate_limit("test-client")

            with self.assertRaises(HTTPException) as result:
                main.enforce_rate_limit("test-client")

        self.assertEqual(result.exception.status_code, 429)
        self.assertIn("Retry-After", result.exception.headers)

    def test_clients_have_independent_limits(self):
        with patch("main.time.monotonic", return_value=100.0):
            for _ in range(20):
                main.enforce_rate_limit("client-a")

            main.enforce_rate_limit("client-b")

    def test_expired_requests_do_not_count(self):
        with patch("main.time.monotonic", side_effect=[0.0] * 20 + [61.0]):
            for _ in range(20):
                main.enforce_rate_limit("test-client")

            # After 61 seconds, the previous 20 requests have expired.
            main.enforce_rate_limit("test-client")


if __name__ == "__main__":
    unittest.main()
