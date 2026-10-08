import os
import time
from collections import defaultdict, deque
from threading import Lock

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
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

app = FastAPI(title="BlueOrbit AI Assistant API")


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
async def ai_chat(request: Request, payload: ChatRequest):
    client_ip = request.client.host if request.client else "unknown"
    enforce_rate_limit(client_ip)

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
