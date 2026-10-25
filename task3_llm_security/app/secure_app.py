"""AFTER: hardened wrapper around Ollama (port 8000).

Request pipeline (each step is a guardrail; the category it closes is in brackets):

  request -> BodyLimit [3] -> HTTP Basic auth + failed-login throttle [2] -> per-user rate limit [3]
          -> schema check: length / max_tokens / unknown fields [3,4]
          -> input normalisation [1]
          -> concurrency cap, load shedding [3]
          -> SEMANTIC GUARD: Llama reads the message against the chatbot's rules and answers ALLOWED / BLOCKED [1,4]
          -> Ollama /api/chat with separate system / user roles and a fixed model [1,4]
          -> output guard (canary / passcode / system-prompt fragments) [4]
          -> response

Everything unexpected returns a short generic error; details go to the server log only [4].
"""
import asyncio
import logging

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import settings
from .security import input_guard, output_guard, semantic_guard
from .security.body_limit import BodyLimit
from .security.rate_limit import rate_limited_user

logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("secure_app")

# No /docs, /redoc or /openapi.json: the API schema is not published.
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(BodyLimit, max_bytes=settings.MAX_BODY_BYTES)
_slots = asyncio.Semaphore(settings.MAX_CONCURRENCY)


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=settings.MAX_MESSAGE_CHARS)
    max_tokens: int = Field(default=settings.DEFAULT_MAX_TOKENS, ge=1, le=settings.MAX_TOKENS_CAP)
    model_config = {"extra": "forbid"}  # the caller cannot pass `model`, `options`, `system`, ...


# ---------------------------------------------------------------- generic, non-leaky errors
@app.exception_handler(StarletteHTTPException)
async def http_error(_: Request, exc: StarletteHTTPException):
    body = exc.detail if isinstance(exc.detail, dict) else {"detail": "Not found" if exc.status_code == 404 else "Error"}
    return JSONResponse(body, status_code=exc.status_code, headers=getattr(exc, "headers", None))


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, __: RequestValidationError):
    return JSONResponse({"detail": "Invalid request", "code": "E_INVALID"}, status_code=422)  # input is not echoed


@app.exception_handler(Exception)
async def unexpected_error(_: Request, exc: Exception):
    log.error("unhandled error: %r", exc)
    return JSONResponse({"detail": "Internal error", "code": "E_INTERNAL"}, status_code=500)


# ---------------------------------------------------------------- endpoints
@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/chat")
async def chat(body: ChatIn, user: str = Depends(rate_limited_user)):
    message = input_guard.normalize(body.message)

    if _slots.locked():  # all model slots busy: shed load instead of queueing without bound
        raise HTTPException(503, detail={"detail": "Server busy, retry shortly", "code": "E_BUSY"},
                            headers={"Retry-After": "5"})
    async with _slots:
        # Semantic check: is this message allowed under the chatbot's own rules? Fails closed.
        try:
            verdict = await semantic_guard.review(message)
        except semantic_guard.GuardError as e:
            log.error("semantic guard unavailable: %s", e)
            raise HTTPException(503, detail={"detail": "Policy check unavailable", "code": "E_GUARD"})
        if not verdict["allowed"]:
            log.warning("blocked by semantic guard: user=%s concerns=%s", user, verdict["concerns"])
            detail = {"detail": "Request rejected by the semantic policy check", "code": "E_POLICY"}
            if settings.GUARD_EXPLAIN:  # demo only
                detail["guard"] = {"decision": verdict["decision"], "concerns": verdict["concerns"],
                                   "answers": verdict["answers"]}
            raise HTTPException(400, detail=detail)

        payload = {
            "model": settings.MODEL,  # fixed server-side
            "stream": False,
            "messages": [
                {"role": "system", "content": settings.SYSTEM_PROMPT},  # developer instructions only
                {"role": "user", "content": message},                   # untrusted text, separate role
            ],
            "options": {"num_predict": body.max_tokens, "temperature": 0.3, "num_ctx": settings.NUM_CTX},
        }
        try:
            async with httpx.AsyncClient(timeout=settings.UPSTREAM_TIMEOUT) as client:
                r = await client.post(f"{settings.OLLAMA_URL}/api/chat", json=payload)
            r.raise_for_status()
            reply = r.json()["message"]["content"]
        except Exception as e:
            log.error("upstream failure: %r", e)
            raise HTTPException(502, detail={"detail": "Upstream model unavailable", "code": "E_UPSTREAM"})

    safe_reply, blocked = output_guard.filter_reply(reply)
    if blocked:
        log.warning("output guard blocked a reply containing protected content: user=%s", user)
    return {"reply": safe_reply}
