"""ONE COMMAND:  python run_demo.py

For each of the 4 cases, in this order:
  BEFORE  - the vulnerable app (port 8001) is sent the prompts/requests; every prompt, the response and a
            PASSED / FAILED judgement are shown
  AFTER   - the guardrails are applied (hardened app, port 8000) and the SAME prompts/requests are sent again,
            with the same layout

Writes reports/security_report.json and reports/security_report.md.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app import settings  # noqa: E402
from demo import report, scenarios  # noqa: E402

REPORTS = ROOT / "reports"
BEFORE_PORT, AFTER_PORT = 8001, 8000
BAR = "=" * 100


def log(msg=""):
    print(msg, flush=True)


def check_ollama():
    try:
        tags = httpx.get(f"{settings.OLLAMA_URL}/api/tags", timeout=5).json()
    except Exception:
        sys.exit(f"Ollama is not reachable at {settings.OLLAMA_URL}. Start it (ollama serve) and re-run.")
    names = [m["name"] for m in tags.get("models", [])]
    for m in {settings.MODEL, settings.GUARD_MODEL}:
        if m not in names:
            sys.exit(f"Model '{m}' is not installed. Run: ollama pull {m}   (installed: {names})")
    log(f"Ollama OK. Chat model: {settings.MODEL}   Guard model: {settings.GUARD_MODEL}")
    log("Loading both models into memory (first call is slow) ...")
    for m in {settings.MODEL, settings.GUARD_MODEL}:
        httpx.post(f"{settings.OLLAMA_URL}/api/generate", timeout=600,
                   json={"model": m, "prompt": "hi", "stream": False, "options": {"num_predict": 1}})


def ensure_users():
    if not settings.USERS_FILE.exists():
        subprocess.run([sys.executable, str(ROOT / "scripts" / "create_users.py")], check=True)
    creds = json.loads(settings.CREDENTIALS_FILE.read_text(encoding="utf-8"))
    return {u["name"]: u["password"] for u in creds["valid_users"]}


def start(module, port, env_extra=None):
    try:
        httpx.get(f"http://127.0.0.1:{port}/health", timeout=1)
        sys.exit(f"Port {port} is already in use. Stop whatever is running there and re-run.")
    except httpx.TransportError:
        pass
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", module, "--host", "127.0.0.1", "--port", str(port),
                             "--log-level", "error"], cwd=ROOT, env={**os.environ, **(env_extra or {})})
    for _ in range(60):
        try:
            httpx.get(f"http://127.0.0.1:{port}/health", timeout=1)
            return proc
        except httpx.TransportError:
            time.sleep(0.5)
    proc.kill()
    sys.exit(f"{module} did not start on port {port}")


def stop(proc):
    proc.terminate()
    try:
        proc.wait(10)
    except subprocess.TimeoutExpired:
        proc.kill()


def run_phase(label, port, creds, env_extra=None):
    log(f"\nRunning {label} scenarios (heavy resource tests run last so they do not disturb the others) ...")
    module = "app.vulnerable_app:app" if label == "BEFORE" else "app.secure_app:app"
    proc = start(module, port, env_extra)
    ctx = scenarios.Ctx(f"http://127.0.0.1:{port}", creds)
    results = {}
    try:
        for cid in (1, 2, 4, 3):
            t0 = time.time()
            results[cid] = scenarios.CASES[cid](ctx)
            log(f"  case {cid} done ({time.time() - t0:.0f} s)")
    finally:
        stop(proc)
    return results


def show_phase(label, results):
    log(f"\n{BAR}\n{label}\n{BAR}")
    for cid in (1, 2, 3, 4):
        info = report.CASE_INFO[cid]
        log(f"\nCASE {cid}: {info['name'].upper()}\n{'-' * 100}")
        for s in results[cid]:
            r = s["request"]
            log(f"[{s['id']}] {s['title']}")
            log(f"   REQUEST  : {r['method']} {r['path']}  as {r['credentials']}")
            if r["body"]:
                log(f"   PROMPT   : {json.dumps(r['body'], ensure_ascii=False)}")
            resp = s["response"]
            log(f"   RESPONSE : HTTP {resp['http_status']} in {resp['seconds']} s  {resp['body'][:300]!r}")
            log(f"   JUDGEMENT: {s['judgement']['result']} - {s['judgement']['reason']}\n")
        c = report._count(results[cid])
        log(f"   => case {cid}: {c['passed']} PASSED, {c['failed']} FAILED of {c['total']}")


def main():
    started = time.time()
    check_ollama()
    creds = ensure_users()
    log(f"Demo accounts: {', '.join(creds)}  (other credentials tried: mallory, and alice with a wrong password)")

    before = run_phase("BEFORE", BEFORE_PORT, creds)
    show_phase("BEFORE: vulnerable app (no guardrails)", before)
    time.sleep(3)  # let Ollama drop any generation the vulnerable app left running

    log(f"\n{BAR}\nGUARDRAILS APPLIED (details per case in the report). Same prompts, hardened app.\n{BAR}")
    after = run_phase("AFTER", AFTER_PORT, creds, env_extra={"GUARD_EXPLAIN": "1"})
    show_phase("AFTER: hardened app (same prompts and requests)", after)

    rep = report.build(before, after, started, time.time())
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "security_report.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
    (REPORTS / "security_report.md").write_text(report.to_markdown(rep), encoding="utf-8")

    log(f"\n{BAR}\nSUMMARY\n{BAR}")
    log(f"  BEFORE: {rep['summary']['before']}")
    log(f"  AFTER : {rep['summary']['after']}")
    for c in rep["summary"]["per_case"]:
        log(f"  case {c['case']} {c['name']:<38} before {c['before']['failed']:>2} failed -> after {c['after']['failed']:>2} failed")
    log(f"\nReports written to {REPORTS / 'security_report.json'} and security_report.md")


if __name__ == "__main__":
    main()
