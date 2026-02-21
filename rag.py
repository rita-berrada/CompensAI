from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import re
from typing import Dict, List

from schemas import RagCitation

KB_PATH = Path("data/eu261_kb.jsonl")
INDEX_DB_PATH = Path("data/eu261_rag.sqlite")


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


class Eu261RAG:
    def __init__(self):
        self.kb_rows = _load_kb()
        self._ensure_index()

    def _ensure_index(self) -> None:
        INDEX_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(INDEX_DB_PATH) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS kb (
                    rowid INTEGER PRIMARY KEY AUTOINCREMENT,
                    chunk_id TEXT UNIQUE NOT NULL,
                    title TEXT NOT NULL,
                    text TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")

            current_fp = "|".join(
                f"{row.get('id','')}::{row.get('title','')}::{row.get('text','')}" for row in self.kb_rows
            )
            row = conn.execute("SELECT value FROM meta WHERE key = 'fingerprint'").fetchone()
            cached_fp = row[0] if row else None
            if cached_fp == current_fp:
                return

            conn.execute("DELETE FROM kb")
            conn.execute("DROP TABLE IF EXISTS kb_fts")
            conn.execute("CREATE VIRTUAL TABLE kb_fts USING fts5(title, text, content='kb', content_rowid='rowid')")

            for item in self.kb_rows:
                cur = conn.execute(
                    "INSERT INTO kb (chunk_id, title, text) VALUES (?, ?, ?)",
                    (item["id"], item["title"], item["text"]),
                )
                rowid = cur.lastrowid
                conn.execute(
                    "INSERT INTO kb_fts(rowid, title, text) VALUES (?, ?, ?)",
                    (rowid, item["title"], item["text"]),
                )

            conn.execute(
                "INSERT INTO meta (key, value) VALUES ('fingerprint', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (current_fp,),
            )
            conn.commit()

    def retrieve(self, query: str, k: int = 4) -> List[RagCitation]:
        if not self.kb_rows:
            return []
        tokens = [t for t in re.split(r"[^a-zA-Z0-9]+", query.lower()) if len(t) >= 2]
        fts_query = " OR ".join(tokens[:12]) if tokens else "eu261 OR delay OR compensation"
        out: List[RagCitation] = []
        with sqlite3.connect(INDEX_DB_PATH) as conn:
            try:
                rows = conn.execute(
                    """
                    SELECT kb.chunk_id, kb.title, kb.text, bm25(kb_fts) AS bm25_score
                    FROM kb_fts
                    JOIN kb ON kb.rowid = kb_fts.rowid
                    WHERE kb_fts MATCH ?
                    ORDER BY bm25_score
                    LIMIT ?
                    """,
                    (fts_query, int(k)),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = conn.execute(
                    """
                    SELECT chunk_id, title, text, 9.0 AS bm25_score
                    FROM kb
                    WHERE lower(title) LIKE ? OR lower(text) LIKE ?
                    LIMIT ?
                    """,
                    (f"%{query.lower()}%", f"%{query.lower()}%", int(k)),
                ).fetchall()

        for chunk_id, title, text, bm25_score in rows:
            score = 1.0 / (1.0 + abs(float(bm25_score)))
            out.append(RagCitation(chunk_id=chunk_id, title=title, text=text, score=score))
        return out
