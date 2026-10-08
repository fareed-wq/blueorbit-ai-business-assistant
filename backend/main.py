import os

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

load_dotenv()

N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL")
N8N_WEBHOOK_SECRET = os.getenv("N8N_WEBHOOK_SECRET")
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")

if not N8N_WEBHOOK_URL:
    raise RuntimeError("N8N_WEBHOOK_URL is not configured")

if not N8N_WEBHOOK_SECRET:
    raise RuntimeError("N8N_WEBHOOK_SECRET is not configured")

app = FastAPI(title="BlueOrbit AI Assistant API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN],
    allow_credentials=False,
    allow_methods=["POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


class ChatRequest(BaseModel):
    sessionId: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=10000)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/api/ai-chat")
async def ai_chat(request: ChatRequest):
    payload = {
        "sessionId": request.sessionId,
        "message": request.message,
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
