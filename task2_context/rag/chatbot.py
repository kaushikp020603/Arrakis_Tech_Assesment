"""RAG chatbot: conversation memory + query condensing + hybrid retrieval + Groq generation."""
from groq import Groq

from . import config
from .retriever import HybridRetriever

SYSTEM_PROMPT = """You are an analyst answering questions about the Meridian Grid Security internal dossier.

Rules:
- Use ONLY the numbered context excerpts supplied with the question. Never use outside knowledge.
- Some excerpts are table rows written as "Column: value; ..." and one is OCR text from a scanned page.
- Answer every part of a multi-part question. Be concise and direct, then give brief supporting detail.
- If a calculation is needed, list each input from the context, show the arithmetic step by step, and
  re-check the sums. Keep amounts in INR using the dossier's Indian digit grouping (e.g. 61,00,000).
- Cite sources like (Section 4, p5). If the context does not contain the answer, say so plainly instead of guessing.
- Use earlier turns of the conversation only to resolve references such as "he", "that incident", "it"."""

CONDENSE_PROMPT = """Given the conversation so far and a new user message, rewrite the new message as one
standalone question that can be understood without the conversation. Replace pronouns and vague references
with the specific names or values they refer to. If the message is already standalone, return it unchanged.
Output only the question."""


class MissingKeyError(RuntimeError):
    pass


class RAGChatbot:
    def __init__(self, retriever: HybridRetriever | None = None, model: str | None = None):
        key = config.groq_key()
        if not key:
            raise MissingKeyError(
                "GROQ_API_KEY is not set. Copy .env.example to .env and put your Groq key in it "
                "(see README.md).")
        self.client = Groq(api_key=key, max_retries=5)
        self.model = model or config.GROQ_MODEL
        self.retriever = retriever or HybridRetriever()
        self.history: list[dict] = []  # plain question/answer turns, without retrieved context

    def reset(self):
        self.history = []

    def _recent(self):
        return self.history[-2 * config.MEMORY_TURNS:]

    def _condense(self, question: str) -> str:
        if not self.history:
            return question
        convo = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in self._recent())
        r = self.client.chat.completions.create(
            model=self.model, temperature=0, max_tokens=800,
            messages=[{"role": "system", "content": CONDENSE_PROMPT},
                      {"role": "user", "content": f"Conversation:\n{convo}\n\nNew message: {question}"}])
        return (r.choices[0].message.content or question).strip()

    @staticmethod
    def _format_context(hits):
        blocks = []
        for n, h in enumerate(hits, start=1):
            blocks.append(f"[{n}] (Section: {h['section']}; page {h['page']})\n{h['text'].split(chr(10), 1)[-1]}")
        return "\n\n".join(blocks)

    def ask(self, question: str) -> dict:
        standalone = self._condense(question)
        hits = self.retriever.search(standalone)
        user_msg = f"Context excerpts:\n{self._format_context(hits)}\n\nQuestion: {question}"
        if standalone != question:
            user_msg += f"\n(Interpreted as: {standalone})"
        r = self.client.chat.completions.create(
            model=self.model, temperature=0, max_tokens=3000,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}, *self._recent(),
                      {"role": "user", "content": user_msg}])
        answer = (r.choices[0].message.content or "").strip()
        self.history += [{"role": "user", "content": question}, {"role": "assistant", "content": answer}]
        return {"question": question, "standalone_question": standalone, "answer": answer,
                "sources": [{k: h[k] for k in ("id", "section", "page", "kind", "cosine", "bm25", "rrf")}
                            for h in hits]}
