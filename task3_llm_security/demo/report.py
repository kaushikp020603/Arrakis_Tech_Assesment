"""Builds the report. Every case has the same layout:

    BEFORE   the exact prompts/requests sent to the vulnerable app, what came back, PASSED / FAILED
    GUARDRAILS   exactly what was added, and where
    AFTER    the SAME prompts/requests sent to the hardened app, what came back, PASSED / FAILED

PASSED = the system withstood the attack (or served a legitimate request); FAILED = the attack worked.
Written as reports/security_report.json and reports/security_report.md (same content).
"""
import datetime
import json
import platform

from app import settings

CASE_INFO = {
    1: {
        "name": "Prompt injection",
        "what_it_is": "Text typed by the user overrides the developer's instructions, so the bot does what the attacker says "
                      "or goes outside its job.",
        "why_vulnerable": [
            "vulnerable_app.py pastes SYSTEM_PROMPT and the user's text into ONE prompt string, so the model cannot tell "
            "instructions from data.",
            "Nothing checks what the user's message is trying to do.",
            "The model is not deterministic, so each prompt is tried up to 4 times and the report says how often it worked.",
        ],
        "guardrails": [
            {"control": "Semantic guard (the main control)", "what_we_did": "Before the chat model sees a message, a separate Llama "
             "call reads the chatbot's own rules together with the message and answers, in a fixed JSON format, four yes/no "
             "questions about its MEANING (does it override the rules or give a new role? dictate or control the reply? ask "
             "for instructions or secrets? is it unrelated to Acme?) and then ALLOWED or BLOCKED. BLOCKED requests get HTTP "
             "400 and never reach the chat model. There is no keyword or regex list anywhere: paraphrases, other languages "
             "and obfuscated spellings are judged on what they mean.",
             "file": "app/security/semantic_guard.py"},
            {"control": "The guard cannot be talked into leaking", "what_we_did": "The guard sees only the public rules, never the "
             "confidential note; the user text is delimited and treated as data; output is forced into a JSON schema with an "
             "ALLOWED/BLOCKED enum at temperature 0; if the guard cannot answer, the request is refused (fails closed).",
             "file": "app/security/semantic_guard.py"},
            {"control": "Input canonicalisation", "what_we_did": "Unicode NFKC folding and removal of control / zero-width "
             "characters, so the guard sees obfuscated text as a human reads it. No words are matched.",
             "file": "app/security/input_guard.py: normalize()"},
            {"control": "Role separation, fixed model", "what_we_did": "System instructions and user text go as separate "
             "`system` / `user` messages to /api/chat; model and parameters are fixed by the server; unknown request fields "
             "are rejected.", "file": "app/secure_app.py"},
        ],
    },
    2: {
        "name": "Unauthenticated endpoint access",
        "what_it_is": "Anyone who can reach the port can use the chatbot and internal endpoints.",
        "why_vulnerable": [
            "No authentication on any endpoint, including /debug/config.",
            "Credentials, if sent, are simply ignored, so a wrong password is as good as a right one.",
            "Nothing limits repeated password guessing.",
        ],
        "guardrails": [
            {"control": "HTTP Basic authentication", "what_we_did": "Every endpoint except /health needs a registered username "
             "and password (3 users: alice, bob, carol). Failures return 401 with a WWW-Authenticate header.",
             "file": "app/security/auth.py: current_user()"},
            {"control": "Hashed credentials", "what_we_did": "Passwords exist only as salted scrypt hashes in data/users.json "
             "(created by scripts/create_users.py).", "file": "app/security/auth.py: hash_password() / verify_password()"},
            {"control": "Constant-time checks", "what_we_did": "hmac.compare_digest, and unknown usernames are checked against a "
             "dummy hash so timing does not reveal which usernames exist.", "file": "app/security/auth.py"},
            {"control": "Brute-force lockout", "what_we_did": f"After {settings.MAX_FAILS_PER_USER_IP} wrong passwords for the "
             f"same (IP, username) in a minute the server answers 429 even for the right password; a per-IP cap of "
             f"{settings.MAX_FAILS_PER_IP} failures stops username spraying.", "file": "app/security/auth.py"},
            {"control": "Debug surface removed", "what_we_did": "/debug/config does not exist.", "file": "app/secure_app.py"},
            {"control": "Ollama not exposed", "what_we_did": "Ollama listens on 127.0.0.1 only, so the wrapper is the only way in.",
             "file": "deployment (Ollama default)"},
        ],
    },
    3: {
        "name": "Rate limiting / resource exhaustion",
        "what_it_is": "A caller can make the server, and the model behind it, do unbounded work and starve other users.",
        "why_vulnerable": [
            "Request bodies of any size are read and sent to the model.",
            "The caller controls max_tokens, including unlimited generation.",
            "No rate limit, no cap on simultaneous model calls, no timeout.",
        ],
        "guardrails": [
            {"control": "Body size cap", "what_we_did": f"Bodies above {settings.MAX_BODY_BYTES} bytes get 413, including chunked "
             "uploads that send no Content-Length header.", "file": "app/security/body_limit.py"},
            {"control": "Schema limits", "what_we_did": f"message <= {settings.MAX_MESSAGE_CHARS} characters, max_tokens <= "
             f"{settings.MAX_TOKENS_CAP}; larger values are rejected (422).", "file": "app/secure_app.py: ChatIn"},
            {"control": "Per-user rate limit", "what_we_did": f"Sliding window of {settings.RATE_LIMIT_PER_MIN} requests per minute "
             "per authenticated user, then 429 with Retry-After.", "file": "app/security/rate_limit.py"},
            {"control": "Concurrency cap + load shedding", "what_we_did": f"At most {settings.MAX_CONCURRENCY} requests use the "
             "model at once; extra requests get an immediate 503 instead of queueing without bound.",
             "file": "app/secure_app.py"},
            {"control": "Timeouts and fixed context", "what_we_did": f"{settings.UPSTREAM_TIMEOUT:.0f} s upstream timeout, "
             f"num_ctx fixed at {settings.NUM_CTX}, no streaming.", "file": "app/secure_app.py"},
        ],
    },
    4: {
        "name": "Context / system prompt leakage",
        "what_it_is": "The system prompt or other hidden context (here a marker and an escalation passcode) is exposed through "
                      "endpoints, errors or the model's own answers.",
        "why_vulnerable": [
            "/debug/config returns the system prompt.",
            "The API docs / schema are public.",
            "Upstream errors are returned verbatim with the full prompt, and the caller can choose the model.",
            "Nothing checks what the model says before it is returned.",
        ],
        "guardrails": [
            {"control": "No debug or docs endpoints", "what_we_did": "/debug/*, /docs, /redoc and /openapi.json are removed.",
             "file": "app/secure_app.py"},
            {"control": "Generic errors", "what_we_did": "Validation, upstream and unexpected errors return a short code "
             "(E_INVALID, E_UPSTREAM, E_INTERNAL); details go to the server log only; invalid input is never echoed.",
             "file": "app/secure_app.py: exception handlers"},
            {"control": "Model not caller-controlled", "what_we_did": "A request that includes `model` (or any unknown field) is "
             "rejected.", "file": "app/secure_app.py: ChatIn (extra=forbid)"},
            {"control": "Semantic guard", "what_we_did": "Requests that try to extract the instructions, notes or codes are "
             "judged by meaning and blocked before reaching the chat model (same guard as case 1).",
             "file": "app/security/semantic_guard.py"},
            {"control": "Output guard (safety net)", "what_we_did": "Every model reply is compared with this deployment's own "
             "protected strings (the confidential note, the passcode and each sentence of the system prompt) after normalising; "
             "a match is replaced by a fixed refusal. This checks for the deployment's own secret, it is not a keyword "
             "classifier of user prompts.", "file": "app/security/output_guard.py"},
        ],
    },
}

KNOWN_LIMITS = {
    1: "The guard is a language model, so it can be wrong in both directions: see semantic_guard_evaluation for measured "
       "numbers on prompts it was not tuned on. It adds one extra model call to every request.",
    2: "HTTP Basic over plain HTTP is only acceptable on localhost; use TLS in production.",
    3: "Limits are in memory per process; with several workers use a shared store such as Redis.",
    4: "The output guard catches verbatim or lightly reformatted leaks, not a deliberately paraphrased one. Real secrets should "
       "never be placed in a system prompt; the passcode here is bait for the test.",
}


def _count(scenarios):
    return {"passed": sum(s["judgement"]["result"] == "PASSED" for s in scenarios),
            "failed": sum(s["judgement"]["result"] == "FAILED" for s in scenarios), "total": len(scenarios)}


def _side(s):
    return {"response": s["response"], "judgement": s["judgement"]}


def _load(name):
    f = settings.ROOT / "reports" / name
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {"note": "not generated yet"}


def build(before, after, started, finished):
    cases = []
    for cid, info in CASE_INFO.items():
        b, a = before[cid], after[cid]
        assert [s["id"] for s in b] == [s["id"] for s in a], "BEFORE and AFTER must contain the same scenarios"
        assert all(x["request"] == y["request"] for x, y in zip(b, a)), "BEFORE and AFTER requests must be identical"
        cases.append({
            "case": cid, "name": info["name"], "what_it_is": info["what_it_is"],
            "before": {"target": "app/vulnerable_app.py on :8001", "why_vulnerable": info["why_vulnerable"],
                       "summary": _count(b), "scenarios": b},
            "guardrails_applied": info["guardrails"],
            "after": {"target": "app/secure_app.py on :8000", "summary": _count(a), "scenarios": a},
            "side_by_side": [{"id": x["id"], "title": x["title"], "request": x["request"],
                              "before": _side(x), "after": _side(y)} for x, y in zip(b, a)],
            "known_limits": KNOWN_LIMITS[cid],
        })
    tb = sum(c["before"]["summary"]["failed"] for c in cases)
    ta = sum(c["after"]["summary"]["failed"] for c in cases)
    n = sum(c["before"]["summary"]["total"] for c in cases)
    return {
        "report": "Local LLM (Ollama / Llama) behind a Python API: security BEFORE vs AFTER",
        "legend": {"PASSED": "the system withstood the attack, or served a legitimate request correctly",
                   "FAILED": "the attack worked, or a legitimate request was refused"},
        "meta": {"generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
                 "run_time_seconds": round(finished - started, 1), "chat_model": settings.MODEL,
                 "guard_model": settings.GUARD_MODEL, "python": platform.python_version(),
                 "demo_accounts": "alice, bob, carol (passwords in demo/credentials.json; stored hashed in data/users.json)",
                 "note": "Every scenario is sent identically to both apps; only the server differs."},
        "summary": {
            "before": f"{tb} of {n} scenarios FAILED on the vulnerable app",
            "after": f"{ta} of {n} scenarios FAILED on the hardened app",
            "per_case": [{"case": c["case"], "name": c["name"], "before": c["before"]["summary"],
                          "after": c["after"]["summary"]} for c in cases]},
        "cases": cases,
        "semantic_guard_evaluation": _load("semantic_guard_evaluation.json"),
    }


def _fmt_req(r):
    body = r["body"]
    return f"{r['method']} {r['path']}  as {r['credentials']}" + (f"\n    {json.dumps(body, ensure_ascii=False)}" if body else "")


def to_markdown(rep):
    L = [f"# {rep['report']}", "", f"**{rep['summary']['before']}**  ->  **{rep['summary']['after']}**", "",
         f"PASSED = {rep['legend']['PASSED']}.  FAILED = {rep['legend']['FAILED']}.", ""]
    for c in rep["cases"]:
        L += [f"## Case {c['case']}: {c['name']}", "", c["what_it_is"], ""]
        for phase, title in (("before", "BEFORE (vulnerable app)"), ("after", "AFTER (hardened app, same requests)")):
            if phase == "after":
                L += ["### Guardrails applied", ""] + [f"- **{g['control']}**: {g['what_we_did']} (`{g['file']}`)"
                                                       for g in c["guardrails_applied"]] + [""]
            s = c[phase]["summary"]
            L += [f"### {title}: {s['passed']} passed, {s['failed']} failed", ""]
            for sc in c[phase]["scenarios"]:
                L += [f"**{sc['id']} {sc['title']}**", "", "```", "REQUEST : " + _fmt_req(sc["request"]),
                      f"RESPONSE: HTTP {sc['response']['http_status']} ({sc['response']['seconds']} s) "
                      f"{sc['response']['body']!r}", f"JUDGEMENT: {sc['judgement']['result']} - {sc['judgement']['reason']}",
                      "```", ""]
        L += [f"_Limits: {c['known_limits']}_", ""]
    return "\n".join(L)
