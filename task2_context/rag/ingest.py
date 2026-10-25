"""PDF -> clean text/tables -> overlapping, section-aware chunks -> embeddings -> ChromaDB.

Extraction uses PyMuPDF only:
  * normal text      page.get_text("blocks"), skipping repeated headers/footers
  * tables           page.find_tables(); every row is rewritten as "Column: value; ..." so each
                     row is self-contained (a bare table cell is useless to a retriever)
  * scanned pages    pages with (almost) no text layer are rendered to an image with PyMuPDF and
                     OCR'd with EasyOCR (all other pages use normal extraction)
"""
import json
import re
import sys

import fitz  # PyMuPDF

from . import config

BOILERPLATE = re.compile(r"^(Meridian Grid Security\W*Internal Dossier(\s+Page\s+\d+)?|Page\s+\d+)\s*$", re.I)
HEADING = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+[A-Z][^\n]{2,90}$")


# ----------------------------------------------------------------------------- extraction
def _clean(s: str) -> str:
    return re.sub(r"[ \t]+", " ", s.replace(" ", " ")).strip()


_OCR_READER = None


def _ocr_reader():
    global _OCR_READER
    if _OCR_READER is None:
        import easyocr

        _OCR_READER = easyocr.Reader(["en"], gpu=False, verbose=False)
    return _OCR_READER


def _ocr_page(page) -> str:
    """OCR one scanned page with EasyOCR. EasyOCR returns word boxes, so words are regrouped into lines
    (same vertical position) and ordered left to right."""
    import numpy as np

    pix = page.get_pixmap(dpi=300)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3]
    items = []
    for box, txt, _conf in _ocr_reader().readtext(img):
        ys, xs = [p[1] for p in box], [p[0] for p in box]
        items.append(((min(ys) + max(ys)) / 2, max(ys) - min(ys), min(xs), txt))
    items.sort()
    lines = []
    for yc, h, x, txt in items:
        if lines and abs(yc - lines[-1]["y"]) < 0.6 * h:
            lines[-1]["words"].append((x, txt))
        else:
            lines.append({"y": yc, "words": [(x, txt)]})
    text = [" ".join(t for _, t in sorted(l["words"])) for l in lines]
    text = [l for l in (_clean(x) for x in text) if l and not BOILERPLATE.match(l)]
    # A blank page only yields the running header; that is not content.
    return "\n".join(text) if sum(len(l) for l in text) >= 40 else ""


def _table_rows(table, words):
    """Rebuild a table from word positions. find_tables() only supplies the grid; the text of each cell is
    taken from words assigned by where the word STARTS, so text that overflows a cell edge stays whole
    (clipping by cell box would cut "pipelines" into "pipeli|nes")."""
    cols = sorted(c[0] for c in table.rows[0].cells if c)
    starts = [r.bbox[1] for r in table.rows]
    grid = [[[] for _ in cols] for _ in starts]
    for w in words:
        yc = (w[1] + w[3]) / 2
        # No right-edge limit: text that overflows the last column (e.g. "...(deployed Nov 2023)") still belongs to it.
        if not (starts[0] - 2 <= yc <= table.bbox[3] + 2 and w[0] >= table.bbox[0] - 2):
            continue
        r = max(i for i, y in enumerate(starts) if yc >= y - 2)
        c = max([i for i, x in enumerate(cols) if w[0] >= x - 2] or [0])
        grid[r][c].append(w)
    return [[" ".join(w[4] for w in sorted(cell, key=lambda w: (round(w[1] / 3), w[0]))) for cell in row]
            for row in grid]


def extract_elements(pdf_path):
    """Return a list of {page, y, kind, ...} in reading order."""
    doc = fitz.open(pdf_path)
    elements = []
    for pno, page in enumerate(doc, start=1):
        table_rects, page_elems = [], []
        words = page.get_text("words")
        try:
            tables = page.find_tables().tables
        except Exception:
            tables = []
        for t in tables:
            rows = [r for r in _table_rows(t, words) if any(r)]
            if len(rows) < 2:
                continue
            table_rects.append(fitz.Rect(t.bbox))
            page_elems.append({"page": pno, "y": t.bbox[1], "kind": "table", "rows": rows})
        for x0, y0, x1, y1, text, *_ in page.get_text("blocks"):
            if any(fitz.Rect(x0, y0, x1, y1).intersects(r) for r in table_rects):
                continue
            lines = [_clean(l) for l in text.split("\n")]
            lines = [l for l in lines if l and not BOILERPLATE.match(l)]
            if lines:
                page_elems.append({"page": pno, "y": y0, "kind": "text", "text": "\n".join(lines)})
        if (config.USE_OCR and not table_rects
                and sum(len(e.get("text", "")) for e in page_elems if e["kind"] == "text") < 80):
            ocr = _clean(_ocr_page(page))
            if ocr:
                print(f"  page {pno}: no text layer -> OCR ({len(ocr)} chars)")
                page_elems = [{"page": pno, "y": 0, "kind": "ocr", "text": ocr}]
        elements.extend(sorted(page_elems, key=lambda e: e["y"]))
    return elements


# ----------------------------------------------------------------------------- chunking
def split_text(text: str, size: int, overlap: int):
    """Greedy sentence packing with character overlap carried into the next chunk."""
    units = [u.strip() for u in re.split(r"(?<=[.!?])\s+|\n+", text) if u.strip()]
    chunks, cur = [], []
    cur_len = 0
    for u in units:
        if cur and cur_len + len(u) + 1 > size:
            chunks.append(" ".join(cur))
            keep, kept = [], 0
            for prev in reversed(cur):  # overlap: last sentences up to `overlap` chars
                if kept + len(prev) > overlap and keep:
                    break
                keep.insert(0, prev)
                kept += len(prev) + 1
            cur, cur_len = keep, kept
        cur.append(u)
        cur_len += len(u) + 1
    if cur and (not chunks or " ".join(cur) != chunks[-1]):
        chunks.append(" ".join(cur))
    return chunks


def table_chunks(rows, size):
    header, body = rows[0], rows[1:]
    lines = ["; ".join(f"{h}: {c}" for h, c in zip(header, r) if c) for r in body]
    chunks, cur = [], []
    for ln in lines:
        if cur and sum(len(x) + 1 for x in cur) + len(ln) > size:
            chunks.append("\n".join(cur))
            cur = []
        cur.append(ln)
    if cur:
        chunks.append("\n".join(cur))
    return chunks


def build_chunks(elements):
    """Text is buffered per (section, page) so a heading is never split from its body; tables and
    OCR pages are chunked on their own. Every chunk is prefixed with its section + page."""
    chunks = []
    state = {"section": "Front matter", "page": None, "lines": []}

    def emit(pieces, page, section, kind):
        for p in pieces:
            chunks.append({"text": f"[Section: {section} | Page {page} | {kind}]\n{p}",
                           "page": page, "section": section, "kind": kind})

    def flush():
        if state["lines"]:
            pieces = split_text("\n".join(state["lines"]), config.CHUNK_SIZE, config.CHUNK_OVERLAP)
            emit(pieces, state["page"], state["section"], "text")
        state["lines"] = []

    for el in elements:
        if state["page"] != el["page"]:
            flush()
            state["page"] = el["page"]
        if el["kind"] == "text":
            for line in el["text"].split("\n"):
                if HEADING.match(line):
                    flush()
                    state["section"] = line
                state["lines"].append(line)
        elif el["kind"] == "table":
            flush()
            emit(table_chunks(el["rows"], config.TABLE_CHUNK_SIZE), el["page"], state["section"], "table")
        else:  # ocr
            flush()
            sec = "Appendix B - Scanned Vendor Memo (OCR of page image)"
            emit(split_text(el["text"], config.CHUNK_SIZE, config.CHUNK_OVERLAP), el["page"], sec, "ocr")
    flush()
    for i, c in enumerate(chunks):
        c["id"] = f"chunk-{i:03d}"
    return chunks


# ----------------------------------------------------------------------------- indexing
def build_index(force: bool = False):
    import chromadb
    from sentence_transformers import SentenceTransformer

    config.DB_DIR.mkdir(exist_ok=True)
    config.OUTPUT_DIR.mkdir(exist_ok=True)
    client = chromadb.PersistentClient(path=str(config.DB_DIR))
    existing = [c.name for c in client.list_collections()]
    if config.COLLECTION in existing:
        if not force and client.get_collection(config.COLLECTION).count() > 0:
            return client.get_collection(config.COLLECTION).count()
        client.delete_collection(config.COLLECTION)

    print(f"Extracting {config.PDF_PATH.name} with PyMuPDF ...")
    chunks = build_chunks(extract_elements(config.PDF_PATH))
    print(f"Embedding {len(chunks)} chunks with {config.EMBED_MODEL} ...")
    model = SentenceTransformer(config.EMBED_MODEL)
    vecs = model.encode([c["text"] for c in chunks], normalize_embeddings=True, show_progress_bar=False)

    col = client.create_collection(config.COLLECTION, metadata={"hnsw:space": "cosine"})
    col.add(ids=[c["id"] for c in chunks], documents=[c["text"] for c in chunks],
            embeddings=vecs.tolist(),
            metadatas=[{"page": c["page"], "section": c["section"], "kind": c["kind"]} for c in chunks])
    config.CHUNKS_PREVIEW.write_text(json.dumps(chunks, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Indexed {col.count()} chunks into {config.DB_DIR.name}/ (cosine space).")
    return col.count()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    build_index(force="--force" in sys.argv)
