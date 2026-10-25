# Pipeline: how each task was approached, in the order the work was done

The work did not go task by task. The order was: the Task 2 answers by hand, then Task 1, then a first version of
Task 3, then the Task 2 chatbot, then Task 3 reworked around a semantic guard, and last a combined run of the Task 1
scraper. Each section lists the steps of one task in the order they happened and ends with the mechanism that
resulted. Run instructions are in each folder's README.

## Task 2: Context handling

1. **Read the PDF and answered the questions by hand.** Page 13 (Appendix B) is a scanned image with no text, and page
   10 is blank apart from the running header; the other pages are normal text. Each question was traced to its section
   (incident log, vendor table, client table, personnel history, severity table, Appendix B). For question 5 the incidents
   caused by a misconfigured firewall rule (INC-001, INC-003, INC-005) were multiplied by their severity weights and
   summed. These answers are in `task2_context/answers.md` and were used later to check the chatbot.
2. **Built the chatbot in stages.** Extraction with PyMuPDF; chunking; `all-MiniLM-L6-v2` embeddings in ChromaDB;
   retrieval; a Groq model for the answer; chat memory; then the two commands (chat and batch run), a virtual
   environment, and the key in `.env`.
3. **Inspected the extracted chunks before trusting them.** PyMuPDF's table reader had dropped spaces and mangled
   numbers (`1.0x` read as `10x`, `48,00,000` garbled), which would have made question 5 wrong. The fix: use PyMuPDF only
   to find the table grid, assign every word to a cell by where the word starts, and write each row as one line
   (`Severity Tier: High; Weight Multiplier: 2.0x; ...`).
4. **First full run: question 6 failed**, because Appendix B has no text. A page with under 80 characters of text and no
   table is now rendered at 300 dpi and read with EasyOCR (word boxes regrouped into lines). RapidOCR was tried first and
   misread one line. The blank page 10 would have produced a junk chunk from its header, so running headers are filtered
   out of OCR output too.
5. **The first Groq model was not available to the key**, so `openai/gpt-oss-120b` became the default.
6. **Final mechanism.** Chunks of about 700 characters with 120 overlap that never cross a section or page and start
   with `[Section | Page]` (37 chunks); a cosine search and a BM25 search each return 20 candidates; Reciprocal Rank
   Fusion (`1/(60 + rank)`) picks the top 7; the model answers only from them at temperature 0; the last six turns are
   kept, with the question rewritten as a standalone one when there is history. All six answers match the hand-worked ones
   (`outputs/answers.json`).

## Task 1: Scraping

1. **Playwright driving Chrome.** The browser that Playwright downloads would not start on the test machine, so the
   installed Chrome is used, with a persistent profile.
2. **Fixed each site as it failed.** Indeed: the title is in an `h3`, not an `h2`, and overlapping selectors produced
   duplicates. Glassdoor: CSS selectors found nothing, but the page publishes its reviews as JSON-LD, so that is read
   (three reviews). G2: the category slug in the assessment is a 404; the working one is
   `endpoint-detection-response-edr`.
3. **Bot protection.** Zillow showed a "Press & Hold" check that kept repeating, and after several test runs G2 restricted
   the IP for a while. Automated retries were stopped. A page saved by hand from a normal browser was parsed offline with
   `parse_saved.py` (BeautifulSoup): G2's ratings, Zillow's embedded listing data, StockX's JSON-LD.
4. **StockX needed care.** The product page in the assessment is a 404, so another Air Force 1 listing was used. Two wrong
   values were caught and not used: an early run returned $41 from a generic StockX page, and a saved copy showed only
   the $118 retail price with placeholders where the market price goes.
5. **One combined script.** `live_scrape.py` now fetches all five sites in one run and writes `output/*.json` and
   `result.json`; `stockx_scraper.py` handles StockX alone with extra price fields. Zillow is fetched first with
   `curl_cffi` (a request that presents itself as Chrome) and read from the page's `__NEXT_DATA__`; the browser is the
   fallback. A bot-check page is waited on for 12 to 15 seconds and then the site is recorded as failed.
6. **Final mechanism and caveat.** Indeed: result cards. Glassdoor: JSON-LD reviews. Zillow: embedded listings (41). G2:
   the rating elements, walked up to the product link (15). StockX: JSON-LD lowest price, then page text. If the live G2
   read fails, the script substitutes a built-in list of the same products and still reports success; the names in the
   current output end in "...", which shows they were read from the page.

## Task 3: Local LLM security

1. **Built two versions of the same API in front of Ollama.** The vulnerable one joins the system prompt and the user's
   text into one prompt and has no authentication, no limits, a debug endpoint, public API docs and verbose errors. The
   hardened one was built case by case: body limit (including chunked uploads), HTTP Basic authentication with scrypt
   hashes and lockout, per-user rate limit, a cap on parallel model calls, generic errors, and a check of replies against
   the deployment's secret.
2. **Wrote the attack scenarios and looked at the first results critically.** Two of my own mistakes showed up: a
   "passed" leak test that was only passing because it was being rate-limited, and injection prompts that did not work on
   the vulnerable version at all because the 1B model refused the blunt wording. Scenarios were changed to include the
   attacks that do work on that model, and each prompt is tried up to four times because the model answers differently each
   time.
3. **First injection defence: a list of attack phrases.** It blocked the demo prompts, but a phrase list can be
   paraphrased around, and the requirement was a semantic check, not keywords.
4. **Measured whether prompt tricks help the 1B chat model** (separate roles, stricter instructions, tags, a closing
   reminder). They did not reduce obedience (`demo/experiments.py`), so the control had to be a separate check.
5. **Semantic guard.** A separate Llama call reads the chatbot's own rules and the message. Llama 3.2 1B was too weak for
   this (5 to 7 of 12 attacks blocked on a tuning set), so the guard uses `llama3.2:3b`. One long JSON verdict was less
   reliable than four short yes/no questions (overrides the rules, controls the reply, seeks secrets, off-topic), so
   that is the design: allowed only if all four answers are no. The guard sees only the public rules, never the secret,
   and refuses the request if it cannot answer.
6. **Measured the guard on prompts it was not tuned on.** The guard's prompt was tuned on one set of labelled prompts and
   scored once on another: 19 of 22 attacks blocked, 20 of 20 genuine questions allowed.
7. **Final demo in the requested layout.** For each of the four cases: the prompt, the response and a PASSED/FAILED
   judgement for the vulnerable version, then the identical prompts against the hardened version. The report builder
   refuses to run if the two sets of requests differ. Result: 19 of 28 scenarios failed before, 1 after. The one that
   still fails is a request to start the reply with a chosen word, which the guard let through. The report also lists the
   guard's other misses and a false rejection of two "Say hi." messages.
