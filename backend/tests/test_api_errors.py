import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

import main


# Preserve the real client used to send test requests to FastAPI.
_REAL_ASYNC_CLIENT = httpx.AsyncClient


class FakeResponse:
    def __init__(self, status_code, payload=None, invalid_json=False):
        self.status_code = status_code
        self.payload = payload
        self.invalid_json = invalid_json

    def json(self):
        if self.invalid_json:
            raise ValueError("Private upstream response details")
        return self.payload


class APIErrorHandlingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        with main._rate_limit_lock:
            main._rate_limit_requests.clear()

    async def post_chat(self, payload):
        transport = httpx.ASGITransport(app=main.app)

        async with _REAL_ASYNC_CLIENT(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.post("/api/ai-chat", json=payload)

    def fake_upstream_client(self, response=None, error=None):
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        if error is not None:
            client.post = AsyncMock(side_effect=error)
        else:
            client.post = AsyncMock(return_value=response)

        return client

    async def test_invalid_request_returns_422_without_calling_n8n(self):
        with patch("main.httpx.AsyncClient") as upstream:
            response = await self.post_chat({"sessionId": "test-session"})

        self.assertEqual(response.status_code, 422)
        upstream.assert_not_called()

    async def test_upstream_connection_error_hides_internal_details(self):
        client = self.fake_upstream_client(
            error=httpx.ConnectError("private connection details")
        )

        with patch("main.httpx.AsyncClient", return_value=client):
            response = await self.post_chat({
                "sessionId": "test-session",
                "message": "Test message",
            })

        self.assertEqual(response.status_code, 502)
        self.assertEqual(
            response.json()["detail"],
            "AI assistant service is unavailable.",
        )
        self.assertNotIn("private connection details", response.text)

    async def test_upstream_http_error_returns_generic_502(self):
        client = self.fake_upstream_client(
            response=FakeResponse(status_code=500)
        )

        with patch("main.httpx.AsyncClient", return_value=client):
            response = await self.post_chat({
                "sessionId": "test-session",
                "message": "Test message",
            })

        self.assertEqual(response.status_code, 502)
        self.assertEqual(
            response.json()["detail"],
            "AI assistant request failed.",
        )

    async def test_invalid_upstream_json_returns_generic_502(self):
        client = self.fake_upstream_client(
            response=FakeResponse(status_code=200, invalid_json=True)
        )

        with patch("main.httpx.AsyncClient", return_value=client):
            response = await self.post_chat({
                "sessionId": "test-session",
                "message": "Test message",
            })

        self.assertEqual(response.status_code, 502)
        self.assertEqual(
            response.json()["detail"],
            "AI assistant returned an invalid response.",
        )
        self.assertNotIn("Private upstream response details", response.text)


if __name__ == "__main__":
    unittest.main()
