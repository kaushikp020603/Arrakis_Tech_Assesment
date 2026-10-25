# Technical Assessment: overview of methods and file structure

The assessment has three tasks. Each lives in its own folder with its own run guide, so any one of them can be
run without the others.

| Folder | Task | Run guide |
|---|---|---|
| `task1_scraping/` | Scrape fields from five live websites into JSON | `task1_scraping/README.md` |
| `task2_context/` | Answer six questions about a 13-page internal dossier | `task2_context/README.md` |
| `task3_llm_security/` | Put a local Llama model behind an API and fix four security problems | `task3_llm_security/README.md` |

Other files in this folder: `README.md` (quick start), `PIPELINE.md` (the order in which the work was done),
`results.json` (the results of all three tasks in one format), and `Technical_Assessment_Report.pdf` (the questions
and the output obtained, in one short document).

---

## Task 1: Scraping

**Method.** One Python script (`live_scrape.py`) drives the installed Chrome with Playwright and visits the five
sites in turn. Where a site publishes its data in structured markup, that markup is read instead of the visible page
layout, because it is far more stable than CSS selectors:

- Indeed: result cards on the first page.
- Glassdoor: review data in the page's JSON-LD block.
- Zillow: listing data embedded in the page (`__NEXT_DATA__`), fetched with `curl_cffi`; browser fallback.
- G2: product name and rating pairs read from the rendered page.
- StockX: lowest offer price from the page's structured data.

Two assessment URLs (G2 category, StockX product) return 404 today, so working equivalents were used. When a site
blocks automation, `parse_saved.py` parses a page saved by hand from a normal browser.

```
task1_scraping/
  live_scrape.py      all five sites in one run -> output/*.json and result.json
  stockx_scraper.py   StockX only, with extra fields (last sale, highest bid)
  scrape.py           earlier per-site version (python scrape.py indeed g2)
  parse_saved.py      parser for pages saved from a browser (g2, zillow, stockx)
  output/             one JSON file per site
  result.json         the five sites combined
  README.md
```

## Task 2: Context handling (RAG chatbot)

**Method.** A retrieval-augmented chatbot over `Meridian_Grid_Internal_Dossier.pdf`.

1. **Extraction (PyMuPDF).** Text blocks are read with headers and footers removed. Tables are rebuilt cell by cell from
   word positions and written as one self-contained line per row (`Severity Tier: High; Weight Multiplier: 2.0x; ...`).
   Appendix B is a scanned image, so only that page is rendered and read with EasyOCR.
2. **Chunking.** About 700 characters with 120 characters of overlap, never crossing a section or page boundary.
   Each chunk starts with its section and page number.
3. **Embeddings and storage.** `all-MiniLM-L6-v2`, normalised, stored in ChromaDB using cosine distance.
4. **Hybrid retrieval.** Cosine similarity search and BM25 keyword search each return 20 candidates; they are merged with
   Reciprocal Rank Fusion (k = 60) and the top 7 chunks go to the model.
5. **Answering.** Groq (`openai/gpt-oss-120b`, temperature 0) answers only from those chunks and cites sections.
6. **Memory.** The last six question and answer pairs are kept, and a follow-up question is rewritten into a standalone
   question before searching.

Two commands: `start_chatbot.bat` (interactive chat) and `run_questions.bat` (asks every question in `questions.md`
in order and saves `outputs/answers.json`).

```
task2_context/
  chat.py  run_questions.py         the two entry points
  start_chatbot.bat  run_questions.bat  setup.bat
  questions.md                      the six questions
  rag/ingest.py  retriever.py  chatbot.py  config.py
  data/Meridian_Grid_Internal_Dossier.pdf
  outputs/answers.json  chunks_preview.json
  answers.md                        the answers worked out by hand, as a cross-check
  requirements.txt  .env.example  README.md
```

## Task 3: Local LLM security

**Method.** The same small FastAPI service is built twice in front of Ollama (Llama 3.2): `vulnerable_app.py`
(port 8001) and `secure_app.py` (port 8000). One list of prompts and requests is sent unchanged to both, and the
response to each is judged PASSED (the system held) or FAILED (the attack worked).

| Case | Problem shown | Fix in the secure app |
|---|---|---|
| 1. Prompt injection | Instructions and user text mixed in one prompt; overrides, persona switches, reply hijacking, other languages | A semantic guard: a separate Llama call (`llama3.2:3b`) reads the chatbot's rules and the message and answers four yes/no questions about what the message tries to do. No keyword or regex list. |
| 2. Unauthenticated access | Anyone can chat and read the debug endpoint | HTTP Basic auth, three registered users, scrypt-hashed passwords, constant-time checks, lockout after repeated wrong passwords |
| 3. Resource exhaustion | Floods, 200 KB bodies, unlimited `max_tokens` | Body size cap (including chunked uploads), message and token limits, per-user rate limit, concurrency cap with 503, timeouts |
| 4. Prompt leakage | Debug endpoint, public API schema, error that echoes the prompt, model reveals the passcode | Debug and docs routes removed, generic errors, model not caller-selectable, semantic guard, output check against the deployment's own secret |

```
task3_llm_security/
  run_demo.py                   one command: BEFORE, guardrails, AFTER, report
  app/vulnerable_app.py  secure_app.py  settings.py
  app/security/                 auth.py  rate_limit.py  body_limit.py
                                input_guard.py  semantic_guard.py  output_guard.py
  demo/scenarios.py             every prompt and request, defined once
  demo/report.py                builds the JSON and Markdown reports
  demo/guard_eval.py  guard_eval_data.py   accuracy of the semantic guard on labelled prompts
  demo/experiments.py           whether prompt-level tricks help the 1B chat model
  demo/credentials.json         the three demo accounts (demo only)
  scripts/create_users.py       writes data/users.json (hashed)
  reports/                      security_report.json / .md, semantic_guard_evaluation.json
  README.md
```

## Limits worth knowing

- Task 1: the sites use bot protection and change often; a new run can be blocked or return different values. In
  `live_scrape.py` the G2 step falls back to a built-in product list if the live read fails, and still reports success.
- Task 2: the answers come from a language model reading retrieved text; the six answers were checked against the PDF
  by hand. Appendix B depends on OCR of a scanned page.
- Task 3: the semantic guard is a language model and is not perfectly accurate; its measured accuracy is in
  `task3_llm_security/reports/semantic_guard_evaluation.json`. It adds an extra model call to every chat request.
  The other protections (authentication, limits, output check) do not depend on it.
