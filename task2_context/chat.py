"""COMMAND 1 - switch the chatbot on:   python chat.py     (or start_chatbot.bat)

Interactive RAG chatbot over the Meridian Grid dossier. It remembers the conversation, so follow-ups
like "and how long did she hold that role?" work.

In-chat commands:  /sources  show/hide retrieved sources     /reset  forget the conversation
                   /history  print the conversation so far   /exit    quit
"""
import argparse
import sys

from rag import config
from rag.ingest import build_index


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reindex", action="store_true", help="re-extract the PDF and rebuild the vector DB")
    ap.add_argument("--sources", action="store_true", help="show retrieved sources under every answer")
    ap.add_argument("--model", default=None, help=f"Groq model (default {config.GROQ_MODEL})")
    args = ap.parse_args()

    if not config.groq_key():
        sys.exit("GROQ_API_KEY is missing. Copy .env.example to .env and add your key (see README.md).")

    print("Preparing knowledge base ...")
    build_index(force=args.reindex)

    from rag.chatbot import RAGChatbot  # imported late: loads the embedding model

    bot = RAGChatbot(model=args.model)
    show_sources = args.sources
    print(f"\nMeridian Grid dossier chatbot ready  (LLM: {bot.model}, embeddings: all-MiniLM-L6-v2, hybrid search).")
    print("Ask a question. Commands: /sources  /reset  /history  /exit\n")
    while True:
        try:
            q = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not q:
            continue
        if q.lower() in ("/exit", "/quit", "exit", "quit"):
            break
        if q == "/reset":
            bot.reset()
            print("Bot: memory cleared.\n")
            continue
        if q == "/sources":
            show_sources = not show_sources
            print(f"Bot: sources {'on' if show_sources else 'off'}.\n")
            continue
        if q == "/history":
            for m in bot.history:
                print(f"  {m['role']}: {m['content'][:200]}")
            print()
            continue
        try:
            res = bot.ask(q)
        except Exception as e:
            print(f"Bot: sorry, the request failed ({type(e).__name__}: {e})\n")
            continue
        if res["standalone_question"] != q:
            print(f"  (understood as: {res['standalone_question']})")
        print(f"Bot: {res['answer']}\n")
        if show_sources:
            for s in res["sources"]:
                print(f"  - p{s['page']} | {s['section']} | cos={s['cosine']} bm25={s['bm25']} rrf={s['rrf']}")
            print()


if __name__ == "__main__":
    main()
