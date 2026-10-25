"""BEFORE: deliberately vulnerable wrapper around Ollama (port 8001). Never deploy this.

Flaws, by task category:
  1 Prompt injection      user text is pasted into the same prompt string as the system prompt
  2 No authentication     every endpoint is open, including /debug/config
  3 Resource exhaustion   no body/length/token limits, no rate limit, no timeout, no concurrency cap
  4 Context leakage       /debug/config returns the system prompt, API docs are exposed, user can pick
                          the model, and upstream errors are returned verbatim together with the prompt
"""
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .settings import MODEL, OLLAMA_URL, SYSTEM_PROMPT

app = FastAPI(title="Vulnerable LLM wrapper")  # FLAW 4: /docs and /openapi.json are public


@app.post("/chat")  # FLAW 2: no authentication
async def chat(request: Request):
    body = await request.json()  # FLAW 3: body of any size is read
    model = body.get("model", MODEL)  # FLAW 4: caller chooses the model
    # FLAW 1: instructions and untrusted user text share one string, so the user can override the rules
    prompt = f"{SYSTEM_PROMPT}\n\nUser: {body.get('message', '')}\nAssistant:"
    options = {"num_predict": body.get("max_tokens", -1)}  # FLAW 3: unlimited generation allowed
    try:
        async with httpx.AsyncClient(timeout=None) as client:  # FLAW 3: no timeout
            r = await client.post(f"{OLLAMA_URL}/api/generate",
                                  json={"model": model, "prompt": prompt, "stream": False, "options": options})
        if r.status_code != 200:
            # FLAW 4: raw upstream error + the full prompt (including the system prompt) go back to the caller
            return JSONResponse({"upstream_error": r.text, "model": model, "prompt_sent": prompt}, status_code=502)
        return {"reply": r.json().get("response", "")}
    except Exception as e:
        return JSONResponse({"error": repr(e), "ollama_url": OLLAMA_URL, "prompt_sent": prompt}, status_code=500)


@app.get("/debug/config")  # FLAW 2 + 4: unauthenticated, returns the system prompt
async def debug_config():
    return {"model": MODEL, "ollama_url": OLLAMA_URL, "system_prompt": SYSTEM_PROMPT}
