import os
import time
from collections import defaultdict, deque
from threading import Lock

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, field_validator

load_dotenv()

N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL")
N8N_WEBHOOK_SECRET = os.getenv("N8N_WEBHOOK_SECRET")
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")

if not N8N_WEBHOOK_URL:
    raise RuntimeError("N8N_WEBHOOK_URL is not configured")

if not N8N_WEBHOOK_SECRET:
    raise RuntimeError("N8N_WEBHOOK_SECRET is not configured")

MAX_CHAT_REQUEST_BODY_BYTES = 64 * 1024
MAX_CONCURRENT_CHAT_REQUESTS = 10
CONCURRENCY_RETRY_AFTER_SECONDS = 5

_chat_concurrency_lock = Lock()
_active_chat_requests = 0


class RequestBodyLimitMiddleware:
    """Limit streamed request bodies on the chat endpoint."""

    def __init__(self, app, max_body_bytes: int):
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope, receive, send):
        if (
            scope.get("type") != "http"
            or scope.get("path") != "/api/ai-chat"
            or scope.get("method") != "POST"
        ):
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        content_length = headers.get(b"content-length")

        if content_length is not None:
            try:
                if int(content_length) > self.max_body_bytes:
                    await self._reject_oversized(send)
                    return
            except ValueError:
                pass  # Enforce the limit while reading the body below.

        body = bytearray()
        while True:
            message = await receive()

            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                continue

            chunk = message.get("body", b"")
            if len(body) + len(chunk) > self.max_body_bytes:
                await self._reject_oversized(send)
                return
            body.extend(chunk)

            if not message.get("more_body", False):
                break

        body_sent = False

        async def replay_receive():
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {
                    "type": "http.request",
                    "body": bytes(body),
                    "more_body": False,
                }
            return await receive()

        await self.app(scope, replay_receive, send)

    @staticmethod
    async def _reject_oversized(send):
        body = b'{"detail":"Request body too large."}'
        await send({
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        })
        await send({"type": "http.response.body", "body": body})


class ChatConcurrencyMiddleware:
    """Bound simultaneous requests to the chat endpoint in this process."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        global _active_chat_requests

        if (
            scope.get("type") != "http"
            or scope.get("path") != "/api/ai-chat"
            or scope.get("method") != "POST"
        ):
            await self.app(scope, receive, send)
            return

        with _chat_concurrency_lock:
            overloaded = (
                _active_chat_requests >= MAX_CONCURRENT_CHAT_REQUESTS
            )
            if not overloaded:
                _active_chat_requests += 1

        if overloaded:
            await self._reject_busy(send)
            return

        try:
            await self.app(scope, receive, send)
        finally:
            with _chat_concurrency_lock:
                _active_chat_requests -= 1

    @staticmethod
    async def _reject_busy(send):
        body = b'{"detail":"AI assistant is busy. Please try again shortly."}'
        await send({
            "type": "http.response.start",
            "status": 503,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
                (
                    b"retry-after",
                    str(CONCURRENCY_RETRY_AFTER_SECONDS).encode("ascii"),
                ),
            ],
        })
        await send({"type": "http.response.body", "body": body})


app = FastAPI(title="BlueOrbit AI Assistant API")
app.add_middleware(
    RequestBodyLimitMiddleware,
    max_body_bytes=MAX_CHAT_REQUEST_BODY_BYTES,
)
app.add_middleware(ChatConcurrencyMiddleware)


RATE_LIMIT_MAX_REQUESTS = 20
RATE_LIMIT_WINDOW_SECONDS = 60.0
RATE_LIMIT_CLEANUP_INTERVAL_SECONDS = 60.0

_rate_limit_requests: dict[str, deque[float]] = defaultdict(deque)
_rate_limit_lock = Lock()
_last_rate_limit_cleanup = 0.0


def enforce_rate_limit(client_key: str) -> None:
    global _last_rate_limit_cleanup

    now = time.monotonic()
    cutoff = now - RATE_LIMIT_WINDOW_SECONDS

    with _rate_limit_lock:
        if now - _last_rate_limit_cleanup >= RATE_LIMIT_CLEANUP_INTERVAL_SECONDS:
            for existing_key, timestamps in list(_rate_limit_requests.items()):
                while timestamps and timestamps[0] <= cutoff:
                    timestamps.popleft()

                if not timestamps:
                    del _rate_limit_requests[existing_key]

            _last_rate_limit_cleanup = now

        requests = _rate_limit_requests[client_key]

        while requests and requests[0] <= cutoff:
            requests.popleft()

        if len(requests) >= RATE_LIMIT_MAX_REQUESTS:
            retry_after = max(
                1,
                int(RATE_LIMIT_WINDOW_SECONDS - (now - requests[0]))
            )
            raise HTTPException(
                status_code=429,
                detail="Too many requests. Please try again later.",
                headers={"Retry-After": str(retry_after)},
            )

        requests.append(now)



class ChatRateLimitMiddleware:
    """Apply per-client rate limits before request-body validation."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (
            scope.get("type") != "http"
            or scope.get("path") != "/api/ai-chat"
            or scope.get("method") != "POST"
        ):
            await self.app(scope, receive, send)
            return

        client = scope.get("client")
        client_key = (
            client[0]
            if isinstance(client, (tuple, list))
            and client
            and isinstance(client[0], str)
            else "unknown"
        )

        try:
            enforce_rate_limit(client_key)
        except HTTPException as exc:
            body = b'{"detail":"Too many requests. Please try again later."}'
            retry_after = (exc.headers or {}).get("Retry-After", "1")
            await send({
                "type": "http.response.start",
                "status": 429,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                    (b"retry-after", str(retry_after).encode("ascii")),
                ],
            })
            await send({"type": "http.response.body", "body": body})
            return

        await self.app(scope, receive, send)


# Register before CORS so CORS remains outermost and browser errors include
# the appropriate access-control headers.
app.add_middleware(ChatRateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN],
    allow_credentials=False,
    allow_methods=["POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sessionId: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=10000)

    @field_validator("sessionId", "message")
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Field must not be blank")
        return value


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/api/ai-chat")
async def ai_chat(payload: ChatRequest):
    payload = {
        "sessionId": payload.sessionId,
        "message": payload.message,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                N8N_WEBHOOK_URL,
                json=payload,
                headers={
                    "X-BlueOrbit-Chat-Secret": N8N_WEBHOOK_SECRET,
                },
            )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail="AI assistant service is unavailable.",
        ) from exc

    if response.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail="AI assistant request failed.",
        )

    try:
        return response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail="AI assistant returned an invalid response.",
        ) from exc
