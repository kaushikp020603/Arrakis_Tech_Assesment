"""Central settings for the RAG chatbot. Secrets come from .env (never hard-coded)."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

PDF_PATH = ROOT / "data" / "Meridian_Grid_Internal_Dossier.pdf"
DB_DIR = ROOT / "vector_db"
OUTPUT_DIR = ROOT / "outputs"
QUESTIONS_FILE = ROOT / "questions.md"
ANSWERS_JSON = OUTPUT_DIR / "answers.json"
CHUNKS_PREVIEW = OUTPUT_DIR / "chunks_preview.json"
COLLECTION = "meridian_dossier"

# Embeddings: all-MiniLM-L6-v2, L2-normalised so dot product == cosine similarity.
EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# Pages with no text layer (scans) are OCR'd with EasyOCR; every other page uses normal PyMuPDF extraction.
# Set USE_OCR=0 in .env to disable.
USE_OCR = os.getenv("USE_OCR", "1") == "1"

# Chunking (characters). Overlap is carried between consecutive text chunks of the same section.
CHUNK_SIZE = 700
CHUNK_OVERLAP = 120
TABLE_CHUNK_SIZE = 1100

# Hybrid retrieval: dense (cosine) + BM25 fused with weighted Reciprocal Rank Fusion.
CANDIDATES = 20     # candidates taken from each retriever before fusion
TOP_K = 7           # chunks given to the LLM
RRF_K = 60
W_DENSE = 1.0
W_BM25 = 1.0

# Generation (Groq).
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
MEMORY_TURNS = 6    # previous question/answer pairs kept in the conversation


def groq_key() -> str | None:
    key = os.getenv("GROQ_API_KEY", "").strip()
    return key if key and key != "your_groq_api_key_here" else None
