import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

import os

# Safe defaults let tests run without a local .env file.
os.environ.setdefault("N8N_WEBHOOK_URL", "http://n8n.test/webhook/ai-chat")
os.environ.setdefault("N8N_WEBHOOK_SECRET", "test-only-secret")

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
        with main._chat_concurrency_lock:
            main._active_chat_requests = 0

    async def post_chat(self, payload):
        transport = httpx.ASGITransport(app=main.app)

        async with _REAL_ASYNC_CLIENT(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.post("/api/ai-chat", json=payload)

    async def post_raw_chat(self, content, headers=None):
        transport = httpx.ASGITransport(app=main.app)

        async with _REAL_ASYNC_CLIENT(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.post(
                "/api/ai-chat",
                content=content,
                headers=headers,
            )

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

    async def test_blank_message_returns_422_without_calling_n8n(self):
        with patch("main.httpx.AsyncClient") as upstream:
            response = await self.post_chat({
                "sessionId": "test-session",
                "message": "   ",
            })

        self.assertEqual(response.status_code, 422)
        upstream.assert_not_called()

    async def test_blank_session_id_returns_422_without_calling_n8n(self):
        with patch("main.httpx.AsyncClient") as upstream:
            response = await self.post_chat({
                "sessionId": "   ",
                "message": "Test message",
            })

        self.assertEqual(response.status_code, 422)
        upstream.assert_not_called()

    async def test_extra_fields_are_rejected(self):
        with patch("main.httpx.AsyncClient") as upstream:
            response = await self.post_chat({
                "sessionId": "test-session",
                "message": "Test message",
                "admin": True,
            })

        self.assertEqual(response.status_code, 422)
        upstream.assert_not_called()

    async def test_oversized_body_returns_413_without_calling_n8n(self):
        body = (
            b'{"sessionId":"test-session","message":"'
            + b"x" * main.MAX_CHAT_REQUEST_BODY_BYTES
            + b'"}'
        )

        with patch("main.httpx.AsyncClient") as upstream:
            response = await self.post_raw_chat(
                body,
                headers={"Content-Type": "application/json"},
            )

        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["detail"], "Request body too large.")
        upstream.assert_not_called()

    async def test_oversized_stream_without_content_length_returns_413(self):
        async def chunks():
            yield b'{"sessionId":"test-session","message":"'
            yield b"x" * main.MAX_CHAT_REQUEST_BODY_BYTES
            yield b'"}'

        with patch("main.httpx.AsyncClient") as upstream:
            response = await self.post_raw_chat(
                chunks(),
                headers={"Content-Type": "application/json"},
            )

        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["detail"], "Request body too large.")
        upstream.assert_not_called()

    async def test_concurrency_limit_rejects_extra_request_without_calling_n8n(self):
        started = asyncio.Event()
        release = asyncio.Event()

        async def delayed_post(*args, **kwargs):
            started.set()
            await release.wait()
            return FakeResponse(status_code=200, payload={"output": "ok"})

        client = self.fake_upstream_client()
        client.post = AsyncMock(side_effect=delayed_post)
        first_response = None

        with patch("main.httpx.AsyncClient", return_value=client), patch.object(
            main, "MAX_CONCURRENT_CHAT_REQUESTS", 1
        ):
            first_task = asyncio.create_task(
                self.post_chat({
                    "sessionId": "first-session",
                    "message": "First request",
                })
            )

            try:
                await asyncio.wait_for(started.wait(), timeout=2)
                second_response = await self.post_chat({
                    "sessionId": "second-session",
                    "message": "Second request",
                })

                self.assertEqual(second_response.status_code, 503)
                self.assertEqual(
                    second_response.json()["detail"],
                    "AI assistant is busy. Please try again shortly.",
                )
                self.assertEqual(second_response.headers["retry-after"], "5")
                client.post.assert_awaited_once()
            finally:
                release.set()
                first_response = await asyncio.wait_for(first_task, timeout=2)

        self.assertEqual(first_response.status_code, 200)

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
