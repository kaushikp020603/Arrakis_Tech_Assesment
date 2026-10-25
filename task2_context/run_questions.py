"""COMMAND 2 - master command:   python run_questions.py     (or run_questions.bat)

Reads every question from questions.md, asks them one after another, and saves the questions and
answers, in order, to outputs/answers.json (rewritten after each question, so partial runs are kept).

Options:
  --questions FILE   other markdown file (default questions.md)
  --output FILE      other JSON file (default outputs/answers.json)
  --keep-memory      one continuous conversation for all questions (default: each question starts
                     with fresh memory, so answers are independent of the order)
  --reindex          rebuild the vector DB first
"""
import argparse
import datetime
import json
import re
import sys
from pathlib import Path

from rag import config
from rag.ingest import build_index


def read_questions(path: Path):
    """Numbered markdown items ('1. ...', '2) ...', '3 ...'); wrapped lines are joined."""
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\s*(?:[-*]\s*)?(\d+)[.)]?\s+(\S.*)$", line)
        if m:
            items.append([int(m.group(1)), m.group(2).strip()])
        elif items and line.strip() and not line.lstrip().startswith("#"):
            items[-1][1] += " " + line.strip()
    return items


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--questions", type=Path, default=config.QUESTIONS_FILE)
    ap.add_argument("--output", type=Path, default=config.ANSWERS_JSON)
    ap.add_argument("--keep-memory", action="store_true")
    ap.add_argument("--reindex", action="store_true")
    args = ap.parse_args()

    if not config.groq_key():
        sys.exit("GROQ_API_KEY is missing. Copy .env.example to .env and add your key (see README.md).")
    questions = read_questions(args.questions)
    if not questions:
        sys.exit(f"No numbered questions found in {args.questions}")

    print("Preparing knowledge base ...")
    build_index(force=args.reindex)
    from rag.chatbot import RAGChatbot

    bot = RAGChatbot()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    doc = {"generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
           "source_pdf": config.PDF_PATH.name, "llm": bot.model, "embedding_model": config.EMBED_MODEL,
           "retrieval": {"type": "hybrid: cosine (dense) + BM25, weighted RRF", "top_k": config.TOP_K,
                         "chunk_size": config.CHUNK_SIZE, "chunk_overlap": config.CHUNK_OVERLAP},
           "memory": "shared across questions" if args.keep_memory else "reset for every question",
           "results": []}
    for n, (qid, q) in enumerate(questions, start=1):
        if not args.keep_memory:
            bot.reset()
        print(f"\n[{n}/{len(questions)}] Q{qid}: {q}")
        try:
            res = bot.ask(q)
            entry = {"id": qid, "question": q, "answer": res["answer"],
                     "standalone_question": res["standalone_question"], "sources": res["sources"]}
            print(f"A: {res['answer']}")
        except Exception as e:
            entry = {"id": qid, "question": q, "answer": None, "error": f"{type(e).__name__}: {e}"}
            print(f"FAILED: {entry['error']}")
        doc["results"].append(entry)
        args.output.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nDone. {len(doc['results'])} answers saved to {args.output}")


if __name__ == "__main__":
    main()
