# Technical Assessment

Three tasks, one folder each. Every folder has its own README with full setup, run instructions and an explanation of
how it works, so any task can be run on its own.

| Folder | Task | README | Main command |
|---|---|---|---|
| `task1_scraping/` | Scrape fields from five live sites into JSON | [task1_scraping/README.md](task1_scraping/README.md) | `python live_scrape.py` |
| `task2_context/` | RAG chatbot that answers six questions about a PDF dossier | [task2_context/README.md](task2_context/README.md) | `run_questions.bat` or `start_chatbot.bat` |
| `task3_llm_security/` | Local Llama behind an API, four security problems shown and fixed | [task3_llm_security/README.md](task3_llm_security/README.md) | `python run_demo.py` |

Also in this folder:

- [PIPELINE.md](PIPELINE.md): how each task was approached, in the order the work was done
- [OVERVIEW.md](OVERVIEW.md): the methods used and the file structure of each folder
- [results.json](results.json): the results of all three tasks in one common format
- [Technical_Assessment_Report.pdf](Technical_Assessment_Report.pdf): the questions from the assessment and the output obtained

## Setup and run

### Task 1: scraping

Needs Windows, Python 3.10+ and Google Chrome (the scripts drive the installed Chrome).

```bash
pip install playwright beautifulsoup4 curl_cffi
cd task1_scraping
python live_scrape.py
```

Visits Indeed, Glassdoor, Zillow, G2 and StockX in one Chrome window and writes `output/<site>.json` and `result.json`.
Leave the window open until it prints `LIVE SCRAPING RUN COMPLETE`.

### Task 2: RAG chatbot

Needs Python 3.13, internet access for the first install, and a free Groq API key (https://console.groq.com/keys).

```bash
cd task2_context
setup.bat                  # creates .venv, installs packages, creates .env from .env.example
                           # open .env and put your key after GROQ_API_KEY=
run_questions.bat          # asks every question in questions.md -> outputs/answers.json
start_chatbot.bat          # interactive chat with memory
```

Without the `.bat` files (any system):

```bash
python -m venv .venv
.venv\Scripts\activate     # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env     # macOS/Linux: cp .env.example .env   (then add your Groq key)
python run_questions.py    # or: python chat.py
```

### Task 3: local LLM security

Needs Python 3.10+ and Ollama running with two models.

```bash
ollama pull llama3.2:1b    # the chatbot
ollama pull llama3.2:3b    # the guard that checks incoming prompts
cd task3_llm_security
pip install -r requirements.txt
python run_demo.py         # about 13 to 21 minutes on a CPU-only machine
```

Prints, for each of the four cases, every prompt, the response and a PASSED/FAILED judgement for the vulnerable
version and then for the hardened version, and writes `reports/security_report.json` and `.md`.

## What each task does, in short

**Task 1.** One script drives Chrome with Playwright and reads each site from the data the page itself publishes where
possible: Indeed's result cards, Glassdoor's JSON-LD reviews, Zillow's embedded listing data (fetched with `curl_cffi`),
G2's rating elements, StockX's JSON-LD price. Details, fallbacks and caveats are in the Task 1 README.

**Task 2.** PyMuPDF reads the PDF (tables rebuilt from word positions, the one scanned page read with EasyOCR). The text
is cut into overlapping chunks, embedded with `all-MiniLM-L6-v2` and stored in ChromaDB. For each question a cosine
search and a BM25 search are merged by rank fusion, and the best seven chunks go to a Groq model that answers from them.
The last six turns are kept as memory.

**Task 3.** The same FastAPI service is built twice in front of Ollama. The hardened one adds a body limit, HTTP Basic
authentication with hashed passwords and lockout, per-user rate limits, a cap on parallel model calls, a **semantic
guard** (a separate Llama call that judges what each incoming message is trying to do, with no keyword lists), generic
errors, and a check of every reply against the deployment's own secret.

## Results

| Task | Result |
|---|---|
| 1 | All five sites saved: Indeed 16 records, Glassdoor 3, Zillow 41, G2 15, StockX 1 |
| 2 | All six questions answered and checked against the PDF: INC-003 (Kabir Shah); CloudSentry API (INR 48,00,000); Vantage Retail Group (INR 6,75,000); Naina Kapoor, 2 years 4 months; INR 2,90,10,000; 15 March 2025 with CEO approval |
| 3 | 28 scenarios sent unchanged to both versions: 19 failed on the vulnerable one, 1 on the hardened one (a prompt asking the bot to start its reply with a chosen word, which the guard let through). The guard blocked 19 of 22 attacks and allowed 20 of 20 genuine questions on a held-out prompt set |

## Before sharing this folder

Remove `task2_context/.env` (it holds the Groq key), `task2_context/.venv/`, `task2_context/vector_db/` and
`task1_scraping/.profile/` (a Chrome profile the scrapers create). The scripts recreate all of them.
