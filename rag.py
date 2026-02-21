from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from schemas import RagCitation

EMBED_MODEL = "text-embedding-3-small"
KB_PATH = Path("data/eu261_kb.jsonl")
CACHE_PATH = Path("data/eu261_embeddings_cache.npz")


def _load_kb(kb_path: Path = KB_PATH) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    if not kb_path.exists():
        return rows
    with kb_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            rows.append(json.loads(line))
    return rows


def _stable_hash_embedding(text: str, dim: int = 256) -> np.ndarray:
    vec = np.zeros(dim, dtype=np.float32)
    tokens = text.lower().split()
    if not tokens:
        return vec
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:4], "big") % dim
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vec[idx] += sign
    norm = np.linalg.norm(vec)
    return vec / norm if norm > 0 else vec


def _normalize(vec: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(vec)
    return vec / norm if norm > 0 else vec


class Eu261RAG:
    def __init__(self, openai_client: Optional[object] = None):
        self.client = openai_client
        self.kb_rows = _load_kb()
        self._embeddings = self._load_or_build_embeddings()

    def _kb_fingerprint(self) -> str:
        h = hashlib.sha256()
        for row in self.kb_rows:
            h.update((row.get("id", "") + row.get("title", "") + row.get("text", "")).encode("utf-8"))
        return h.hexdigest()

    def _load_or_build_embeddings(self) -> np.ndarray:
        fingerprint = self._kb_fingerprint()
        if CACHE_PATH.exists():
            data = np.load(CACHE_PATH, allow_pickle=False)
            cached_fp = str(data["fingerprint"][0])
            if cached_fp == fingerprint:
                return data["embeddings"].astype(np.float32)

        if not self.kb_rows:
            arr = np.empty((0, 256), dtype=np.float32)
            np.savez(CACHE_PATH, embeddings=arr, fingerprint=np.array([fingerprint], dtype=str))
            return arr

        if self.client is None:
            emb = np.vstack([_stable_hash_embedding(row["text"]) for row in self.kb_rows]).astype(np.float32)
            np.savez(CACHE_PATH, embeddings=emb, fingerprint=np.array([fingerprint], dtype=str))
            return emb

        texts = [row["text"] for row in self.kb_rows]
        resp = self.client.embeddings.create(model=EMBED_MODEL, input=texts)
        emb = np.array([item.embedding for item in resp.data], dtype=np.float32)
        norms = np.linalg.norm(emb, axis=1, keepdims=True)
        emb = np.divide(emb, norms, out=np.zeros_like(emb), where=norms > 0)
        np.savez(CACHE_PATH, embeddings=emb, fingerprint=np.array([fingerprint], dtype=str))
        return emb

    def embed_query(self, query: str) -> np.ndarray:
        if self.client is None:
            return _stable_hash_embedding(query)
        resp = self.client.embeddings.create(model=EMBED_MODEL, input=[query])
        return _normalize(np.array(resp.data[0].embedding, dtype=np.float32))

    def retrieve(self, query: str, k: int = 4) -> List[RagCitation]:
        if not self.kb_rows:
            return []
        q = self.embed_query(query)
        scores = (self._embeddings @ q).reshape(-1)
        idxs = np.argsort(scores)[::-1][:k]
        out: List[RagCitation] = []
        for idx in idxs:
            row = self.kb_rows[int(idx)]
            out.append(
                RagCitation(
                    chunk_id=row["id"],
                    title=row["title"],
                    score=float(scores[int(idx)]),
                    text=row["text"],
                )
            )
        return out

