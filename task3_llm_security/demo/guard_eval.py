"""Measure the semantic guard on labelled prompts.

    python demo/guard_eval.py dev      # while tuning the guard prompt
    python demo/guard_eval.py test     # held-out set, run once tuning is finished; writes the evaluation report

Reports how many ATTACKS are blocked (want all) and how many LEGIT questions are wrongly blocked (want none).
"""
import datetime
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import settings  # noqa: E402
from app.security import input_guard, semantic_guard  # noqa: E402
from demo import guard_eval_data as data  # noqa: E402

OUT = settings.ROOT / "reports" / "semantic_guard_evaluation.json"


def run(attacks, legit):
    rows, t0 = [], time.time()
    for label, prompts in (("ATTACK", attacks), ("LEGIT", legit)):
        for p in prompts:
            v = semantic_guard.review_sync(input_guard.normalize(p))
            correct = (not v["allowed"]) if label == "ATTACK" else v["allowed"]
            rows.append({"label": label, "prompt": p, "decision": v["decision"], "reason": v["reason"],
                         "correct": correct})
    a = [r for r in rows if r["label"] == "ATTACK"]
    l = [r for r in rows if r["label"] == "LEGIT"]
    return rows, {"attacks_blocked": f"{sum(r['correct'] for r in a)}/{len(a)}",
                  "legit_allowed": f"{sum(r['correct'] for r in l)}/{len(l)}",
                  "seconds_per_check": round((time.time() - t0) / len(rows), 2)}


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "dev"
    attacks, legit = (data.DEV_ATTACKS, data.DEV_LEGIT) if which == "dev" else (data.TEST_ATTACKS, data.TEST_LEGIT)
    rows, summary = run(attacks, legit)
    print(f"[{which}] model={settings.GUARD_MODEL}  {summary}")
    for r in rows:
        if not r["correct"]:
            print(f"  WRONG ({r['label']} -> {r['decision']}): {r['prompt'][:90].encode('ascii', 'replace').decode()}"
                  f"\n        reason: {r['reason'][:110]}")
    if which == "test":
        OUT.parent.mkdir(exist_ok=True)
        OUT.write_text(json.dumps({
            "what": "Accuracy of the semantic guard on a held-out set of labelled prompts (written before tuning).",
            "model": settings.GUARD_MODEL, "measured_on": datetime.date.today().isoformat(), "summary": summary,
            "results": rows}, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
