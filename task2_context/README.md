# Task 2: Context handling (RAG chatbot over the Meridian Grid dossier)

A chatbot that answers questions about `data/Meridian_Grid_Internal_Dossier.pdf`. It reads the PDF, stores it as
searchable chunks, finds the relevant ones for each question, and has a Groq-hosted model answer from them. It
remembers the conversation.

There are two commands:

- `start_chatbot.bat` (or `python chat.py`): an interactive chat
- `run_questions.bat` (or `python run_questions.py`): asks every question in `questions.md` in order and saves the
  questions and answers to `outputs/answers.json`

## Setup (once)

You need Python 3.13 (the tested version), internet access for the first install, and a Groq API key
(free at https://console.groq.com/keys).

On Windows, from this folder:

```bash
setup.bat
```

This creates the virtual environment `.venv\`, installs `requirements.txt`, and creates `.env` from `.env.example`.
On another system, do the same by hand:

```bash
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env          # macOS/Linux: cp .env.example .env
```

Then open `.env` and put the key after `GROQ_API_KEY=`:

```
GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxx
```

The key is read only from `.env` (git-ignored) and is never written into the code. The first run also downloads the
embedding model (about 90 MB) and the EasyOCR models.

## Run

**Interactive chat**

```bash
start_chatbot.bat               # or: .venv\Scripts\python.exe chat.py
```

The first start reads the PDF and builds the vector database in `vector_db\`; later starts reuse it.

```
You: Which incident had the highest reconciled cost?
Bot: INC-003 ... on-call engineer Kabir Shah ...
You: And how much was it in INR?            <- a follow-up; memory resolves "it"
```

| In-chat command | Effect |
|---|---|
| `/sources` | show or hide the retrieved chunks (page, section, cosine, BM25, fused score) under each answer |
| `/history` | print the conversation so far |
| `/reset` | forget the conversation |
| `/exit` | quit |

Options: `--reindex` rebuilds the vector database from the PDF, `--sources` starts with sources shown, `--model NAME`
picks another Groq model.

**All questions from the markdown file**

```bash
run_questions.bat               # or: .venv\Scripts\python.exe run_questions.py
```

It reads each numbered item in `questions.md` (`1.`, `2.` ...), asks them one after another, and rewrites
`outputs/answers.json` after every question, so a partial run is kept:

```json
{
  "generated_at": "...", "llm": "...", "embedding_model": "...", "memory": "reset for every question",
  "results": [
    { "id": 1, "question": "...", "answer": "...", "standalone_question": "...",
      "sources": [ { "section": "...", "page": 5, "cosine": 0.61, "bm25": 7.2, "rrf": 0.032 } ] }
  ]
}
```

To change the questions, edit `questions.md` and keep the `N.` numbering. Each question starts with empty memory so
that an answer does not depend on the order; `--keep-memory` runs them as one conversation instead. Other options:
`--questions FILE`, `--output FILE`, `--reindex`. The `answer` text is exactly what the model returned, including
its citation markers.

## How it works

```
PDF -> PyMuPDF text + tables (EasyOCR for the scanned page) -> overlapping chunks
    -> all-MiniLM-L6-v2 embeddings -> ChromaDB (cosine)

question (+ chat memory) -> standalone question
    -> cosine search (ChromaDB)   \
    -> BM25 keyword search         >- Reciprocal Rank Fusion -> top 7 chunks -> Groq model -> answer
```

**1. Extraction (`rag/ingest.py`).** PyMuPDF reads each page.
- Running headers and footers ("Meridian Grid Security - Internal Dossier", "Page N") are dropped.
- Tables: PyMuPDF finds the table grid, but its own cell text lost spaces and mangled numbers (for example `1.0x` came out
  as `10x`). So every word on the page is assigned to a cell by where the word starts, and each row is written as one
  line: `Severity Tier: High; Weight Multiplier: 2.0x; Definition: ...`.
- A page with fewer than 80 characters of text and no table is treated as scanned: it is rendered at 300 dpi and read
  with EasyOCR, whose word boxes are regrouped into lines. A blank page that only has the running header gives nothing.
  In this PDF that is page 13 (Appendix B). OCR can be switched off with `USE_OCR=0` in `.env`.

**2. Chunking.** Text is collected per section and page (a heading line starts a new section), then packed sentence by
sentence into chunks of about 700 characters, each overlapping the previous by up to 120 characters. Table rows are
grouped into chunks of up to 1,100 characters. A chunk never crosses a section or page and starts with
`[Section: ... | Page N | text/table/ocr]`. The 37 chunks that were indexed are listed in `outputs/chunks_preview.json`.

**3. Embeddings and storage.** `all-MiniLM-L6-v2` vectors, normalised so that dot product equals cosine similarity,
stored in a persistent ChromaDB collection created with cosine distance.

**4. Hybrid retrieval (`rag/retriever.py`).** Two searches run for every question:
- cosine similarity in ChromaDB: the 20 nearest chunks, which catches paraphrases;
- BM25 over the same chunks (lower-case words and numbers, small stop-word list): the 20 best, which catches exact
  tokens such as `INC-003` or `SentinelWatch`.

They are merged with Reciprocal Rank Fusion: each chunk scores `1/(60 + rank)` from each search it appears in, and the
seven highest totals go to the model. Because it uses ranks, the two score scales never have to be compared.

**5. Answering (`rag/chatbot.py`).** The seven chunks are numbered with their section and page and sent with the
question to a Groq model (default `openai/gpt-oss-120b`, temperature 0). The system prompt says to use only those
excerpts, answer every part of the question, show arithmetic step by step, keep amounts in INR in Indian digit
grouping, and say so when the answer is not in the excerpts.

**6. Memory.** The last six question and answer pairs are sent with each request. When there is history, a short extra
call first rewrites the new question as a standalone one (replacing "he", "that incident" and similar), and that
rewritten question is what the search uses.

## The six questions and their answers

| # | Question | Answer |
|---|---|---|
| 1 | Highest reconciled cost, and the on-call engineer | INC-003, INR 61,00,000; Kabir Shah |
| 2 | Vendor flagged in the Q3 audit and its annual cost | CloudSentry API; INR 48,00,000 |
| 3 | Client that received the Firewall Rule Auto-Validator v2, and its monthly revenue | Vantage Retail Group; INR 6,75,000 |
| 4 | Head of Security in the founding year, and tenure | Naina Kapoor; April 2019 to August 2021, 2 years 4 months |
| 5 | Severity-weighted cost of "misconfigured firewall rule" incidents | INR 2,90,10,000 (INC-001 45,00,000 + INC-003 2,44,00,000 + INC-005 1,10,000) |
| 6 | SentinelWatch SIEM renewal date and approver (Appendix B) | 15 March 2025; the CEO must sign off |

`answers.md` holds the same answers worked out by hand from the PDF; the chatbot's output was checked against it.

## Files

```
task2_context/
  chat.py                    command 1: interactive chatbot
  run_questions.py           command 2: questions.md -> outputs/answers.json
  start_chatbot.bat  run_questions.bat  setup.bat
  questions.md               the six questions
  rag/
    config.py                all settings: chunk sizes, top-k, models, memory length
    ingest.py                extraction, OCR, chunking, embeddings, ChromaDB
    retriever.py             cosine + BM25 + rank fusion
    chatbot.py               memory, question rewriting, prompts, Groq call
  data/Meridian_Grid_Internal_Dossier.pdf
  outputs/answers.json  chunks_preview.json
  answers.md                 hand-worked answers, used as a cross-check
  requirements.txt  .env.example  README.md
```

## Troubleshooting

- **"GROQ_API_KEY is missing"**: edit `.env` as in Setup.
- **Odd answers after changing settings**: run with `--reindex`.
- **Groq says the model does not exist or you have no access**: the default model is not enabled for your key. Set
  `GROQ_MODEL` in `.env` to one your key can use.
- **Rate-limit errors**: the client retries automatically; on the free tier wait a minute and run again.
