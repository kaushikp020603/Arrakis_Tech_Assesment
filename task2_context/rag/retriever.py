"""Hybrid retriever: dense cosine search (all-MiniLM-L6-v2 in ChromaDB) + BM25 keyword search,
combined with weighted Reciprocal Rank Fusion.

Why both: dense vectors catch paraphrases ("who was on call" ~ "on-call engineer"), BM25 catches
exact tokens that embeddings blur (INC-003, SentinelWatch, "15 March"). RRF fuses by rank, so the
two score scales (cosine 0..1 vs. BM25 unbounded) never have to be compared directly.
"""
import re

import chromadb
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer

from . import config

STOP = {"the", "a", "an", "of", "to", "in", "and", "or", "is", "was", "for", "on", "by", "with", "it",
        "its", "that", "this", "as", "at", "be", "are", "which", "who", "what", "does", "did", "how"}


def tokenize(text: str):
    toks = re.findall(r"[a-z0-9]+", text.lower())
    return [t for t in toks if t not in STOP]


class HybridRetriever:
    def __init__(self):
        self.model = SentenceTransformer(config.EMBED_MODEL)
        client = chromadb.PersistentClient(path=str(config.DB_DIR))
        self.col = client.get_collection(config.COLLECTION)
        data = self.col.get(include=["documents", "metadatas"])
        self.ids, self.docs, self.metas = data["ids"], data["documents"], data["metadatas"]
        self.pos = {i: n for n, i in enumerate(self.ids)}
        self.bm25 = BM25Okapi([tokenize(d) for d in self.docs])

    def search(self, query: str, k: int = config.TOP_K):
        # Dense: query embedding is normalised, collection uses cosine space -> similarity = 1 - distance.
        qv = self.model.encode([query], normalize_embeddings=True)
        res = self.col.query(query_embeddings=qv.tolist(), n_results=min(config.CANDIDATES, len(self.ids)),
                             include=["distances"])
        dense = {cid: 1.0 - dist for cid, dist in zip(res["ids"][0], res["distances"][0])}
        dense_rank = {cid: r for r, cid in enumerate(res["ids"][0], start=1)}

        # Sparse: BM25 over the same chunks.
        scores = self.bm25.get_scores(tokenize(query))
        order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[: config.CANDIDATES]
        bm25_rank = {self.ids[i]: r for r, i in enumerate(order, start=1) if scores[i] > 0}

        fused = {}
        for cid in set(dense_rank) | set(bm25_rank):
            f = 0.0
            if cid in dense_rank:
                f += config.W_DENSE / (config.RRF_K + dense_rank[cid])
            if cid in bm25_rank:
                f += config.W_BM25 / (config.RRF_K + bm25_rank[cid])
            fused[cid] = f
        top = sorted(fused, key=fused.get, reverse=True)[:k]
        out = []
        for cid in top:
            n = self.pos[cid]
            out.append({"id": cid, "text": self.docs[n], "page": self.metas[n]["page"],
                        "section": self.metas[n]["section"], "kind": self.metas[n]["kind"],
                        "cosine": round(dense[cid], 4) if cid in dense else None,
                        "bm25": round(float(scores[n]), 3), "dense_rank": dense_rank.get(cid),
                        "bm25_rank": bm25_rank.get(cid), "rrf": round(fused[cid], 5)})
        return out
